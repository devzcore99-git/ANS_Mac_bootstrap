#!/usr/bin/env python3
"""Task-state tracker for the build-loop skill.

Holds the plan for one build run so a run survives the session that started it:
task list, dependency order, per-task attempt counts, and the verification
command. Python 3.7+, standard library only.

The script does no thinking. It stores the plan the model authored, answers
"what is runnable right now", and enforces the attempt cap so a failing task
stops the loop instead of grinding.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date

STATE_DIR = ".buildloop"
STATE_FILE = "state.json"
STATE_VERSION = 1

VALID_STATUS = ("pending", "in_progress", "done", "blocked")

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2
EXIT_EXISTS = 3
EXIT_CAP = 4
EXIT_NONE_READY = 5


# --------------------------------------------------------------------------
# state io


def state_path(project: str) -> str:
    return os.path.join(project, STATE_DIR, STATE_FILE)


def die(msg: str, code: int = EXIT_ERROR):
    print(msg, file=sys.stderr)
    sys.exit(code)


def load(project: str) -> dict:
    path = state_path(project)
    if not os.path.exists(path):
        die(
            "Error: no build-loop state at {}\n"
            "       Run `init` first, or pass --project PATH pointing at the "
            "project you are building.".format(path)
        )
    with open(path, encoding="utf-8") as fh:
        try:
            return json.load(fh)
        except json.JSONDecodeError as exc:
            die("Error: state file is not valid JSON: {}\n       {}".format(path, exc))


def save(project: str, state: dict) -> None:
    path = state_path(project)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2)
        fh.write("\n")
    os.replace(tmp, path)


def emit(payload) -> None:
    json.dump(payload, sys.stdout, indent=2)
    sys.stdout.write("\n")


def find_task(state: dict, task_id: str) -> dict:
    for task in state["tasks"]:
        if task["id"] == task_id:
            return task
    known = ", ".join(t["id"] for t in state["tasks"]) or "(none)"
    die("Error: no task with id {!r}.\n       Known ids: {}".format(task_id, known))


# --------------------------------------------------------------------------
# scheduling


def normalize(path: str) -> str:
    return os.path.normpath(path).replace("\\", "/").lstrip("./")


def conflicts(a_files, b_files) -> bool:
    """True when two tasks touch overlapping paths and must not run in parallel.

    A task with no declared files conflicts with everything. An empty list means
    "unknown", not "touches nothing" — treating it as disjoint is what lets an
    unscoped task into a batch that `next` promises is safe to dispatch in
    parallel, and two agents then write the same file.
    """
    if not a_files or not b_files:
        return True
    for a in (normalize(p) for p in a_files):
        for b in (normalize(p) for p in b_files):
            if a == b or a.startswith(b + "/") or b.startswith(a + "/"):
                return True
    return False


def ready_tasks(state: dict) -> list:
    done = {t["id"] for t in state["tasks"] if t["status"] == "done"}
    out = []
    for task in state["tasks"]:
        if task["status"] not in ("pending", "in_progress"):
            continue
        if all(dep in done for dep in task.get("depends_on", [])):
            out.append(task)
    return out


def parallel_batch(tasks: list) -> list:
    """Greedy first batch of ready tasks with no file overlap between them."""
    batch = []
    for task in tasks:
        if not any(conflicts(task.get("files", []), other.get("files", [])) for other in batch):
            batch.append(task)
    return batch


def blocked_by(state: dict, task: dict) -> list:
    lookup = {t["id"]: t for t in state["tasks"]}
    return [
        dep
        for dep in task.get("depends_on", [])
        if dep in lookup and lookup[dep]["status"] != "done"
    ]


def counts(state: dict) -> dict:
    tally = {s: 0 for s in VALID_STATUS}
    for task in state["tasks"]:
        tally[task["status"]] = tally.get(task["status"], 0) + 1
    tally["total"] = len(state["tasks"])
    return tally


# --------------------------------------------------------------------------
# commands


def cmd_init(args) -> int:
    project = os.path.abspath(os.path.expanduser(args.project))
    if not os.path.isdir(project):
        die("Error: --project is not a directory: {}".format(project))
    # `.git` is a directory in a normal checkout but a *file* in a linked
    # worktree, where it holds a gitdir: pointer. The workspace convention is
    # to work in a worktree, so an isdir() test fails in the ordinary case.
    if not os.path.exists(os.path.join(project, ".git")):
        die(
            "Error: {} is not a git repository.\n"
            "       build-loop assumes an existing scaffolded project. Run "
            "/project-bootstrap first.".format(project)
        )

    path = state_path(project)
    if os.path.exists(path) and not args.force:
        die(
            "Error: build-loop state already exists at {}\n"
            "       Run `status` to see it, or pass --force to discard it and "
            "replan from scratch.".format(path),
            EXIT_EXISTS,
        )

    try:
        with open(os.path.expanduser(args.tasks), encoding="utf-8") as fh:
            raw = json.load(fh)
    except FileNotFoundError:
        return die("Error: --tasks file not found: {}".format(args.tasks))
    except json.JSONDecodeError as exc:
        return die("Error: --tasks file is not valid JSON: {}".format(exc))

    if isinstance(raw, dict) and "tasks" in raw:
        raw = raw["tasks"]
    if not isinstance(raw, list) or not raw:
        die("Error: --tasks must be a non-empty JSON array of task objects.")

    tasks, seen = [], set()
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            die("Error: task at index {} is not an object.".format(i))
        for field in ("id", "title", "acceptance"):
            if not item.get(field):
                die(
                    "Error: task at index {} is missing required field {!r}.\n"
                    "       Required: id, title, acceptance. Optional: files, "
                    "depends_on, requirement.".format(i, field)
                )
        if item["id"] in seen:
            die("Error: duplicate task id {!r}.".format(item["id"]))
        seen.add(item["id"])
        tasks.append(
            {
                "id": item["id"],
                "title": item["title"],
                "requirement": item.get("requirement", ""),
                "files": item.get("files", []),
                "depends_on": item.get("depends_on", []),
                "acceptance": item["acceptance"],
                "status": "pending",
                "attempts": 0,
                "last_failure": None,
                "commit": None,
            }
        )

    for task in tasks:
        for dep in task["depends_on"]:
            if dep not in seen:
                die(
                    "Error: task {!r} depends on {!r}, which is not in the task "
                    "list.".format(task["id"], dep)
                )

    state = {
        "version": STATE_VERSION,
        "project": project,
        "spec": os.path.abspath(os.path.expanduser(args.spec)) if args.spec else None,
        "test_command": args.test_command,
        "max_attempts": args.max_attempts,
        "created": date.today().isoformat(),
        "tasks": tasks,
    }
    save(project, state)
    exclude_state_dir(project)

    emit(
        {
            "ok": True,
            "state_file": state_path(project),
            "project": project,
            "test_command": args.test_command,
            "max_attempts": args.max_attempts,
            "task_count": len(tasks),
        }
    )
    return EXIT_OK


def exclude_state_dir(project: str) -> None:
    """Keep .buildloop/ out of git without touching the tracked .gitignore."""
    exclude = os.path.join(project, ".git", "info", "exclude")
    line = STATE_DIR + "/"
    try:
        os.makedirs(os.path.dirname(exclude), exist_ok=True)
        existing = ""
        if os.path.exists(exclude):
            with open(exclude, encoding="utf-8") as fh:
                existing = fh.read()
        if line not in existing.split():
            with open(exclude, "a", encoding="utf-8") as fh:
                if existing and not existing.endswith("\n"):
                    fh.write("\n")
                fh.write(line + "\n")
    except OSError as exc:
        print("Warning: could not update .git/info/exclude: {}".format(exc), file=sys.stderr)


def cmd_status(args) -> int:
    state = load(os.path.abspath(os.path.expanduser(args.project)))
    ready = ready_tasks(state)
    ready_ids = {t["id"] for t in ready}
    rows = []
    for task in state["tasks"]:
        rows.append(
            {
                "id": task["id"],
                "title": task["title"],
                "status": task["status"],
                "attempts": task["attempts"],
                "ready": task["id"] in ready_ids,
                "waiting_on": blocked_by(state, task),
                "commit": task["commit"],
                "last_failure": task["last_failure"],
            }
        )
    emit(
        {
            "project": state["project"],
            "spec": state["spec"],
            "test_command": state["test_command"],
            "max_attempts": state["max_attempts"],
            "counts": counts(state),
            "complete": all(t["status"] == "done" for t in state["tasks"]),
            "tasks": rows,
        }
    )
    return EXIT_OK


def cmd_next(args) -> int:
    project = os.path.abspath(os.path.expanduser(args.project))
    state = load(project)
    ready = ready_tasks(state)
    if not ready:
        tally = counts(state)
        emit(
            {
                "ready": [],
                "counts": tally,
                "complete": tally["done"] == tally["total"],
                "reason": (
                    "all tasks done"
                    if tally["done"] == tally["total"]
                    else "remaining tasks are blocked or waiting on unfinished dependencies"
                ),
            }
        )
        return EXIT_NONE_READY

    batch = parallel_batch(ready) if not args.serial else ready[:1]
    emit(
        {
            "test_command": state["test_command"],
            "max_attempts": state["max_attempts"],
            "spec": state["spec"],
            "counts": counts(state),
            "batch": [
                {
                    "id": t["id"],
                    "title": t["title"],
                    "requirement": t["requirement"],
                    "files": t["files"],
                    "acceptance": t["acceptance"],
                    "attempts": t["attempts"],
                    "last_failure": t["last_failure"],
                }
                for t in batch
            ],
            "deferred": [t["id"] for t in ready if t not in batch],
        }
    )
    return EXIT_OK


def cmd_start(args) -> int:
    project = os.path.abspath(os.path.expanduser(args.project))
    state = load(project)
    task = find_task(state, args.id)
    waiting = blocked_by(state, task)
    if waiting:
        die(
            "Error: task {!r} depends on unfinished tasks: {}\n"
            "       Finish those first, or run `next` to see what is runnable.".format(
                task["id"], ", ".join(waiting)
            )
        )
    task["status"] = "in_progress"
    save(project, state)
    emit({"ok": True, "id": task["id"], "status": task["status"], "attempts": task["attempts"]})
    return EXIT_OK


def cmd_pass(args) -> int:
    project = os.path.abspath(os.path.expanduser(args.project))
    state = load(project)
    task = find_task(state, args.id)
    task["status"] = "done"
    task["last_failure"] = None
    if args.commit:
        task["commit"] = args.commit
    save(project, state)
    tally = counts(state)
    emit(
        {
            "ok": True,
            "id": task["id"],
            "status": "done",
            "counts": tally,
            "complete": tally["done"] == tally["total"],
        }
    )
    return EXIT_OK


def cmd_fail(args) -> int:
    project = os.path.abspath(os.path.expanduser(args.project))
    state = load(project)
    task = find_task(state, args.id)
    task["attempts"] += 1
    task["last_failure"] = args.reason
    remaining = state["max_attempts"] - task["attempts"]
    capped = remaining <= 0
    if capped:
        task["status"] = "blocked"
    save(project, state)
    emit(
        {
            "ok": True,
            "id": task["id"],
            "attempts": task["attempts"],
            "max_attempts": state["max_attempts"],
            "attempts_remaining": max(remaining, 0),
            "status": task["status"],
            "cap_reached": capped,
            "action": (
                "STOP. Report the failure to the user and ask how to proceed. Do not "
                "retry this task."
                if capped
                else "Dispatch a fix agent with the full failure output."
            ),
        }
    )
    return EXIT_CAP if capped else EXIT_OK


def cmd_block(args) -> int:
    project = os.path.abspath(os.path.expanduser(args.project))
    state = load(project)
    task = find_task(state, args.id)
    task["status"] = "blocked"
    task["last_failure"] = args.reason
    save(project, state)
    emit({"ok": True, "id": task["id"], "status": "blocked", "reason": args.reason})
    return EXIT_OK


def cmd_report(args) -> int:
    state = load(os.path.abspath(os.path.expanduser(args.project)))
    tally = counts(state)
    lines = [
        "# Build loop report",
        "",
        "- **Project**: `{}`".format(state["project"]),
        "- **Spec**: {}".format("`{}`".format(state["spec"]) if state["spec"] else "none"),
        "- **Test command**: `{}`".format(state["test_command"]),
        "- **Started**: {}".format(state["created"]),
        "",
        "| Task | Title | Status | Attempts | Commit |",
        "| --- | --- | --- | --- | --- |",
    ]
    for task in state["tasks"]:
        lines.append(
            "| {} | {} | {} | {} | {} |".format(
                task["id"],
                task["title"],
                task["status"],
                task["attempts"],
                (task["commit"] or "")[:8] or "—",
            )
        )
    lines += [
        "",
        "**{done}/{total} done**, {blocked} blocked, {pending} pending, "
        "{in_progress} in progress.".format(**tally),
    ]
    stuck = [t for t in state["tasks"] if t["status"] == "blocked"]
    if stuck:
        lines += ["", "## Blocked", ""]
        for task in stuck:
            lines.append("- **{}** {} — {}".format(task["id"], task["title"], task["last_failure"]))
    print("\n".join(lines))
    return EXIT_OK


# --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="buildloop.py",
        description="Track plan/build/test/fix state for one build-loop run.",
        epilog=(
            "Exit codes: 0 ok, 1 error, 2 usage, 3 state already exists, "
            "4 attempt cap reached (stop and ask the user), 5 nothing ready.\n\n"
            "Examples:\n"
            "  buildloop.py init --project ~/AI_Projects/CODE_Thing \\\n"
            "      --tasks plan.json --test-command 'pytest -q' --spec plans/thing-PRD.md\n"
            "  buildloop.py next    --project ~/AI_Projects/CODE_Thing\n"
            "  buildloop.py start   --project ~/AI_Projects/CODE_Thing --id T3\n"
            "  buildloop.py fail    --project ~/AI_Projects/CODE_Thing --id T3 \\\n"
            "      --reason 'test_parse_empty: IndexError in parse()'\n"
            "  buildloop.py pass    --project ~/AI_Projects/CODE_Thing --id T3 --commit abc1234\n"
            "  buildloop.py report  --project ~/AI_Projects/CODE_Thing\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def with_project(sp):
        sp.add_argument(
            "--project",
            default=".",
            help="project directory being built (default: current directory)",
        )
        return sp

    p = with_project(sub.add_parser("init", help="create state from a planned task list"))
    p.add_argument("--tasks", required=True, help="JSON file: array of task objects")
    p.add_argument("--test-command", required=True, help="command that verifies the build")
    p.add_argument("--spec", help="path to the PRD or spec driving this run")
    p.add_argument("--max-attempts", type=int, default=5, help="fix attempts per task (default: 5)")
    p.add_argument("--force", action="store_true", help="discard existing state and replan")
    p.set_defaults(func=cmd_init)

    p = with_project(sub.add_parser("status", help="full task table as JSON"))
    p.set_defaults(func=cmd_status)

    p = with_project(sub.add_parser("next", help="tasks runnable now, grouped for parallelism"))
    p.add_argument("--serial", action="store_true", help="return one task instead of a batch")
    p.set_defaults(func=cmd_next)

    p = with_project(sub.add_parser("start", help="mark a task in progress"))
    p.add_argument("--id", required=True)
    p.set_defaults(func=cmd_start)

    p = with_project(sub.add_parser("pass", help="mark a task done"))
    p.add_argument("--id", required=True)
    p.add_argument("--commit", help="commit sha the task landed in")
    p.set_defaults(func=cmd_pass)

    p = with_project(sub.add_parser("fail", help="record a failed attempt; exits 4 at the cap"))
    p.add_argument("--id", required=True)
    p.add_argument("--reason", required=True, help="the actual failure, not a summary")
    p.set_defaults(func=cmd_fail)

    p = with_project(sub.add_parser("block", help="mark a task blocked and stop working it"))
    p.add_argument("--id", required=True)
    p.add_argument("--reason", required=True)
    p.set_defaults(func=cmd_block)

    p = with_project(sub.add_parser("report", help="markdown summary for the user"))
    p.set_defaults(func=cmd_report)

    return parser


def main() -> int:
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
