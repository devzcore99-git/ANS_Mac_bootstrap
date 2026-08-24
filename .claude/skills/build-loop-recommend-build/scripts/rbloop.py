#!/usr/bin/env python3
"""Outer-loop state for /build-loop-recommend-build.

/build-loop drives one project from a spec to passing tests. This script drives
the loop *around* that loop: build once, then review the result with
/projects-recommendations and /projects-features-suggest and build what they
found, for a capped number of rounds.

Two things here are worth more than the bookkeeping:

  draft    turns the two review reports into a build-loop task plan. That
           conversion is otherwise done by hand, item by item, and the hand
           version is where declined ideas and dependency-hungry features
           quietly get built.

  advance  owns the phase machine, so "the initial build must pass before the
           review rounds start" is a rule the state file enforces rather than
           a sentence in a document. It refuses to leave the initial build on a
           red suite, and refuses to start round N+1 past the cap.

State lives in .buildloop/rounds.json, beside build-loop's own state.json.
Sharing that directory is deliberate: `buildloop.py init` already excludes
.buildloop/ from git, and `--force` rewrites only state.json, so a per-round
replan cannot take the round history with it.

Usage:
  python3 rbloop.py start   --project DIR [--rounds N] [--force]
  python3 rbloop.py status  --project DIR
  python3 rbloop.py draft   --project DIR [--out FILE] [--include-low]
                            [--max N] [--allow-deps]
  python3 rbloop.py advance --project DIR --result passed|failed
                            [--converged] [--note TEXT] [--counts JSON]
  python3 rbloop.py report  --project DIR
  python  rbloop.py ...     # Windows

Exit codes: 0 ok, 1 error, 2 usage, 3 state already exists,
            4 the phase refuses to advance (stop and ask the user),
            5 nothing left to build (converged or capped).
"""

import argparse
import importlib.util
import json
import os
import sys
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
SKILLS_DIR = os.path.dirname(os.path.dirname(SCRIPT_DIR))
sys.path.insert(0, os.path.join(SKILLS_DIR, "_lib"))
from projectscan import read_report  # noqa: E402

STATE_DIR = ".buildloop"
STATE_FILE = "rounds.json"

DEFAULT_ROUNDS = 3
# Past this the loop is not converging, it is grinding. Each round costs two
# review subagents plus one build subagent per task.
MAX_ROUNDS = 10
DEFAULT_MAX_TASKS = 12

PHASES = ("initial-build", "review", "integrate", "complete")


def die(message, code=1):
    print(json.dumps({"error": message}))
    sys.exit(code)


def load_sibling(skill, filename, name):
    """Import a sibling skill's script for its SPEC.

    The report format is that skill's to define, so its own ReportSpec is the
    only correct parser configuration. Copying the field list here would be a
    second definition that silently rots the day a field is added.
    """
    path = os.path.join(SKILLS_DIR, skill, filename)
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or not os.path.exists(path):
        die("%s not found at %s. This skill needs its sibling skills and _lib "
            "installed beside it." % (filename, path))
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:                                  # noqa: BLE001
        die("could not load %s: %s" % (path, exc))
    return module


def state_path(project):
    return os.path.join(project, STATE_DIR, STATE_FILE)


def read_state(project):
    try:
        with open(state_path(project), encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        die("No run in %s. Start one with `start --project %s`."
            % (os.path.join(project, STATE_DIR, STATE_FILE), project))
    except (OSError, ValueError) as exc:
        die("%s could not be read: %s" % (state_path(project), exc))


def write_state(project, state):
    path = state_path(project)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=1)
    except OSError as exc:
        die("could not write %s: %s" % (path, exc))


def now():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def cmd_start(args):
    project = os.path.abspath(os.path.expanduser(args.project))
    if not os.path.isdir(project):
        die("Not a directory: %s" % project)
    if not os.path.exists(os.path.join(project, ".git")):
        die("%s is not a git repository. Run /project-bootstrap first."
            % project)
    # Arguments before state, so a bad --rounds reports itself as a usage error
    # whether or not a run already exists. The other order made the same
    # command exit 2 or 3 depending on the directory it was pointed at.
    rounds = DEFAULT_ROUNDS if args.rounds is None else args.rounds
    if rounds < 0:
        die("--rounds cannot be negative.", code=2)
    if rounds > MAX_ROUNDS:
        die("--rounds %d exceeds the cap of %d. The loop stops improving long "
            "before that; raise MAX_ROUNDS deliberately if you really want it."
            % (rounds, MAX_ROUNDS), code=2)

    if os.path.exists(state_path(project)) and not args.force:
        die("A run already exists at %s. Use `status` to see it, or --force to "
            "discard it." % state_path(project), code=3)

    state = {
        "project": project,
        "started_at": now(),
        "rounds_requested": rounds,
        "round": 0,
        "phase": "initial-build",
        "converged": False,
        "history": [],
    }
    write_state(project, state)
    print(json.dumps({
        "started": True, "project": project, "rounds_requested": rounds,
        "phase": state["phase"],
        "next": "Run the initial build with /build-loop. The review rounds do "
                "not start until its full test suite passes.",
    }))


def cmd_status(args):
    project = os.path.abspath(os.path.expanduser(args.project))
    state = read_state(project)
    print(json.dumps(state))


# --- draft ---------------------------------------------------------------

def _where_paths(item, project):
    """Repo-relative paths out of an item's Where field.

    Where is prose written by a review agent: "`src/cli.py:88`",
    "`src/a.py` and `src/b.py`", sometimes a bare directory. Take what looks
    like a path and exists; a task with no files is still useful, a task with
    invented files sends a build agent to write a new file beside the real one.
    """
    raw = (item.get("where") or "").replace("`", " ")
    found = []
    for token in raw.replace(",", " ").split():
        token = token.strip("()[]<>'\"")
        if token.startswith("http"):
            continue
        token = token.split(":")[0]          # strip a :line suffix
        if "/" not in token and "." not in token:
            continue
        candidate = os.path.join(project, token)
        if os.path.exists(candidate) and token not in found:
            found.append(token)
    return found


def _task(index, source, item, project):
    title = item["title"]
    files = _where_paths(item, project)
    detail = " ".join(part for part in (item.get("why"), item.get("how"))
                      if part)
    return {
        "id": "R%d" % index,
        "title": title,
        "requirement": "%s [%s] %s" % (source, item["priority"], title),
        "files": files,
        "depends_on": [],
        "acceptance": item.get("how") or "",
        "_source": source,
        "_priority": item["priority"],
        "_raised": item.get("raised"),
        "_needs": item.get("needs") or "none",
        "_detail": detail,
    }


def cmd_draft(args):
    project = os.path.abspath(os.path.expanduser(args.project))
    state = read_state(project)
    if state["phase"] != "review":
        # Not merely out of order. A project may already carry reports from an
        # earlier, separate review run, and drafting from those during the
        # initial build would start improving code that is not green yet -
        # exactly what the gate exists to prevent.
        die("Phase is %r, not review. The initial build has to pass first, and "
            "each round drafts only after its own review has run."
            % state["phase"], code=4)

    recs = load_sibling("projects-recommendations", "recommendations.py", "recs")
    feats = load_sibling("projects-features-suggest", "features.py", "feats")

    wanted = {"High", "Medium"} | ({"Low"} if args.include_low else set())
    tasks, skipped = [], []
    index = 1

    for source, spec in (("recommendations.md", recs.SPEC),
                         ("features.md", feats.SPEC)):
        report = read_report(project, spec)
        if report is None:
            skipped.append({"source": source, "reason": "no report yet"})
            continue
        if report["meta"].get("generated-by") != spec.generated_by:
            # Someone else's file of the same name. Never build from it.
            skipped.append({"source": source, "reason": "foreign report"})
            continue
        for item in report["items"]:
            if item["done"]:
                # Already Completed, Built, or Declined. A declined idea
                # rebuilt is the exact failure the reports exist to prevent.
                continue
            if item["priority"] not in wanted:
                skipped.append({"source": source, "title": item["title"],
                                "reason": "priority %s" % item["priority"]})
                continue
            needs = (item.get("needs") or "none").strip().lower()
            if source == "features.md" and needs not in ("none", "", "-"):
                if not args.allow_deps:
                    # The workspace never installs a library without asking.
                    skipped.append({
                        "source": source, "title": item["title"],
                        "reason": "needs a new dependency: %s"
                                  % item.get("needs")})
                    continue
            tasks.append(_task(index, source, item, project))
            index += 1

    tasks.sort(key=lambda t: ({"High": 0, "Medium": 1, "Low": 2}
                              .get(t["_priority"], 3), t["id"]))
    capped = []
    if args.max and len(tasks) > args.max:
        capped = [t["title"] for t in tasks[args.max:]]
        tasks = tasks[:args.max]
    for position, task in enumerate(tasks, 1):
        task["id"] = "R%d" % position

    out = os.path.abspath(os.path.expanduser(args.out)) if args.out else \
        os.path.join(project, STATE_DIR, "round%d-plan.json" % state["round"])
    try:
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "w", encoding="utf-8") as fh:
            json.dump(tasks, fh, indent=1)
    except OSError as exc:
        die("could not write %s: %s" % (out, exc))

    weak = [t["id"] for t in tasks if not t["files"] or len(t["acceptance"]) < 15]
    print(json.dumps({
        "project": project, "round": state["round"], "plan": out,
        "tasks": len(tasks),
        "by_priority": {p: sum(1 for t in tasks if t["_priority"] == p)
                        for p in ("High", "Medium", "Low")},
        "needs_tightening": weak,
        "over_cap": capped,
        "skipped": skipped,
        "note": "DRAFT. Every acceptance line came from a report's How field "
                "and is prose, not a runnable check. For each task: rewrite "
                "the acceptance as something the test command proves, write "
                "the test yourself and commit it, name it in test_file, then "
                "pass this to `buildloop.py init`. The build agents run on the "
                "local model through /herdr-agents and may never write the "
                "test they are judged by. buildloop stores a known set of "
                "fields and drops the rest, so the underscore-prefixed keys "
                "here are for your triage only - they do not reach the state "
                "file, and test_file does.",
    }))
    if not tasks:
        sys.exit(5)


# --- advance -------------------------------------------------------------

def cmd_advance(args):
    project = os.path.abspath(os.path.expanduser(args.project))
    state = read_state(project)
    phase, rounds = state["phase"], state["rounds_requested"]

    if phase == "complete":
        die("This run is already complete. `report` shows what it did.",
            code=5)

    counts = {}
    if args.counts:
        try:
            counts = json.loads(args.counts)
        except ValueError as exc:
            die("--counts is not valid JSON: %s" % exc, code=2)

    entry = {"at": now(), "round": state["round"], "phase": phase,
             "result": args.result, "note": args.note or "", "counts": counts}

    if args.result == "failed":
        # Never advance on red. build-loop's own attempt cap has already been
        # spent by the time this is called with failed.
        state["history"].append(entry)
        write_state(project, state)
        print(json.dumps({
            "advanced": False, "phase": phase, "round": state["round"],
            "reason": "The %s phase did not pass. Report what failed and stop "
                      "— do not start the next phase on a red suite." % phase,
        }))
        sys.exit(4)

    if phase == "initial-build":
        state["history"].append(entry)
        if rounds == 0:
            state["phase"] = "complete"
            state["completed_at"] = now()
            write_state(project, state)
            print(json.dumps({
                "advanced": True, "phase": "complete", "round": 0,
                "reason": "Initial build passed and 0 review rounds were "
                          "requested."}))
            sys.exit(5)
        state["phase"] = "review"
        state["round"] = 1
        write_state(project, state)
        print(json.dumps({
            "advanced": True, "phase": "review", "round": 1,
            "rounds_requested": rounds,
            "next": "Run /projects-recommendations and "
                    "/projects-features-suggest against this project, then "
                    "`draft`."}))
        return

    if phase == "review":
        if args.converged:
            state["converged"] = True
            state["phase"] = "complete"
            state["completed_at"] = now()
            entry["result"] = "converged"
            state["history"].append(entry)
            write_state(project, state)
            print(json.dumps({
                "advanced": True, "phase": "complete", "round": state["round"],
                "reason": "The review found nothing actionable left. Stopping "
                          "at round %d of %d rather than manufacturing work."
                          % (state["round"], rounds)}))
            sys.exit(5)
        state["history"].append(entry)
        state["phase"] = "integrate"
        write_state(project, state)
        print(json.dumps({
            "advanced": True, "phase": "integrate", "round": state["round"],
            "next": "Run the build loop over the drafted plan. The suite must "
                    "pass before this round closes."}))
        return

    if phase == "integrate":
        state["history"].append(entry)
        if state["round"] >= rounds:
            state["phase"] = "complete"
            state["completed_at"] = now()
            write_state(project, state)
            print(json.dumps({
                "advanced": True, "phase": "complete", "round": state["round"],
                "reason": "Round %d of %d integrated and green. The cap is "
                          "reached." % (state["round"], rounds)}))
            sys.exit(5)
        state["round"] += 1
        state["phase"] = "review"
        write_state(project, state)
        print(json.dumps({
            "advanced": True, "phase": "review", "round": state["round"],
            "rounds_requested": rounds,
            "next": "Re-run both review skills. They carry the previous "
                    "round's items forward and move the fixed ones to "
                    "Completed / Built, which is what makes progress visible."}))
        return

    die("Unknown phase %r in %s" % (phase, state_path(project)))


# --- report --------------------------------------------------------------

def cmd_report(args):
    project = os.path.abspath(os.path.expanduser(args.project))
    state = read_state(project)
    name = os.path.basename(project)
    lines = [
        "## Build-and-improve run — %s" % name,
        "",
        "- Started: %s" % state["started_at"],
        "- Rounds requested: %d" % state["rounds_requested"],
        "- Phase: **%s** (round %d)" % (state["phase"], state["round"]),
    ]
    if state.get("converged"):
        lines.append("- Stopped early: the review found nothing actionable")
    if state.get("completed_at"):
        lines.append("- Completed: %s" % state["completed_at"])
    lines += ["", "| Round | Phase | Result | Detail |",
              "|-------|-------|--------|--------|"]
    for entry in state["history"]:
        counts = entry.get("counts") or {}
        detail = ", ".join("%s: %s" % (k, v) for k, v in counts.items())
        note = entry.get("note") or ""
        lines.append("| %s | %s | %s | %s |" % (
            entry["round"] or "—", entry["phase"], entry["result"],
            (detail + (" — " if detail and note else "") + note) or "—"))
    if not state["history"]:
        lines.append("| — | — | — | nothing recorded yet |")
    print("\n".join(lines))


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    subs = parser.add_subparsers(dest="command", required=True)

    start = subs.add_parser("start", help="create the outer-loop state")
    start.add_argument("--project", default=".")
    start.add_argument("--rounds", type=int,
                       help="review rounds after the initial build "
                            "(default: %d, cap: %d)"
                            % (DEFAULT_ROUNDS, MAX_ROUNDS))
    start.add_argument("--force", action="store_true",
                       help="discard an existing run")
    start.set_defaults(func=cmd_start)

    status = subs.add_parser("status", help="the run state as JSON")
    status.add_argument("--project", default=".")
    status.set_defaults(func=cmd_status)

    draft = subs.add_parser(
        "draft", help="turn the two review reports into a build-loop plan")
    draft.add_argument("--project", default=".")
    draft.add_argument("--out", help="where to write the plan (default: "
                                     ".buildloop/round<N>-plan.json)")
    draft.add_argument("--include-low", action="store_true",
                       help="also draft Low-priority items")
    draft.add_argument("--max", type=int, default=DEFAULT_MAX_TASKS,
                       help="most tasks to draft in one round (default: %d)"
                            % DEFAULT_MAX_TASKS)
    draft.add_argument("--allow-deps", action="store_true",
                       help="include feature ideas whose Needs is not none — "
                            "only after the user has approved the library")
    draft.set_defaults(func=cmd_draft)

    advance = subs.add_parser("advance", help="record a phase and move on")
    advance.add_argument("--project", default=".")
    advance.add_argument("--result", required=True,
                         choices=("passed", "failed"))
    advance.add_argument("--converged", action="store_true",
                         help="from review: nothing actionable was found, so "
                              "stop early")
    advance.add_argument("--note")
    advance.add_argument("--counts", help="JSON object of per-phase numbers, "
                                          "e.g. '{\"tasks\": 6}'")
    advance.set_defaults(func=cmd_advance)

    report = subs.add_parser("report", help="markdown summary across rounds")
    report.add_argument("--project", default=".")
    report.set_defaults(func=cmd_report)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
