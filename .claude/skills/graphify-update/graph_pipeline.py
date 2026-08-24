"""The graphify code-graph pipeline. Canonical implementation for the workspace.

It lives inside the /graphify-update skill rather than in ../_lib so that this
skill stands on its own: the three files in this directory are the whole thing,
importing only the standard library and reading no configuration they cannot do
without. _lib is bundled into every project too, so the import would resolve
either way — but a skill whose only dependency is Python is one fewer thing
that can be half-deployed, and a test asserts it stays that way.

/projects-recommendations and /projects-features-suggest borrow this module
through ../_lib/codegraph.py rather than holding a second copy, so all three
build graphs identically and a fix reaches every caller.

The pipeline is deterministic and offline:

    graphify extract <path> --code-only     first build: AST only, no API key
    graphify update <path>                  later builds: re-extract changed files
    graphify cluster-only <path> --no-label --no-viz
                                            GRAPH_REPORT.md, placeholder
                                            community names, no 5 MB graph.html

`--code-only` and `--no-label` are the load-bearing flags. Without them
graphify reaches for an LLM backend — semantic extraction over documents, and
community naming — which is exactly the cost this module exists to avoid. A
graph with `Community 7` for a name is still a map; a graph that bills an API
per project is not what a token-saving step should be doing.

graphify is optional. It is a per-machine install outside version control, so
it is absent in a fresh clone and inside a devcontainer, and every function
here degrades to a status the caller can report rather than an exception.
"""

import json
import os
import re
import shutil
import subprocess

SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
# Present when this skill sits in ASST_BBMax's own .claude/skills/; absent in
# the copy every other project carries, which is why every read of it tolerates
# the file not being there.
CONFIG_PATH = os.path.join(os.path.dirname(SCRIPT_DIR), "skills_config.json")

GRAPH_DIR = "graphify-out"
GRAPH_JSON = "graph.json"
GRAPH_REPORT = "GRAPH_REPORT.md"

# `- 637 nodes · 1310 edges · 33 communities (22 shown, 11 thin omitted)`
SUMMARY_RE = re.compile(
    r"^-\s*([\d,]+)\s*nodes\D+([\d,]+)\s*edges\D+([\d,]+)\s*communities")
# `- Built from commit: `2930c8b1``
COMMIT_RE = re.compile(r"^-\s*Built from commit:\s*`([0-9a-fA-F]+)`")

# Long enough for a first extraction of the largest repo in the workspace,
# short enough that one wedged build cannot hold a 30-project sweep open.
DEFAULT_TIMEOUT = 600


def _config_bin():
    """An explicit `graphify_bin` in skills_config.json, for a machine where
    the binary lives somewhere PATH does not reach. Absent in a project copy,
    which is not an error."""
    try:
        with open(CONFIG_PATH, encoding="utf-8") as fh:
            value = json.load(fh).get("graphify_bin")
    except (OSError, ValueError):
        return None
    if not value:
        return None
    value = os.path.expanduser(value)
    return value if os.path.exists(value) else None


def graphify_bin():
    """Path to the graphify executable, or None when it is not installed.

    Returns the bare name when PATH already resolves it, so the commands
    written into a brief stay readable — an agent runs them by hand.
    """
    if shutil.which("graphify"):
        return "graphify"
    configured = _config_bin()
    if configured:
        return configured
    fallback = os.path.expanduser("~/.local/bin/graphify")
    return fallback if os.path.exists(fallback) else None


def graph_paths(path):
    out = os.path.join(path, GRAPH_DIR)
    return os.path.join(out, GRAPH_JSON), os.path.join(out, GRAPH_REPORT)


def _run(cmd, timeout):
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, "timed out after %ds" % timeout
    except OSError as exc:
        return False, str(exc)
    out = (proc.stdout or b"").decode("utf-8", "replace").strip()
    if proc.returncode != 0:
        # The last few lines carry the actual failure; the rest is progress.
        tail = " / ".join(out.splitlines()[-3:])[:400]
        return False, tail or "exit %d" % proc.returncode
    return True, out


def info(path, head=None):
    """What the built graph looks like, or None when there is no graph.

    Read from GRAPH_REPORT.md rather than graph.json: the report is 8 KB where
    the graph is measured in megabytes, it carries the same header numbers, and
    it is the file the agent is being pointed at anyway.
    """
    graph_json, report = graph_paths(path)
    if not os.path.exists(graph_json):
        return None
    data = {"graph": graph_json, "report": None, "nodes": None, "edges": None,
            "communities": None, "built_commit": None, "stale": None}
    try:
        with open(report, encoding="utf-8") as fh:
            head_lines = [next(fh, "") for _ in range(40)]
    except OSError:
        return data
    data["report"] = report
    for line in head_lines:
        m = SUMMARY_RE.match(line)
        if m:
            data["nodes"] = int(m.group(1).replace(",", ""))
            data["edges"] = int(m.group(2).replace(",", ""))
            data["communities"] = int(m.group(3).replace(",", ""))
            continue
        m = COMMIT_RE.match(line)
        if m:
            data["built_commit"] = m.group(1)
    if head and data["built_commit"]:
        n = len(data["built_commit"])
        data["stale"] = head[:n] != data["built_commit"]
    return data


def build(path, force=False, timeout=DEFAULT_TIMEOUT):
    """Bring one project's graph up to date. Never raises.

    status is one of:
      built       first graph for this project
      updated     existing graph re-extracted against the current tree
      no-code     graphify found nothing it can parse — a prose-only repo
      unavailable graphify is not installed on this machine
      error       the build failed; `detail` says how
    """
    binp = graphify_bin()
    if not binp:
        return {"project": os.path.basename(path), "status": "unavailable",
                "detail": "graphify is not on PATH"}

    graph_json, _ = graph_paths(path)
    incremental = os.path.exists(graph_json) and not force

    if incremental:
        # Re-extracts only what changed, keeps whatever a richer (semantic)
        # build put in the graph, and regenerates GRAPH_REPORT.md itself.
        ok, out = _run([binp, "update", path], timeout)
        status = "updated"
    else:
        cmd = [binp, "extract", path, "--code-only"]
        if force:
            # Skips the incremental gate, so a refactor that deleted code
            # cannot leave stale symbols behind.
            cmd.append("--force")
        ok, out = _run(cmd, timeout)
        status = "built"

    result = {"project": os.path.basename(path), "status": status}
    if not ok:
        result["status"] = "error"
        result["detail"] = out
        return result

    # `update` regenerates GRAPH_REPORT.md itself, so the clustering pass below
    # is only for a fresh extract or a graph left behind by an older run that
    # never wrote a report.
    _, report_path = graph_paths(path)
    if not (incremental and os.path.exists(report_path)):
        if not os.path.exists(graph_json):
            # Nothing parseable in the repo. Not a failure — a KBX_ knowledge
            # base has no call graph to draw.
            result["status"] = "no-code"
            result["detail"] = "graphify found no code files to map"
            return result
        # extract stops at graph.json, and a graph built by an older run may
        # predate the report entirely. Generating it is a separate
        # deterministic pass: --no-label keeps the LLM out of it, --no-viz
        # skips the multi-megabyte graph.html nothing here reads.
        ok, out = _run([binp, "cluster-only", path, "--no-label", "--no-viz"],
                       timeout)
        if not ok:
            result["status"] = "error"
            result["detail"] = "clustering failed: %s" % out
            return result

    result.update({k: v for k, v in (info(path) or {}).items()
                   if k in ("nodes", "edges", "communities", "report")})
    return result


def _git(repo, *args):
    """One local git command. Returns (ok, stdout).

    Deliberately not ../_lib/gitutil.git_run: this module has to work in a
    project copy where _lib is not there. Only local plumbing is run here —
    rev-parse — so none of git_run's network and credential hardening applies.
    """
    try:
        proc = subprocess.run(("git", "-C", repo) + args,
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                              timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return False, ""
    out = (proc.stdout or b"").decode("utf-8", "replace").strip()
    return proc.returncode == 0, out


def repo_root(path):
    """(repository root holding path, True), or (path, False) outside a repo.

    graphify maps whatever directory it is pointed at. Pointed at a
    subdirectory it produces a graph of that subtree, silently — a map missing
    most of the project, in a graphify-out/ nobody thinks to look for.
    """
    ok, out = _git(path, "rev-parse", "--show-toplevel")
    if ok and out:
        return os.path.abspath(out), True
    return os.path.abspath(path), False


def head_commit(path):
    """The repo's current HEAD sha, or None outside a repo."""
    ok, out = _git(path, "rev-parse", "HEAD")
    return out if ok and out else None


def exclude_entries(path, entries, generated_by):
    """Add entries to one repo's .git/info/exclude, skipping any already there.

    That file is local and untracked, so an entry never shows up as a pending
    change the way editing .gitignore would, and /projects-git-status stays
    clean. Returns {"status", "added", "detail"}; status is excluded,
    already-excluded, or error. Never raises.
    """
    # .git is a file, not a directory, inside a worktree or submodule.
    ok, git_dir = _git(path, "rev-parse", "--absolute-git-dir")
    if not ok:
        return {"status": "error", "added": [],
                "detail": "could not resolve the git dir"}
    exclude = os.path.join(git_dir, "info", "exclude")
    try:
        os.makedirs(os.path.dirname(exclude), exist_ok=True)
        body = ""
        if os.path.exists(exclude):
            with open(exclude, encoding="utf-8") as fh:
                body = fh.read()
        present = {line.strip() for line in body.splitlines()}
        missing = [e for e in entries if e not in present]
        if not missing:
            return {"status": "already-excluded", "added": [],
                    "detail": exclude}
        prefix = "" if body.endswith("\n") or not body else "\n"
        with open(exclude, "a", encoding="utf-8") as fh:
            fh.write("%s\n# Written by the %s skill \u2014 advisory output, "
                     "not repo content.\n%s\n"
                     % (prefix, generated_by, "\n".join(missing)))
        return {"status": "excluded", "added": missing, "detail": exclude}
    except OSError as exc:
        return {"status": "error", "added": [], "detail": str(exc)}
