#!/usr/bin/env python3
"""Dispatch opencode agents into isolated git worktrees and collect their work.

Python 3 standard library only. Structured JSON to stdout, diagnostics to stderr.
Run with --help, or `<command> --help`, for the interface.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

STATE_DIR_NAME = ".opencode-agents"
BRANCH_PREFIX = "opencode_"
# 900 killed every one of three measured CODE_GitTracker tasks just short of
# finishing (950-1008s each). Wall clock, not step count, is what binds.
DEFAULT_TIMEOUT = 1800
# One at a time. The endpoint serves a single local model on one machine, so
# concurrent agents contend for the same GPU rather than using idle capacity —
# they do not finish sooner, they all finish later and closer to the timeout.
DEFAULT_PARALLEL = 1
DEFAULT_RETRIES = 2

# Context budget. The local models are small; the window is the binding
# constraint on what a task can be, so peak usage is reported per task.
# Measured on 2026-08-09 against ham51-2/qwen/qwen3.5-9b: ~4,900 tokens of fixed
# overhead with a restricted toolset (5,500 with the full one), then ~1.9K per
# step. 128K therefore buys roughly 60 tool calls. The endpoint actually serves
# 262,144, but a 9B Q4's useful reasoning span is far shorter than its
# architectural maximum, so this is a working budget, not a hard limit.
DEFAULT_CONTEXT_LIMIT = 128000
CONTEXT_WARN_FRACTION = 0.75

# Exit codes (documented in --help)
EX_OK = 0
EX_FAIL = 1          # one or more tasks failed
EX_USAGE = 2         # bad arguments / bad task file
EX_PREFLIGHT = 3     # environment not usable (no opencode, bad model, dirty repo)

# opencode's own session ledger. Every run through the CLI *and* through the
# TUI writes a row here, which is what lets `tokens` report on /herdr-agents —
# that skill drives the TUI and so has no stream of its own to parse.
#
# Deliberately read-only everywhere below: this file also holds credentials
# (see DEVCONTAINER/CLAUDE.md on why opencode gets no host mount), and it is
# opencode's live WAL database, not ours to write.
OPENCODE_DB = Path.home() / ".local/share/opencode/opencode.db"
# One worktree per task is the contract in both skills, so the directory's last
# segment is the task id. herdr puts them under ~/.herdr/worktrees/<repo>/<task>,
# this script under <project>/.opencode-agents/worktrees/<task>.
HERDR_WORKTREE_MARK = "/.herdr/worktrees/"
SELF_WORKTREE_MARK = "/%s/worktrees/" % STATE_DIR_NAME

ANSI_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")
# opencode prints these to the console when --agent does not resolve to a
# usable primary agent. It then runs the DEFAULT agent and exits 0.
FALLBACK_RE = re.compile(
    r'agent "([^"]+)" (?:not found|is a subagent[^.]*)\. Falling back to default agent'
)


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------

def strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text)


def die(msg: str, code: int = EX_USAGE) -> "NoReturn":  # type: ignore[name-defined]
    print(msg, file=sys.stderr)
    sys.exit(code)


def emit(payload: dict) -> None:
    """Structured result to stdout."""
    json.dump(payload, sys.stdout, indent=2)
    sys.stdout.write("\n")


def run(cmd: list[str], cwd: Path | None = None, timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        timeout=timeout,
        stdin=subprocess.DEVNULL,
    )


def git(args: list[str], cwd: Path, timeout: int = 120) -> subprocess.CompletedProcess:
    return run(["git", *args], cwd=cwd, timeout=timeout)


def strip_jsonc(text: str) -> str:
    """Remove // and /* */ comments outside of strings. Enough for opencode.jsonc."""
    out, i, n = [], 0, len(text)
    in_str = False
    while i < n:
        ch = text[i]
        if in_str:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if ch == '"':
                in_str = False
            i += 1
            continue
        if ch == '"':
            in_str = True
            out.append(ch)
            i += 1
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "/":
            while i < n and text[i] != "\n":
                i += 1
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "*":
            i += 2
            while i + 1 < n and not (text[i] == "*" and text[i + 1] == "/"):
                i += 1
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


# --------------------------------------------------------------------------
# project / state
# --------------------------------------------------------------------------

def resolve_project(raw: str | None) -> Path:
    project = Path(raw).expanduser().resolve() if raw else Path.cwd().resolve()
    if not project.is_dir():
        die(f"Error: --project path does not exist: {project}")
    if not (project / ".git").exists():
        die(
            f"Error: {project} is not a git repository.\n"
            "       Agent isolation uses git worktrees, so a repo is required.\n"
            "       Run /project-bootstrap first, or pass --project PATH.",
            EX_PREFLIGHT,
        )
    return project


def state_dir(project: Path) -> Path:
    return project / STATE_DIR_NAME


def state_path(project: Path) -> Path:
    return state_dir(project) / "state.json"


def load_state(project: Path) -> dict:
    p = state_path(project)
    if not p.exists():
        return {"tasks": {}}
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError as exc:
        die(f"Error: corrupt state file {p}: {exc}\n       Delete it to start over.")


def save_state(project: Path, state: dict) -> None:
    d = state_dir(project)
    (d / "logs").mkdir(parents=True, exist_ok=True)
    state_path(project).write_text(json.dumps(state, indent=2) + "\n")
    ensure_excluded(project)


def ensure_excluded(project: Path) -> None:
    """Keep .opencode-agents/ out of git status without touching .gitignore."""
    exclude = project / ".git" / "info" / "exclude"
    line = f"{STATE_DIR_NAME}/"
    try:
        exclude.parent.mkdir(parents=True, exist_ok=True)
        existing = exclude.read_text() if exclude.exists() else ""
        if line not in existing.split():
            with exclude.open("a") as fh:
                if existing and not existing.endswith("\n"):
                    fh.write("\n")
                fh.write(line + "\n")
    except OSError as exc:  # a worktree's .git is a file, not a dir
        print(f"warn: could not update .git/info/exclude: {exc}", file=sys.stderr)


# --------------------------------------------------------------------------
# preflight
# --------------------------------------------------------------------------

def opencode_bin() -> str:
    found = shutil.which("opencode")
    if not found:
        die(
            "Error: `opencode` is not on PATH.\n"
            "       Install it, or add its bin directory (commonly ~/.opencode/bin) to PATH.",
            EX_PREFLIGHT,
        )
    return found


def sandbox_status() -> dict:
    """Can we confine an agent to its worktree on this machine?

    bubblewrap only. It needs no root, and Ubuntu ships an AppArmor profile that
    lets it use user namespaces even with apparmor_restrict_unprivileged_userns=1.
    """
    if sys.platform != "linux":
        return {"available": False,
                "reason": f"bubblewrap is Linux-only; this is {sys.platform}."}
    binary = shutil.which("bwrap")
    if not binary:
        return {"available": False,
                "reason": "bwrap is not installed. On Debian/Ubuntu: apt install bubblewrap."}
    probe = run([binary, "--ro-bind", "/", "/", "--dev", "/dev", "--tmpfs", "/tmp",
                 "/bin/true"], timeout=30)
    if probe.returncode != 0:
        return {"available": False, "path": binary,
                "reason": "bwrap is installed but cannot create a namespace here: "
                          + (probe.stderr.strip()[:200] or f"exit {probe.returncode}")}
    return {"available": True, "path": binary}


def sandbox_home(project: Path, tid: str) -> Path:
    return state_dir(project) / "sandbox" / tid


def wrap_in_sandbox(cmd: list[str], wt: Path, home: Path) -> list[str]:
    """Confine cmd so the only writable paths are the worktree and its own state.

    Everything else is bind-mounted read-only, so a write outside fails loudly
    with an error the agent reports, rather than landing in the calling repo.
    The project's .git stays read-only on purpose — verified sufficient, and it
    keeps an agent from corrupting git metadata. The dispatcher commits from
    outside the sandbox afterwards.
    """
    home.mkdir(parents=True, exist_ok=True)
    args = [
        "bwrap",
        "--ro-bind", "/", "/",
        "--dev", "/dev", "--proc", "/proc", "--tmpfs", "/tmp",
        "--bind", str(wt), str(wt),
        "--bind", str(home), str(home),
    ]
    # Read-only view of the real opencode config, so the provider, API key, npm
    # provider package, and any global agent files still resolve under $HOME.
    real_cfg = Path.home() / ".config" / "opencode"
    if real_cfg.is_dir():
        args += ["--ro-bind", str(real_cfg), str(home / ".config" / "opencode")]
    args += [
        "--setenv", "HOME", str(home),
        "--setenv", "XDG_CONFIG_HOME", str(home / ".config"),
        "--setenv", "XDG_DATA_HOME", str(home / ".local" / "share"),
        "--setenv", "PWD", str(wt),
        "--chdir", str(wt),
        "--die-with-parent",
        "--unshare-pid",
    ]
    return args + cmd


def list_models() -> list[str]:
    proc = run([opencode_bin(), "models"], timeout=60)
    if proc.returncode != 0:
        return []
    return [ln.strip() for ln in strip_ansi(proc.stdout).splitlines() if "/" in ln]


def config_default_model() -> tuple[str | None, Path | None]:
    cfg = Path.home() / ".config" / "opencode" / "opencode.jsonc"
    if not cfg.exists():
        alt = Path.home() / ".config" / "opencode" / "opencode.json"
        cfg = alt if alt.exists() else cfg
    if not cfg.exists():
        return None, None
    try:
        data = json.loads(strip_jsonc(cfg.read_text()))
    except (json.JSONDecodeError, OSError):
        return None, cfg
    model = data.get("model")
    return (model if isinstance(model, str) else None), cfg


def discover_agents(project: Path) -> list[dict]:
    """Agent definitions opencode will see, project-local first."""
    agents: dict[str, dict] = {}
    roots = [
        (Path.home() / ".config" / "opencode" / "agent", "global"),
        (project / ".opencode" / "agent", "project"),
    ]
    for root, scope in roots:
        if not root.is_dir():
            continue
        for md in sorted(root.glob("*.md")):
            mode, desc = parse_agent_md(md)
            agents[md.stem] = {
                "name": md.stem,
                "scope": scope,
                "mode": mode,
                "description": desc,
                "path": str(md),
                "usable_with_run": mode in ("primary", "all"),
            }
    return list(agents.values())


def parse_agent_md(path: Path) -> tuple[str, str]:
    """Minimal frontmatter read: mode and description. PyYAML is not installed."""
    mode, desc = "all", ""  # opencode's own default when `mode` is absent
    try:
        text = path.read_text()
    except OSError:
        return mode, desc
    if not text.startswith("---"):
        return mode, desc
    end = text.find("\n---", 3)
    block = text[3:end] if end != -1 else text[3:]
    for line in block.splitlines():
        if ":" not in line or line.strip().startswith("#"):
            continue
        key, _, val = line.partition(":")
        key, val = key.strip(), val.strip().strip("'\"")
        if key == "mode" and val:
            mode = val
        elif key == "description" and val:
            desc = val
    return mode, desc


def cmd_check(args: argparse.Namespace) -> int:
    project = resolve_project(args.project)
    binary = opencode_bin()
    ver = run([binary, "--version"], timeout=60).stdout.strip()
    models = list_models()
    cfg_model, cfg_path = config_default_model()

    problems: list[str] = []
    if not models:
        problems.append("`opencode models` returned nothing — no provider is configured.")
    if cfg_model and models and cfg_model not in models:
        problems.append(
            f"Config default model {cfg_model!r} in {cfg_path} is not a real model id. "
            f"Bare `opencode run` will fail. Always pass --model, or fix the config."
        )

    chosen = args.model or (cfg_model if cfg_model in models else None)
    if not chosen and models:
        non_free = [m for m in models if not m.endswith("-free")]
        chosen = (non_free or models)[0]
    if chosen and models and chosen not in models:
        problems.append(f"--model {chosen!r} is not in `opencode models`.")

    agents = discover_agents(project)
    unusable = [a["name"] for a in agents if not a["usable_with_run"]]
    if unusable:
        problems.append(
            "These agents have mode other than primary/all, so `opencode run --agent` "
            "silently falls back to the default agent: " + ", ".join(unusable)
        )

    sandbox = sandbox_status()
    emit({
        "opencode": {"path": binary, "version": ver},
        "project": str(project),
        "models": models,
        "config_default_model": cfg_model,
        "resolved_model": chosen,
        "agents": agents,
        "sandbox": sandbox,
        "problems": problems,
        "ok": not problems,
    })
    return EX_OK if not problems else EX_PREFLIGHT


def cmd_agents(args: argparse.Namespace) -> int:
    project = resolve_project(args.project)
    emit({"project": str(project), "agents": discover_agents(project)})
    return EX_OK


# --------------------------------------------------------------------------
# tokens
# --------------------------------------------------------------------------

def _model_id(raw) -> str:
    """The session table stores `model` as a JSON object, not a bare string.

    Observed: {"id":"qwen/qwen3.6-35b-a3b","providerID":"ham51-2",...}. Older rows
    may hold a plain string, so both shapes are accepted rather than assumed.
    """
    if not raw:
        return "-"
    if isinstance(raw, str) and not raw.startswith("{"):
        return raw
    try:
        d = json.loads(raw) if isinstance(raw, str) else raw
    except (ValueError, TypeError):
        return str(raw)[:60]
    if not isinstance(d, dict):
        return str(raw)[:60]
    prov, mid = d.get("providerID"), d.get("id")
    return f"{prov}/{mid}" if prov and mid else str(mid or "-")


def _task_of(directory: str) -> tuple[str | None, str | None]:
    """(runner, task id) for a session, from the worktree it ran in.

    Returns (None, None) for an ordinary interactive session, which is how a
    hand-run opencode is told apart from an agent dispatched by either skill.
    """
    if not directory:
        return None, None
    d = directory.rstrip("/")
    if HERDR_WORKTREE_MARK in d:
        return "herdr-agents", d.rsplit("/", 1)[-1]
    if SELF_WORKTREE_MARK in d:
        return "opencode-agents", d.rsplit("/", 1)[-1]
    return None, None


def read_sessions(since_days: int | None, directory: str | None) -> list[dict]:
    """Session rows from opencode's ledger, newest first.

    sqlite3 is stdlib, so this adds no dependency. Opened read-only through a
    file: URI so a corrupt or busy database fails as an error rather than
    silently creating an empty one beside it.
    """
    import sqlite3
    if not OPENCODE_DB.exists():
        die(
            f"No opencode session database at {OPENCODE_DB}.\n"
            "       Nothing has run yet, or this is a devcontainer — opencode's\n"
            "       state is deliberately unmounted there, so a rebuild resets it.",
            EX_PREFLIGHT,
        )
    try:
        con = sqlite3.connect(f"file:{OPENCODE_DB}?mode=ro", uri=True, timeout=5)
    except sqlite3.Error as exc:
        die(f"Could not open {OPENCODE_DB}: {exc}", EX_PREFLIGHT)

    where, params = [], []
    if since_days:
        cutoff = int((time.time() - since_days * 86400) * 1000)
        where.append("time_created >= ?")
        params.append(cutoff)
    if directory:
        where.append("directory LIKE ?")
        params.append(f"{directory.rstrip('/')}%")
    sql = (
        "SELECT id, time_created, directory, title, model, agent, cost, "
        "tokens_input, tokens_output, tokens_reasoning, "
        "tokens_cache_read, tokens_cache_write FROM session"
    )
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY time_created DESC"
    try:
        rows = con.execute(sql, params).fetchall()
    except sqlite3.Error as exc:
        die(f"Could not read the session table: {exc}", EX_PREFLIGHT)
    finally:
        con.close()

    out = []
    for r in rows:
        runner, task = _task_of(r[2] or "")
        inp, outp, reas = (r[7] or 0), (r[8] or 0), (r[9] or 0)
        out.append({
            "session": r[0],
            "started": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime((r[1] or 0) / 1000)),
            "directory": r[2] or "",
            "runner": runner,
            "task": task,
            "title": (r[3] or "").strip()[:80] or None,
            "model": _model_id(r[4]),
            "agent": r[5] or None,
            # Local providers carry no pricing, so this is 0.0 for ham51-2/* and
            # only meaningful for a hosted provider. Reported, never summed into
            # a headline that would read as free when it is merely unpriced.
            "cost": r[6] or 0.0,
            "tokens": {
                "input": inp, "output": outp, "reasoning": reas,
                "cache_read": r[10] or 0, "cache_write": r[11] or 0,
                "total": inp + outp + reas,
            },
        })
    return out


def cmd_tokens(args: argparse.Namespace) -> int:
    directory = None
    if args.here:
        directory = str(resolve_project(args.project))
    sessions = read_sessions(args.since, directory)
    if args.agents_only:
        sessions = [s for s in sessions if s["runner"]]

    by_model: dict[str, dict] = {}
    by_runner: dict[str, dict] = {}
    totals = {"input": 0, "output": 0, "reasoning": 0, "total": 0}
    for s in sessions:
        t = s["tokens"]
        for k in totals:
            totals[k] += t[k]
        for bucket, key in ((by_model, s["model"]), (by_runner, s["runner"] or "interactive")):
            b = bucket.setdefault(key, {"sessions": 0, "input": 0, "output": 0, "total": 0})
            b["sessions"] += 1
            for k in ("input", "output", "total"):
                b[k] += t[k]

    unpriced = any(s["model"].startswith("ham51-2/") for s in sessions)
    payload = {
        "database": str(OPENCODE_DB),
        "since_days": args.since,
        "directory": directory,
        "sessions": len(sessions),
        "totals": totals,
        "by_model": by_model,
        "by_runner": by_runner,
        # Named so a reader cannot mistake an unpriced local run for a free one.
        "cost_note": ("local provider has no pricing configured; cost is not tracked"
                      if unpriced else None),
    }
    if not args.summary:
        payload["detail"] = sessions[: args.limit]
    emit(payload)
    return EX_OK


# --------------------------------------------------------------------------
# dispatch
# --------------------------------------------------------------------------

TASK_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def validate_files(tid: str, raw, project: Path) -> list[str]:
    """Check a task's `files` list and return it normalised.

    Paths must be relative to the project root, because the agent runs inside a
    worktree cut from that root and — under --sandbox — can read nothing else.
    An absolute path or a `..` escape would resolve outside the worktree and
    fail there rather than here, so both are refused up front.
    """
    if raw is None:
        return []
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list) or not all(isinstance(f, str) for f in raw):
        die(f'Error: task {tid!r} has a "files" value that is not a list of strings.')

    out: list[str] = []
    for f in raw:
        f = f.strip()
        if not f:
            continue
        if Path(f).is_absolute() or os.path.isabs(f):
            die(
                f"Error: task {tid!r} attaches an absolute path {f!r}.\n"
                "       Attachments must be relative to the project root — the agent runs in a\n"
                "       worktree, and under --sandbox nothing outside it is readable."
            )
        norm = os.path.normpath(f)
        if norm == ".." or norm.startswith(".." + os.sep):
            die(f"Error: task {tid!r} attaches {f!r}, which escapes the project root.")
        if not (project / norm).exists():
            die(
                f"Error: task {tid!r} attaches {f!r}, which does not exist in {project}.\n"
                "       Attachments are resolved in the worktree, which is checked out from\n"
                "       HEAD — so an uncommitted file is not there either."
            )
        out.append(norm)
    return out


def load_tasks(path: str, project: Path) -> tuple[list[dict], dict]:
    p = Path(path).expanduser()
    if not p.exists():
        die(f"Error: task file not found: {p}")
    try:
        data = json.loads(p.read_text())
    except json.JSONDecodeError as exc:
        die(f"Error: {p} is not valid JSON: {exc}")

    defaults: dict = {}
    if isinstance(data, dict):
        defaults = {k: v for k, v in data.items() if k != "tasks"}
        tasks = data.get("tasks")
    else:
        tasks = data
    if not isinstance(tasks, list) or not tasks:
        die(
            f"Error: {p} must be a JSON array of tasks, or an object with a non-empty "
            '"tasks" array.\n'
            '       Task shape: {"id": "t1", "prompt": "...", "agent": "optional-name"}'
        )

    seen = set()
    for i, t in enumerate(tasks):
        if not isinstance(t, dict):
            die(f"Error: task #{i} is not an object.")
        tid = str(t.get("id") or "").strip()
        if not tid:
            die(f'Error: task #{i} has no "id". Ids become branch names, so one is required.')
        if not TASK_ID_RE.match(tid):
            die(
                f"Error: task id {tid!r} is not usable as a git branch name.\n"
                "       Allowed: letters, digits, dot, underscore, hyphen; must start alphanumeric."
            )
        if tid in seen:
            die(f"Error: duplicate task id {tid!r}. Ids must be unique.")
        seen.add(tid)
        if not str(t.get("prompt") or "").strip():
            die(f'Error: task {tid!r} has an empty "prompt".')
        t["files"] = validate_files(tid, t.get("files"), project)
    return tasks, defaults


_PRINT_LOCK = threading.Lock()


def say(line: str) -> None:
    """One progress line to stderr. Locked so parallel agents cannot interleave."""
    with _PRINT_LOCK:
        sys.stderr.write(line + "\n")
        sys.stderr.flush()


def describe_event(ev: dict, wt: Path | None = None) -> str | None:
    """Turn one NDJSON event into a short progress line, or None to stay quiet.

    Event vocabulary, confirmed against opencode 1.18.15:
      step_start | tool_use | text | step_finish
    The tool name is at part.tool; part.type is the string "tool".
    """
    etype = ev.get("type")
    part = ev.get("part") or {}

    if etype == "tool_use":
        state = part.get("state") or {}
        inp = state.get("input") or {}
        target = (inp.get("filePath") or inp.get("path") or inp.get("command")
                  or inp.get("pattern") or inp.get("query") or "")
        target = str(target).replace("\n", " ")
        if target.startswith("/") and wt:
            # Show the path as the agent's own working tree sees it. A bare
            # basename would hide "docs/", and the absolute path would drag in
            # the worktree directory and read like a stray subdirectory.
            try:
                target = str(Path(target).relative_to(wt))
            except ValueError:
                pass
        if len(target) > 60:
            target = target[:57] + "..."
        status = state.get("status")
        suffix = f" [{status}]" if status and status not in ("completed", "success") else ""
        return f"{part.get('tool') or 'tool'} {target}".rstrip() + suffix

    if etype == "text":
        text = (part.get("text") or "").strip().replace("\n", " ")
        return f"· {text[:100]}" if text else None

    if etype == "step_finish":
        total = (part.get("tokens") or {}).get("total")
        return f"— step done ({total:,} tokens)" if isinstance(total, int) else None

    if etype == "error" or ev.get("error"):
        return "ERROR " + json.dumps(ev.get("error") or ev)[:160]

    return None  # step_start and anything unrecognised


def _pump(stream, sink: list, on_line=None) -> None:
    """Drain a pipe line by line into sink, calling on_line as each arrives."""
    try:
        for line in stream:
            sink.append(line)
            if on_line:
                try:
                    on_line(line)
                except Exception:
                    pass  # a progress line must never kill the run
    finally:
        try:
            stream.close()
        except Exception:
            pass


def run_streaming(cmd: list[str], cwd: Path, env: dict, timeout: int,
                  on_stdout=None) -> tuple[int, str, str, bool]:
    """Run cmd, consuming stdout/stderr as they arrive rather than at exit.

    subprocess.run(capture_output=True) buffers until the process exits, which is
    why a long agent used to be completely silent. Reading both pipes in threads
    also avoids the deadlock that a single blocking read would risk.
    """
    proc = subprocess.Popen(
        cmd, cwd=str(cwd), env=env, text=True, bufsize=1,
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        start_new_session=True,
    )
    out_lines: list[str] = []
    err_lines: list[str] = []
    threads = [
        threading.Thread(target=_pump, args=(proc.stdout, out_lines, on_stdout), daemon=True),
        threading.Thread(target=_pump, args=(proc.stderr, err_lines), daemon=True),
    ]
    for t in threads:
        t.start()

    timed_out = False
    try:
        rc = proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        try:  # kill the whole group; opencode spawns children
            os.killpg(proc.pid, 15)
            proc.wait(timeout=10)
        except Exception:
            pass
        try:
            os.killpg(proc.pid, 9)
        except Exception:
            pass
        rc = proc.poll() if proc.poll() is not None else -1

    for t in threads:
        t.join(timeout=10)
    return rc, "".join(out_lines), "".join(err_lines), timed_out


def parse_events(stdout: str) -> dict:
    """Pull the assistant's final text and token totals out of --format json NDJSON."""
    texts: list[str] = []
    tokens = {"input": 0, "output": 0, "reasoning": 0}
    errors: list[str] = []
    tools: list[str] = []
    # Input tokens on a step are the whole conversation resent, so the largest
    # of them is the high-water mark of context — the number that predicts
    # whether a task will run out of room. The summed totals below cannot show
    # it: they grow with step count even when each step stays small.
    peak_input = 0
    steps = 0
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        etype = ev.get("type")
        part = ev.get("part") or {}
        if etype == "text" and part.get("text"):
            texts.append(part["text"])
        elif etype in ("tool_use", "tool") and part.get("tool"):
            # The event type is "tool_use"; part.type is "tool". Matching on the
            # latter is why this list used to come back empty on every run.
            tools.append(part["tool"])
        elif etype == "step_finish":
            steps += 1
            tk = part.get("tokens") or {}
            for k in tokens:
                if isinstance(tk.get(k), int):
                    tokens[k] += tk[k]
            if isinstance(tk.get("input"), int):
                peak_input = max(peak_input, tk["input"])
        elif etype == "error" or ev.get("error"):
            errors.append(json.dumps(ev)[:500])
    return {
        "text": "\n".join(texts).strip(),
        "tokens": tokens,
        "peak_input": peak_input,
        "steps": steps,
        "tool_calls": sorted(set(tools)),
        "errors": errors,
    }


def context_report(parsed: dict, limit: int) -> dict:
    """How close this task came to running out of window.

    A task that fills its context does not fail — it gets vague, forgets the
    interface it was given, and re-reads files it already has. That degradation
    is invisible in the exit code, so the high-water mark is reported for every
    task whether it passed or not.
    """
    peak = parsed.get("peak_input") or 0
    steps = parsed.get("steps") or 0
    report = {
        "peak_tokens": peak,
        "limit": limit,
        "pct": round(100 * peak / limit) if limit else None,
        "steps": steps,
        "tokens_per_step": round(peak / steps) if steps else None,
    }
    if limit and peak >= limit * CONTEXT_WARN_FRACTION:
        report["warning"] = (
            f"peak context {peak:,} tokens = {report['pct']}% of the {limit:,} budget over "
            f"{steps} steps. Treat this task's output as suspect and split it: attach the "
            f"files it needed via \"files\" instead of letting it search, or narrow its scope."
        )
    return report


def worktree_path(project: Path, tid: str) -> Path:
    return state_dir(project) / "worktrees" / tid


def create_worktree(project: Path, tid: str, base: str) -> tuple[Path, str]:
    wt = worktree_path(project, tid)
    branch = f"{BRANCH_PREFIX}{tid}"
    if wt.exists():
        raise RuntimeError(
            f"worktree already exists at {wt} — run `cleanup --task {tid}` first"
        )
    wt.parent.mkdir(parents=True, exist_ok=True)
    proc = git(["worktree", "add", "-b", branch, str(wt), base], cwd=project)
    if proc.returncode != 0:
        raise RuntimeError(f"git worktree add failed: {proc.stderr.strip()}")
    return wt, branch


def commit_worktree(wt: Path, tid: str, prompt: str, attached: list[str] | None = None) -> dict:
    git(["add", "-A"], cwd=wt)
    status = git(["status", "--porcelain"], cwd=wt).stdout.strip()
    if not status:
        return {"committed": False, "files_changed": 0, "commit": None}
    subject = prompt.strip().splitlines()[0][:60]
    proc = git(
        ["-c", "user.email=opencode@local", "-c", "user.name=opencode-agent",
         "commit", "-m", f"opencode({tid}): {subject}"],
        cwd=wt,
    )
    if proc.returncode != 0:
        return {"committed": False, "files_changed": 0, "commit": None,
                "commit_error": proc.stderr.strip()[:300]}
    sha = git(["rev-parse", "HEAD"], cwd=wt).stdout.strip()
    stat = git(["show", "--stat", "--oneline", "HEAD"], cwd=wt).stdout
    files = [ln for ln in status.splitlines() if ln.strip()]
    out = {"committed": True, "files_changed": len(files), "commit": sha,
           "files": [ln[3:] for ln in files][:50], "stat": stat[:2000]}
    # An attached file is the contract the task must conform to. Nothing in
    # opencode stops the agent editing it — --sandbox confines writes to the
    # worktree, and the contract is *in* the worktree — so the only guard
    # available is to notice afterwards. Read from the commit, not the capped
    # `files` list above, or a violation past the 50th path would be invisible.
    # `-z` and a NUL split, not `.split()`: whitespace-splitting breaks any path
    # containing a space into fragments that match nothing, so the guard silently
    # passes on exactly the paths it should catch. `-z` also stops git quoting
    # and escaping non-ASCII names, which would fail to match `attached` too.
    if attached:
        touched = [
            p for p in git(["show", "--name-only", "-z", "--pretty=format:", "HEAD"],
                           cwd=wt).stdout.split("\0") if p
        ]
        violated = sorted(set(attached) & set(touched))
        if violated:
            out["contract_violations"] = violated
    return out


def is_transient(rc: int, parsed: dict) -> bool:
    """A provider hiccup, not a task failure.

    The observed shape is exit 1 within a couple of seconds, zero tokens, no tool
    calls, and an UnknownError / 'Unexpected server error' event. A self-hosted
    endpoint does this while a model loads or swaps. Retrying works; treating it
    as a real failure wastes the task.
    """
    if rc == 0:
        return False
    if parsed["tokens"]["output"] or parsed["tool_calls"]:
        return False  # it did real work; a retry could double-apply it
    blob = " ".join(parsed["errors"]).lower()
    return "unexpectedservererror" in blob.replace(" ", "") or \
           "unexpected server error" in blob or "unknownerror" in blob


def reset_worktree(wt: Path, base: str) -> None:
    """Put a worktree back to its starting state before a retry."""
    git(["reset", "--hard", base], cwd=wt)
    git(["clean", "-fdx"], cwd=wt)


def run_one(project: Path, task: dict, cfg: dict) -> dict:
    tid = task["id"]
    prompt = task["prompt"]
    agent = task.get("agent") or cfg.get("agent")
    model = task.get("model") or cfg["model"]
    timeout = int(task.get("timeout") or cfg["timeout"])
    retries = int(cfg.get("retries", 0))
    files = task.get("files") or []
    started = time.time()
    result: dict = {"id": tid, "agent": agent, "model": model, "status": "failed"}
    if files:
        result["files_attached"] = files

    try:
        wt, branch = create_worktree(project, tid, cfg["base"])
    except RuntimeError as exc:
        result["error"] = str(exc)
        return result
    result["worktree"] = str(wt)
    result["branch"] = branch

    cmd = [opencode_bin(), "run", "--auto", "--format", "json", "-m", model]
    if agent:
        cmd += ["--agent", agent]
    for f in files:
        cmd += ["--file", f]
    # `--file` takes an array, so yargs keeps eating positionals after it and
    # swallows the prompt — the observed symptom is
    # `Error: File not found: <the entire prompt>`. The `--` terminates it.
    # Harmless when nothing is attached, so it is always passed rather than
    # conditionally, which would make the two paths differ.
    cmd += ["--", prompt]

    result["sandboxed"] = bool(cfg.get("sandbox"))
    if cfg.get("sandbox"):
        cmd = wrap_in_sandbox(cmd, wt, sandbox_home(project, tid))

    log = state_dir(project) / "logs" / f"{tid}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("")  # truncate; this run owns the file from here on

    # opencode resolves its project root from $PWD, not from the real working
    # directory. subprocess sets cwd but leaves PWD pointing at the parent
    # process's directory, so without this the agent loads the WRONG repository
    # and the request fails at the provider with zero tokens. See SKILL.md.
    env = dict(os.environ, PWD=str(wt))
    stream = bool(cfg.get("stream"))

    def on_stdout(line: str) -> None:
        """Called per NDJSON line as it arrives, from the reader thread."""
        with _PRINT_LOCK:
            with log.open("a") as fh:      # append now, so `tail -f` works live
                fh.write(line)
        if not stream:
            return
        raw = line.strip()
        if not raw.startswith("{"):
            return
        try:
            ev = json.loads(raw)
        except json.JSONDecodeError:
            return
        desc = describe_event(ev, wt)
        if desc:
            say(f"  [{tid}] {desc}")

    for attempt in range(retries + 1):
        if attempt:
            time.sleep(min(2 ** attempt, 15))
            reset_worktree(wt, cfg["base"])
            if stream:
                say(f"  [{tid}] retrying (attempt {attempt + 1}/{retries + 1})")
        with _PRINT_LOCK:
            with log.open("a") as fh:
                fh.write(f"=== attempt {attempt + 1}/{retries + 1} ===\n"
                         f"$ {' '.join(cmd[:-1])} <prompt>\ncwd: {wt}\n--- stdout ---\n")

        rc, out, err, timed_out = run_streaming(cmd, wt, env, timeout, on_stdout)

        err_clean = strip_ansi(err)
        parsed = parse_events(out)
        with _PRINT_LOCK:
            with log.open("a") as fh:
                fh.write(f"--- stderr ---\n{err_clean}\n--- rc: {rc} ---\n")
        if timed_out or not is_transient(rc, parsed):
            break
    result["log"] = str(log)
    result["elapsed_sec"] = round(time.time() - started, 1)
    result["exit_code"] = rc
    result["attempts"] = attempt + 1
    result["reply"] = parsed["text"][:4000]
    result["tokens"] = parsed["tokens"]
    result["tool_calls"] = parsed["tool_calls"]
    result["context"] = context_report(parsed, int(cfg.get("context_limit") or DEFAULT_CONTEXT_LIMIT))
    if result["context"].get("warning") and stream:
        say(f"  [{tid}] {result['context']['warning']}")

    # opencode exits 0 after silently substituting the default agent.
    fallback = FALLBACK_RE.search(err_clean) or FALLBACK_RE.search(strip_ansi(out))
    if agent and fallback:
        result["status"] = "agent_mismatch"
        result["error"] = (
            f"Requested agent {agent!r} did not run — opencode fell back to its default "
            f"agent and still exited 0. Cause: {fallback.group(0)}. "
            "Fix the agent file (mode must be primary or all) or the name."
        )
        return result

    if timed_out:
        result["status"] = "timeout"
        result["error"] = f"No completion within {timeout}s. Raise --timeout or split the task."
        return result
    if rc != 0:
        result["status"] = "transient" if is_transient(rc, parsed) else "failed"
        err_text = err_clean.strip() or "; ".join(parsed["errors"]) or f"exit code {rc}"
        if result["status"] == "transient":
            err_text = (
                f"Provider error on every one of {attempt + 1} attempt(s); the model never "
                f"produced a token. Check the endpoint is up, then re-dispatch. Last: {err_text}"
            )
        result["error"] = str(err_text)[:1000]
        return result

    result.update(commit_worktree(wt, tid, prompt, files))
    result["status"] = "done" if result.get("committed") else "no-changes"
    if result.get("contract_violations"):
        result["status"] = "contract_violation"
        result["error"] = (
            "Modified files it was given to conform to: "
            + ", ".join(result["contract_violations"])
            + ". The commit is kept for inspection but must not be merged as-is — "
            "an agent that edits the contract can make any test pass."
        )
    return result


def cmd_dispatch(args: argparse.Namespace) -> int:
    project = resolve_project(args.project)
    tasks, defaults = load_tasks(args.tasks, project)

    models = list_models()
    cfg_model, _ = config_default_model()
    model = args.model or defaults.get("model") or (cfg_model if cfg_model in models else None)
    if not model:
        die(
            "Error: no model resolved. Pass --model, or set \"model\" in the task file.\n"
            "       Available: " + (", ".join(models) if models else "(none — run `check`)"),
            EX_PREFLIGHT,
        )
    if models and model not in models:
        die(
            f"Error: model {model!r} is not available.\n       Available: " + ", ".join(models),
            EX_PREFLIGHT,
        )

    base = args.base or git(["rev-parse", "HEAD"], cwd=project).stdout.strip()
    if not base:
        die("Error: repository has no commits yet — make one before dispatching.", EX_PREFLIGHT)

    sandbox = args.sandbox or bool(defaults.get("sandbox"))
    if sandbox:
        status = sandbox_status()
        if not status["available"]:
            die(
                f"Error: --sandbox requested but unavailable. {status['reason']}\n"
                "       Re-run without --sandbox to dispatch unconfined, but note that\n"
                "       agents can then write anywhere the calling user can.",
                EX_PREFLIGHT,
            )

    parallel = max(1, args.parallel)
    if parallel > 1:
        say(f"warn: --parallel {parallel} runs {parallel} agents against one local "
            "endpoint; on single-GPU hardware they contend and every task slows "
            "toward its timeout. The default is 1 for that reason.")
    # Streaming is on by default only when one agent can run at a time. Key off
    # how many actually run concurrently, not on --parallel alone: a single task
    # under an explicit --parallel 3 is still one agent, and should stream.
    # Above one they interleave; the task-id prefix keeps that readable, but it
    # is opt-in rather than the default.
    # NB: not named `concurrent` — that shadows the concurrent.futures module.
    concurrency = min(parallel, len(tasks))
    stream = (concurrency == 1) if args.stream is None else args.stream

    cfg = {
        "model": model,
        "agent": args.agent or defaults.get("agent"),
        "timeout": args.timeout or defaults.get("timeout") or DEFAULT_TIMEOUT,
        "retries": DEFAULT_RETRIES if args.retries is None else args.retries,
        "sandbox": sandbox,
        "stream": stream,
        "base": base,
        "context_limit": (args.context_limit or defaults.get("context_limit")
                          or DEFAULT_CONTEXT_LIMIT),
    }

    if args.dry_run:
        emit({
            "dry_run": True, "project": str(project), "base": base, "config": cfg,
            "would_dispatch": [
                {"id": t["id"],
                 "agent": t.get("agent") or cfg["agent"],
                 "branch": f"{BRANCH_PREFIX}{t['id']}",
                 "worktree": str(worktree_path(project, t["id"])),
                 "files": t.get("files") or [],
                 "prompt_preview": t["prompt"].strip().splitlines()[0][:100]}
                for t in tasks
            ],
        })
        return EX_OK

    ensure_excluded(project)
    say(f"dispatching {len(tasks)} task(s), {parallel} at a time, model={model}, "
        f"sandbox={'on' if sandbox else 'OFF'}, stream={'on' if stream else 'off'}")

    results: list[dict] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=parallel) as pool:
        futures = {pool.submit(run_one, project, t, cfg): t for t in tasks}
        for fut in concurrent.futures.as_completed(futures):
            t = futures[fut]
            try:
                res = fut.result()
            except Exception as exc:  # never lose the other tasks to one crash
                res = {"id": t["id"], "status": "failed", "error": f"dispatcher error: {exc}"}
            results.append(res)
            ctx = res.get("context") or {}
            pct = f", ctx {ctx['pct']}%" if ctx.get("pct") is not None else ""
            say(f"  [{res['status']}] {res['id']} ({res.get('elapsed_sec', '?')}s{pct})")

    results.sort(key=lambda r: [t["id"] for t in tasks].index(r["id"]))
    state = load_state(project)
    for res in results:
        state["tasks"][res["id"]] = res
    state["base"] = base
    state["model"] = model
    state["sandbox"] = sandbox
    save_state(project, state)

    counts: dict[str, int] = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1

    # Hoisted out of the per-task payloads: a task can pass its status check and
    # still have produced degraded work because it ran out of room, and nobody
    # reads 10 nested result objects looking for that.
    context_warnings = [
        {"id": r["id"], "peak_tokens": r["context"]["peak_tokens"],
         "pct": r["context"]["pct"], "warning": r["context"]["warning"]}
        for r in results
        if (r.get("context") or {}).get("warning")
    ]
    for w in context_warnings:
        say(f"  ! context {w['pct']}% on {w['id']} — review its diff especially closely")

    # Same reasoning as context_warnings, but this one is never merely advisory.
    contract_violations = [
        {"id": r["id"], "files": r["contract_violations"]}
        for r in results if r.get("contract_violations")
    ]
    for v in contract_violations:
        say(f"  ! {v['id']} edited its own contract ({', '.join(v['files'])}) — do not merge")

    emit({"project": str(project), "base": base, "model": model,
          "counts": counts, "context_limit": cfg["context_limit"],
          "context_warnings": context_warnings,
          "contract_violations": contract_violations, "results": results})

    bad = [r for r in results if r["status"] not in ("done", "no-changes")]
    return EX_FAIL if bad else EX_OK


# --------------------------------------------------------------------------
# inspect / integrate / clean
# --------------------------------------------------------------------------

def cmd_status(args: argparse.Namespace) -> int:
    project = resolve_project(args.project)
    state = load_state(project)
    emit({"project": str(project), "base": state.get("base"),
          "model": state.get("model"), "tasks": state.get("tasks", {})})
    return EX_OK


def cmd_diff(args: argparse.Namespace) -> int:
    project = resolve_project(args.project)
    state = load_state(project)
    tasks = state.get("tasks", {})
    ids = [args.task] if args.task else list(tasks)
    if args.task and args.task not in tasks:
        die(f"Error: no dispatched task {args.task!r}. Known: {', '.join(tasks) or '(none)'}")

    out = []
    for tid in ids:
        rec = tasks[tid]
        branch = rec.get("branch")
        if not branch or not rec.get("committed"):
            out.append({"id": tid, "status": rec.get("status"), "diff": None,
                        "note": "nothing committed"})
            continue
        base = state.get("base", "HEAD")
        d = git(["diff", f"{base}...{branch}"], cwd=project).stdout
        truncated = len(d.splitlines()) > args.diff_lines
        if truncated:
            d = "\n".join(d.splitlines()[: args.diff_lines])
        out.append({"id": tid, "status": rec.get("status"), "branch": branch,
                    "files": rec.get("files", []), "truncated": truncated, "diff": d})
    emit({"project": str(project), "diffs": out})
    return EX_OK


def cmd_merge(args: argparse.Namespace) -> int:
    project = resolve_project(args.project)
    state = load_state(project)
    tasks = state.get("tasks", {})
    ids = list(tasks) if args.all else ([args.task] if args.task else [])
    if not ids:
        die("Error: pass --task ID or --all.")
    for tid in ids:
        if tid not in tasks:
            die(f"Error: no dispatched task {tid!r}. Known: {', '.join(tasks) or '(none)'}")

    dirty = git(["status", "--porcelain"], cwd=project).stdout.strip()
    if dirty:
        die(
            "Error: the project tree has uncommitted changes; a merge would mix them in.\n"
            "       Commit or set them aside first, then re-run merge.",
            EX_PREFLIGHT,
        )

    merged, skipped, conflicted = [], [], []
    for tid in ids:
        rec = tasks[tid]
        if not rec.get("committed"):
            skipped.append({"id": tid, "reason": rec.get("status", "nothing committed")})
            continue
        branch = rec["branch"]
        if args.dry_run:
            merged.append({"id": tid, "branch": branch, "dry_run": True})
            continue
        proc = git(["merge", "--no-ff", "-m", f"merge opencode agent {tid}", branch], cwd=project)
        if proc.returncode != 0:
            git(["merge", "--abort"], cwd=project)
            conflicted.append({"id": tid, "branch": branch,
                               "error": (proc.stdout + proc.stderr).strip()[:600]})
            break  # stop at the first conflict; leave the tree clean
        merged.append({"id": tid, "branch": branch,
                       "commit": git(["rev-parse", "HEAD"], cwd=project).stdout.strip()})
        state["tasks"][tid]["merged"] = True

    if not args.dry_run:
        save_state(project, state)
    emit({"project": str(project), "merged": merged, "skipped": skipped,
          "conflicted": conflicted, "dry_run": bool(args.dry_run)})
    return EX_FAIL if conflicted else EX_OK


def cmd_cleanup(args: argparse.Namespace) -> int:
    project = resolve_project(args.project)
    state = load_state(project)
    tasks = state.get("tasks", {})
    ids = list(tasks) if args.all else ([args.task] if args.task else [])
    if not ids:
        die("Error: pass --task ID or --all.")

    removed, kept = [], []
    for tid in ids:
        rec = tasks.get(tid) or {}
        wt = Path(rec.get("worktree") or worktree_path(project, tid))
        branch = rec.get("branch") or f"{BRANCH_PREFIX}{tid}"
        if not args.force and rec.get("committed") and not rec.get("merged"):
            kept.append({"id": tid, "branch": branch,
                         "reason": "has commits that were never merged; pass --force to discard"})
            continue
        if args.dry_run:
            removed.append({"id": tid, "branch": branch, "dry_run": True})
            continue
        git(["worktree", "remove", "--force", str(wt)], cwd=project)
        git(["worktree", "prune"], cwd=project)
        git(["branch", "-D", branch], cwd=project)
        shutil.rmtree(sandbox_home(project, tid), ignore_errors=True)
        state["tasks"].pop(tid, None)
        removed.append({"id": tid, "branch": branch})

    if not args.dry_run:
        save_state(project, state)
    emit({"project": str(project), "removed": removed, "kept": kept,
          "dry_run": bool(args.dry_run)})
    return EX_OK


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

EPILOG = """\
Task file (JSON) — an array, or an object with defaults plus "tasks":

  {
    "model": "ham51-2/qwen/qwen3.5-9b",
    "agent": "builder",
    "tasks": [
      {"id": "parser", "prompt": "Implement src/parser.py ... Do not touch other files.",
       "files": ["src/model.py"]},
      {"id": "cli",    "prompt": "Implement src/cli.py ...", "agent": "reviewer"}
    ]
  }

"files" attaches each path to the prompt, so the agent starts with the content
instead of spending tool calls hunting for it — and cannot re-read it. Paths are
relative to the project root and must be committed, since the agent works in a
worktree checked out from HEAD.

Typical run:
  opencode_agents.py check --project .
  opencode_agents.py dispatch --tasks tasks.json --dry-run
  opencode_agents.py dispatch --tasks tasks.json --sandbox
  opencode_agents.py diff --task parser
  opencode_agents.py merge --all
  opencode_agents.py cleanup --all

Exit codes: 0 ok | 1 a task failed or a merge conflicted | 2 bad usage
            3 environment unusable (no opencode, bad model, dirty tree)
"""


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="opencode_agents.py",
        description="Dispatch opencode agents into isolated git worktrees and collect their work.",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--project", help="target repository (default: current directory)")
    sub = p.add_subparsers(dest="command", required=True)

    c = sub.add_parser("check", help="verify opencode, model, and agent definitions")
    c.add_argument("--model", help="model to validate instead of the config default")
    c.set_defaults(func=cmd_check)

    tk = sub.add_parser("tokens", help="token usage from opencode's session ledger")
    tk.add_argument("--since", type=int, metavar="DAYS",
                    help="only sessions started in the last N days (default: all)")
    tk.add_argument("--here", action="store_true",
                    help="only sessions whose directory is under the target project")
    tk.add_argument("--agents-only", action="store_true",
                    help="drop interactive sessions; keep only herdr/opencode agent worktrees")
    tk.add_argument("--summary", action="store_true", help="omit the per-session detail")
    tk.add_argument("--limit", type=int, default=50,
                    help="max sessions in the detail list (default 50)")
    tk.set_defaults(func=cmd_tokens)

    a = sub.add_parser("agents", help="list agent definitions opencode will see")
    a.set_defaults(func=cmd_agents)

    d = sub.add_parser("dispatch", help="run tasks as opencode agents, one worktree each")
    d.add_argument("--tasks", required=True, help="path to the JSON task file")
    d.add_argument("--model", help="provider/model, e.g. ham51-2/qwen/qwen3.5-9b")
    d.add_argument("--agent", help="opencode agent for tasks that name none")
    d.add_argument("--parallel", type=int, default=DEFAULT_PARALLEL,
                   help=f"concurrent agents (default {DEFAULT_PARALLEL}; raising it "
                        "contends for one local model and is rarely faster)")
    d.add_argument("--timeout", type=int, help=f"per-task seconds (default {DEFAULT_TIMEOUT})")
    d.add_argument("--retries", type=int, default=None,
                   help=f"retries for provider errors that produced no tokens "
                        f"(default {DEFAULT_RETRIES})")
    d.add_argument("--stream", dest="stream", action="store_true", default=None,
                   help="print each agent's tool calls and replies as they happen "
                        "(default: on at --parallel 1, off above that)")
    d.add_argument("--no-stream", dest="stream", action="store_false",
                   help="silence live progress; the per-task log is still written live")
    d.add_argument("--sandbox", action="store_true",
                   help="confine each agent with bubblewrap so the ONLY writable paths "
                        "are its worktree and its own state; everything else, including "
                        "the project's .git, is read-only (Linux + bwrap)")
    d.add_argument("--context-limit", type=int, default=None,
                   help=f"token budget each task is measured against "
                        f"(default {DEFAULT_CONTEXT_LIMIT:,}); tasks peaking above "
                        f"{int(CONTEXT_WARN_FRACTION * 100)}%% of it are flagged")
    d.add_argument("--base", help="commit-ish to branch each worktree from (default HEAD)")
    d.add_argument("--dry-run", action="store_true", help="show the plan, run nothing")
    d.set_defaults(func=cmd_dispatch)

    s = sub.add_parser("status", help="show recorded results")
    s.set_defaults(func=cmd_status)

    f = sub.add_parser("diff", help="show what agents changed, per task")
    f.add_argument("--task", help="one task id (default: all)")
    f.add_argument("--diff-lines", type=int, default=200, help="cap per task (default 200)")
    f.set_defaults(func=cmd_diff)

    m = sub.add_parser("merge", help="merge agent branches into the current branch")
    m.add_argument("--task", help="one task id")
    m.add_argument("--all", action="store_true", help="every task with commits")
    m.add_argument("--dry-run", action="store_true")
    m.set_defaults(func=cmd_merge)

    k = sub.add_parser("cleanup", help="remove agent worktrees and branches")
    k.add_argument("--task", help="one task id")
    k.add_argument("--all", action="store_true")
    k.add_argument("--force", action="store_true", help="discard unmerged agent commits")
    k.add_argument("--dry-run", action="store_true")
    k.set_defaults(func=cmd_cleanup)
    return p


def main() -> int:
    args = build_parser().parse_args()
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return EX_FAIL


if __name__ == "__main__":
    sys.exit(main())
