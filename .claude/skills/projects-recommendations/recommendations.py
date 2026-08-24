#!/usr/bin/env python3
"""Support script for the /projects-recommendations skill.

Subcommands emitting JSON on stdout, except where noted:

  scan    Discover repos, detect each one's tech stack, and report whether its
          recommendations.md is missing, stale, or current. Drives the project
          picker. --format table prints those rows ready to display instead.

  brief   Build each project's code graph, then write a complete, ready-to-use
          agent prompt per project into a directory, so dispatching N experts
          costs one line of prompt each rather than N copies of the same
          instructions.

  graph   Build or refresh the graphify code graph for the given projects
          without writing briefs. brief does this for you; this is the way to
          rebuild one by hand, or to force a full re-extract.

  view    Read the recommendations.md files that already exist and return them
          as structured data, so the report can be assembled without the model
          opening 30 files by hand.

  stamp   Backfill missing **Raised** dates into existing reports.

  ignore  Add recommendations.md and graphify-out/ to a repo's
          .git/info/exclude. That file is local and untracked, so the entries
          never show up as pending changes the way editing .gitignore would.

Repo discovery, stack detection, and report parsing live in
../_lib/projectscan.py, and the graphify code graph in ../_lib/codegraph.py,
both shared with /projects-features-suggest. What stays here
is what makes this skill a code review rather than a feature proposal: the
review personas, the agent brief, and the report shape.

Runs on Windows, macOS, and Linux. Requires Python 3.7+ and git on PATH;
nothing outside the standard library.

Usage:
  python3 recommendations.py scan [--root DIR] [--project NAME ...]
                                  [--format json|table]
  python3 recommendations.py brief [--root DIR] [--project NAME ...]
                                   [--out DIR] [--date YYYY-MM-DD]
                                   [--no-graph] [--force-graph]
  python3 recommendations.py graph [--root DIR] [--project NAME ...] [--force]
  python3 recommendations.py view [--root DIR] [--project NAME ...] [--full]
  python3 recommendations.py stamp [--root DIR] [--date YYYY-MM-DD] [--dry-run]
  python3 recommendations.py ignore --project NAME [--root DIR]
  python  recommendations.py ...    # Windows
"""

import argparse
import json
import os
import re
import sys
import tempfile
from collections import Counter
from datetime import datetime, timezone

# realpath, not abspath: when this skill is symlinked into ~/.claude/skills to
# make it available in every project, abspath stops at the symlink and the
# shared library is not there. realpath resolves back into the repo that holds
# it.
SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(SCRIPT_DIR), "_lib"))
import codegraph  # noqa: E402
from projectscan import (  # noqa: E402
    ITEM_RE, ReportSpec, die, exclude_report, load_root, print_scan_table,
    read_report, resolve_projects, scan_one, scope_of)

# Items under "Completed" are resolved history, not outstanding work. They are
# counted and reported separately everywhere.
SPEC = ReportSpec(
    report_name="recommendations.md",
    generated_by="/projects-recommendations",
    done_categories=("Completed",),
    fields=("Where", "Why", "How", "Effort", "Raised", "Completed",
            "Resolution"),
)

# How to frame the reviewing agent, keyed by primary stack. This lives here
# rather than in SKILL.md because it is a pure function of detect_stack's
# output: a table in prose has to be looked up once per project by the model,
# and the lookup can go wrong. LOC_BEARING_STACKS covers more languages than
# are worth naming individually — anything unlisted falls back to GENERIC_LANG.
PERSONAS = {
    "Python": "a senior Python engineer, judging typing, packaging, "
              "venv and dependency hygiene, exception handling, "
              "stdlib-over-dependency, and pytest structure",
    "JavaScript/TypeScript": "a senior TypeScript/JavaScript engineer, "
                             "judging type safety, async correctness, bundle "
                             "size, dependency risk, and framework idiom",
    "PowerShell": "a PowerShell automation expert, judging approved verbs, "
                  "[CmdletBinding()], pipeline semantics, "
                  "$ErrorActionPreference, and cross-version compatibility",
    "Shell": "a shell scripting expert, judging set -euo pipefail, quoting, "
             "portability between bash and zsh, POSIX traps, and idempotence",
    "Batch": "a Windows batch scripting expert, judging quoting, error "
             "propagation via ERRORLEVEL, delayed expansion, and idempotence",
    "Ansible": "an Ansible expert, judging idempotence, role structure, "
               "become scope, variable precedence, secret handling, and "
               "molecule tests",
    "Docker": "a container expert, judging layer caching, image size, "
              "non-root users, healthchecks, secret leakage, and compose "
              "structure",
    "Dev Container": "a dev container expert, judging base image choice, "
                     "feature and extension selection, rebuild cost, secret "
                     "leakage, and parity with how the project runs outside "
                     "the container",
    "Web": "a frontend engineer, judging semantic HTML, accessibility, CSS "
           "structure, asset weight, and responsive behavior",
    "SQL": "a database engineer, judging indexing, query plans, schema "
           "normalization, and injection exposure",
    "Jupyter": "a data science engineer, judging notebook reproducibility, "
               "hidden state, and extraction of reusable code into modules",
    "AmiBroker AFL": "an AmiBroker AFL expert, judging array-vs-loop "
                     "performance, lookahead bias, and correct backtest "
                     "settings",
    "Docs": "a technical writer and information architect, judging structure, "
            "staleness, contradictions, gaps, and navigability — this is a "
            "knowledge base, so review the content, not code that is not there",
    "Config": "a pragmatic reviewer — say plainly if there is little here to "
              "review rather than inventing findings",
}
PERSONAS["Data"] = PERSONAS["Config"]
PERSONAS["Unknown"] = PERSONAS["Config"]

GENERIC_LANG = ("a senior %s engineer, judging idiom, error handling, and "
                "dependency health by that language's own community norms")


def persona_for(stack):
    if stack in PERSONAS:
        return PERSONAS[stack]
    return GENERIC_LANG % stack



def cmd_scan(args):
    root = load_root(args.root)
    repos = resolve_projects(root, args.project)

    results = [scan_one(name, path, SPEC) for name, path in repos]
    counts = Counter(r["state"] for r in results)

    if args.format == "table":
        print_scan_table(results, counts)
        return

    print(json.dumps({
        "root": root,
        "scope": scope_of(root),
        "scanned_at": datetime.now(timezone.utc).astimezone().isoformat(
            timespec="seconds"),
        "totals": {
            "repos": len(results),
            "never": counts["never"],
            "stale": counts["stale"],
            "current": counts["current"],
            "foreign": counts["foreign"],
        },
        "projects": results,
    }, indent=None))


def cmd_view(args):
    root = load_root(args.root)
    repos = resolve_projects(root, args.project)

    found, absent, foreign = [], [], []
    for name, path in repos:
        report = read_report(path, SPEC)
        if report is None:
            absent.append(name)
            continue
        if report["meta"].get("generated-by") != SPEC.generated_by:
            # Not ours — surface that it exists, but never present its
            # contents as if this skill had produced them.
            foreign.append({"project": name, "path": report["path"]})
            continue
        open_items = [i for i in report["items"] if not i["done"]]
        done_items = [i for i in report["items"] if i["done"]]
        undated = [i["title"] for i in open_items if not i.get("raised")]
        entry = {
            "project": name,
            "path": report["path"],
            "stack": report["meta"].get("stack"),
            "analyzed_at": report["meta"].get("analyzed-at"),
            "analyzed_commit": (report["meta"].get("analyzed-commit") or "")[:8],
            "summary": report["summary"],
            "by_priority": dict(Counter(i["priority"] for i in open_items)),
            "by_category": dict(Counter(i["category"] for i in open_items)),
            "item_count": len(open_items),
            "completed_count": len(done_items),
            "raised_dates": sorted({i["raised"] for i in open_items
                                    if i.get("raised")}),
            "undated_items": undated,
            "items": open_items,
            "completed": done_items,
        }
        if args.full:
            entry["raw"] = report["raw"]
        found.append(entry)

    totals = Counter()
    for entry in found:
        totals.update(entry["by_priority"])
    print(json.dumps({
        "root": root,
        "totals": {
            "projects_with_report": len(found),
            "projects_without_report": len(absent),
            "foreign_reports": len(foreign),
            "items": sum(e["item_count"] for e in found),
            "completed_items": sum(e["completed_count"] for e in found),
            "undated_items": sum(len(e["undated_items"]) for e in found),
            "by_priority": dict(totals),
        },
        "without_report": absent,
        "foreign_reports": foreign,
        "projects": found,
    }, indent=None))


def stamp_text(text, date):
    """Insert `**Raised**: date` into every item block that lacks one.

    Reports written before per-item dates existed carry no provenance at all,
    which makes "raised vs fixed" unanswerable for everything already on file.
    The report's own analyzed-at is the honest date to backfill with: it is
    when the finding was actually made.
    """
    lines = text.splitlines()
    out, changed = [], 0
    i = 0
    while i < len(lines):
        out.append(lines[i])
        if not ITEM_RE.match(lines[i]):
            i += 1
            continue

        # Collect the block up to the next heading, so we can see whether it
        # already has a Raised line and where the field run ends.
        block_start = i + 1
        j = block_start
        while j < len(lines) and not (lines[j].startswith("## ")
                                      or lines[j].startswith("### ")
                                      or lines[j].startswith("---")):
            j += 1
        block = lines[block_start:j]

        if any(SPEC.field_re.match(b) and SPEC.field_re.match(b).group(1).lower() == "raised"
               for b in block):
            out.extend(block)
            i = j
            continue

        # Place it after the last field line so the fields stay contiguous;
        # fall back to the top of the block when there are no fields.
        last_field = -1
        for idx, b in enumerate(block):
            if SPEC.field_re.match(b):
                last_field = idx
        insert_at = last_field + 1 if last_field >= 0 else 0
        while insert_at < len(block) and not block[insert_at].strip():
            break
        block.insert(insert_at, "**Raised**: %s" % date)
        changed += 1
        out.extend(block)
        i = j
    return "\n".join(out) + ("\n" if text.endswith("\n") else ""), changed


def cmd_stamp(args):
    root = load_root(args.root)
    repos = resolve_projects(root, args.project)

    results = []
    for name, path in repos:
        report = read_report(path, SPEC)
        if report is None:
            continue
        if report["meta"].get("generated-by") != SPEC.generated_by:
            results.append({"project": name, "status": "skipped-foreign"})
            continue

        date = args.date or (report["meta"].get("analyzed-at") or "")[:10]
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", date or ""):
            results.append({"project": name, "status": "error",
                            "detail": "no usable date; pass --date YYYY-MM-DD"})
            continue

        new_text, changed = stamp_text(report["raw"], date)
        if not changed:
            results.append({"project": name, "status": "already-dated",
                            "items": len(report["items"])})
            continue
        if args.dry_run:
            results.append({"project": name, "status": "would-stamp",
                            "items": changed, "date": date})
            continue
        try:
            with open(report["path"], "w", encoding="utf-8") as fh:
                fh.write(new_text)
        except OSError as exc:
            results.append({"project": name, "status": "error",
                            "detail": str(exc)})
            continue
        results.append({"project": name, "status": "stamped",
                        "items": changed, "date": date})

    counts = Counter(r["status"] for r in results)
    print(json.dumps({
        "root": root,
        "dry_run": bool(args.dry_run),
        "totals": dict(counts),
        "items_stamped": sum(r.get("items", 0) for r in results
                             if r["status"] in ("stamped", "would-stamp")),
        "results": results,
    }))


SIGNAL_LABELS = [
    ("readme", "a README"),
    ("claude_md", "a CLAUDE.md"),
    ("tests", "a test suite"),
    ("ci", "a CI workflow"),
    ("lockfile", "a dependency lockfile"),
    ("license", "a LICENSE"),
]


def build_brief(rec, today, template_path, report, graph=None):
    """The full agent prompt for one project, as markdown.

    Everything invariant lives here rather than being retyped into each Agent
    call. On a 38-repo workspace that is the difference between the model
    generating ~800 tokens per project and ~30, and it removes the chance of
    the re-run protocol being paraphrased differently for each agent — which
    matters, because these reports are outside git and a dropped item is gone.
    """
    loc = " | ".join("%s: %s" % (s, "{:,}".format(n))
                     for s, n in rec["loc_by_stack"].items()) or "none counted"
    secondary = ", ".join(rec["stacks"][1:]) or "none"
    present = [label for key, label in SIGNAL_LABELS if rec["signals"].get(key)]
    absent = [label for key, label in SIGNAL_LABELS
              if not rec["signals"].get(key)]

    out = [
        "# Review brief — %s" % rec["project"],
        "",
        "You are %s." % rec["persona"],
        "",
        "Review the project at `%s` and write exactly one file: "
        "`%s`." % (rec["path"], os.path.join(rec["path"], SPEC.report_name)),
        "",
        "## What you are looking at",
        "",
        "- Primary stack: **%s**" % rec["primary_stack"],
        "- Also in scope: %s" % secondary,
        "- Size: %s files, %s lines (%s)" % (
            "{:,}".format(rec["file_count"]),
            "{:,}".format(rec["total_loc"]), loc),
        "- HEAD, for the `analyzed-commit` stamp: `%s`" % rec["head_full"],
        "- Timestamp, for the `analyzed-at` stamp: `%s`" % rec["scanned_at"],
        "- **Today's date is %s.** Use it for `**Raised**` on new findings "
        "and `**Completed**` on resolved ones. Do not infer the date from "
        "anything else — you have no reliable clock." % today,
        "",
        "## Signals from the scan",
        "",
    ]
    if absent:
        out += ["This project has none of: %s. Absence is itself a finding "
                "worth raising where it matters — judged against the "
                "project's size and purpose, not as a checklist."
                % ", ".join(absent), ""]
    if present:
        out += ["It does have: %s." % ", ".join(present), ""]

    out += [
        "## Before you read any source",
        "",
        "Read the project's own `README.md`, `CLAUDE.md`, and `TODOs.md` "
        "where they exist. Recommendations should answer what this project is "
        "trying to be, not a generic checklist.",
        "",
    ]

    out += codegraph.brief_section(rec["path"], graph, purpose="review")

    if report and report["items"]:
        open_items = [i for i in report["items"] if not i["done"]]
        out += [
            "## Re-run protocol — this project already has a report",
            "",
            "The existing `%s` is an input, not something to overwrite. Read "
            "it **before** any source, and treat every item in it as a claim "
            "to re-check against the current code." % SPEC.report_name,
            "",
            "For each prior open item, decide one of three things:",
            "",
            "- **Still open** — carry it forward into the same section with "
            "its `**Raised**` date **unchanged**. Update `Where`/`Why`/`How` "
            "if the code moved; it is the same finding and keeps its date.",
            "- **Resolved** — move it to `## Completed` with "
            "`**Completed**: %s`, the original `**Raised**` date, and a "
            "`**Resolution**` line naming what changed. Verify the fix in the "
            "code; a plausible-looking diff or commit message is not proof." % today,
            "- **No longer applicable** — also move it to `## Completed`, "
            "with a resolution that says so (\"module removed\", \"project "
            "changed direction\"). Never silently drop it.",
            "",
            "Anything already under `## Completed` stays there untouched, "
            "newest first. Only genuinely new findings get today's date.",
            "",
            "An item quietly disappearing is the one outcome this protocol "
            "exists to prevent. These reports are outside git, so the file is "
            "the only record there is — if a finding cannot be confirmed "
            "fixed, it stays open.",
            "",
            "The %d open item(s) you must account for:" % len(open_items),
            "",
        ]
        for item in open_items:
            # The parsed Where already carries its own backticks.
            where = item.get("where", "?").strip("`") or "?"
            out.append("- [%s] %s — `%s` (Raised: %s)" % (
                item["priority"], item["title"], where,
                item.get("raised", "undated")))
        out.append("")

    out += [
        "## Output format",
        "",
        "Follow `%s` exactly. Its structure is load-bearing — `scan` and "
        "`view` parse this file, so the metadata comments, the `## ` category "
        "headings, the `### [High] Title` item headings, and the `**Where**:` "
        "field lines must all match. Delete the template's own \"Format "
        "rules\" section from what you write." % template_path,
        "",
        "## Constraints",
        "",
        "- **Write only `%s` at the project root. Change no other file.** No "
        "fixes, no refactors, no `git` commands." % SPEC.report_name,
        "- Ground every item in a real path, and a line number where one "
        "applies. A finding you cannot point at does not go in. The code graph "
        "tells you where to look; the source is what you cite.",
        "- Prefer ten specific items over thirty generic ones. An empty "
        "category is deleted, not padded.",
        "- Judge the project against its own goals and size. A 400-line "
        "personal utility does not need CI, coverage gates, or a plugin "
        "architecture, and saying so is a legitimate finding.",
        "- Every item carries a `**Raised**` date.",
        "",
        "## What to return",
        "",
        "Two lines, as your final message — not the report itself:",
        "",
        "1. Item counts by priority, and (on a re-run) how many prior items "
        "you resolved versus carried forward.",
        "2. The single highest-value recommendation.",
        "",
    ]
    return "\n".join(out)


def cmd_ignore(args):
    root = load_root(args.root)
    # graphify-out/ rides along: the code graph is generated, large, and no
    # more repo content than the report it exists to make cheaper.
    print(json.dumps({
        "root": root,
        "results": exclude_report(root, args.project, SPEC,
                                  extra=("%s/" % codegraph.GRAPH_DIR,)),
    }))


def cmd_graph(args):
    root = load_root(args.root)
    repos = resolve_projects(root, args.project)
    if not codegraph.graphify_bin():
        # Not an error: graphify is a per-machine install outside version
        # control, so a devcontainer or a fresh clone simply does without.
        print(json.dumps({
            "root": root,
            "graphify": None,
            "totals": {"unavailable": len(repos)},
            "results": [{"project": name, "status": "unavailable"}
                        for name, _ in repos],
            "note": "graphify is not installed — reviews fall back to reading "
                    "source directly",
        }))
        return

    results = [codegraph.build(path, force=args.force, timeout=args.timeout)
               for _, path in repos]
    print(json.dumps({
        "root": root,
        "graphify": codegraph.graphify_bin(),
        "totals": dict(Counter(r["status"] for r in results)),
        "results": results,
    }))


def cmd_brief(args):
    root = load_root(args.root)
    repos = resolve_projects(root, args.project)

    out_dir = (os.path.abspath(os.path.expanduser(args.out)) if args.out
               else os.path.join(tempfile.gettempdir(), "bbmax-recommendations"))
    try:
        os.makedirs(out_dir, exist_ok=True)
    except OSError as exc:
        die("Could not create the brief directory %s: %s" % (out_dir, exc))

    today = args.date or datetime.now().strftime("%Y-%m-%d")
    template = os.path.join(SCRIPT_DIR, "TEMPLATE.md")
    scanned_at = datetime.now(timezone.utc).astimezone().isoformat(
        timespec="seconds")
    # Refreshing the graph here rather than in a step of its own is deliberate:
    # a brief that points an agent at a code graph must not be able to point it
    # at a stale one, and a separate step is a step that can be skipped.
    build_graphs = not args.no_graph and bool(codegraph.graphify_bin())

    results = []
    graph_states = Counter()
    for name, path in repos:
        rec = scan_one(name, path, SPEC)
        if rec["state"] == "foreign":
            # Never hand an agent a project whose report is somebody else's.
            results.append({"project": name, "status": "skipped-foreign",
                            "detail": rec["reason"]})
            continue

        graph_result = None
        if build_graphs:
            graph_result = codegraph.build(path, force=args.force_graph,
                                           timeout=args.graph_timeout)
            graph_states[graph_result["status"]] += 1
        graph = codegraph.info(path, head=rec["head_full"])
        if graph is None:
            graph_states["none"] += 1
        # The shared scanner deliberately knows nothing about personas — the
        # review framing is this skill's, not infrastructure.
        rec["persona"] = persona_for(rec["primary_stack"])
        rec["scanned_at"] = scanned_at
        report = read_report(path, SPEC)
        brief_path = os.path.join(out_dir, "%s.md" % name)
        try:
            with open(brief_path, "w", encoding="utf-8") as fh:
                fh.write(build_brief(rec, today, template, report, graph))
        except OSError as exc:
            results.append({"project": name, "status": "error",
                            "detail": str(exc)})
            continue
        results.append({
            "project": name,
            "status": "written",
            "brief": brief_path,
            "path": rec["path"],
            "primary_stack": rec["primary_stack"],
            "state": rec["state"],
            "total_loc": rec["total_loc"],
            "prior_open_items": 0 if not rec["report"]
                                else rec["report"]["item_count"],
            "graph": None if graph is None else {
                "status": (graph_result or {}).get("status", "existing"),
                "nodes": graph["nodes"],
                "stale": graph["stale"],
                "detail": (graph_result or {}).get("detail"),
            },
        })

    # Biggest first: the agents run concurrently, so starting the longest job
    # last is what makes a batch finish late.
    results.sort(key=lambda r: r.get("total_loc", 0), reverse=True)
    print(json.dumps({"root": root, "out_dir": out_dir, "today": today,
                      "graphify": codegraph.graphify_bin(),
                      "graph_totals": dict(graph_states),
                      "results": results}))
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="command", required=True)

    scan = subs.add_parser("scan", help="detect stacks and report staleness")
    scan.add_argument("--root")
    scan.add_argument("--project", action="append")
    scan.add_argument("--format", choices=("json", "table"), default="json",
                      help="table prints the picker rows ready to display")
    scan.set_defaults(func=cmd_scan)

    brief = subs.add_parser(
        "brief", help="write a ready-to-use agent prompt per project")
    brief.add_argument("--root")
    brief.add_argument("--project", action="append")
    brief.add_argument("--out", help="directory for the briefs; defaults to "
                                     "bbmax-recommendations under the system "
                                     "temp directory")
    brief.add_argument("--date", help="YYYY-MM-DD stamped into the brief as "
                                      "today; defaults to the local date")
    brief.add_argument("--no-graph", action="store_true",
                       help="do not run graphify; an existing code graph is "
                            "still offered to the agent, marked stale if it "
                            "is")
    brief.add_argument("--force-graph", action="store_true",
                       help="full re-extract instead of an incremental "
                            "update, for a repo whose code was deleted or "
                            "moved wholesale")
    brief.add_argument("--graph-timeout", type=int,
                       default=codegraph.DEFAULT_TIMEOUT,
                       help="seconds allowed per project graph build "
                            "(default: %d)" % codegraph.DEFAULT_TIMEOUT)
    brief.set_defaults(func=cmd_brief)

    graph = subs.add_parser(
        "graph", help="build or refresh the graphify code graph per project")
    graph.add_argument("--root")
    graph.add_argument("--project", action="append")
    graph.add_argument("--force", action="store_true",
                       help="full re-extract rather than an incremental update")
    graph.add_argument("--timeout", type=int, default=codegraph.DEFAULT_TIMEOUT,
                       help="seconds allowed per project (default: %d)"
                            % codegraph.DEFAULT_TIMEOUT)
    graph.set_defaults(func=cmd_graph)

    view = subs.add_parser("view", help="read existing recommendations.md files")
    view.add_argument("--root")
    view.add_argument("--project", action="append")
    view.add_argument("--full", action="store_true",
                      help="include each report's full markdown body")
    view.set_defaults(func=cmd_view)

    stamp = subs.add_parser(
        "stamp", help="backfill **Raised** dates into existing reports")
    stamp.add_argument("--root")
    stamp.add_argument("--project", action="append")
    stamp.add_argument("--date", help="YYYY-MM-DD; defaults to each report's "
                                      "own analyzed-at date")
    stamp.add_argument("--dry-run", action="store_true")
    stamp.set_defaults(func=cmd_stamp)

    ignore = subs.add_parser(
        "ignore", help="exclude recommendations.md and graphify-out/ via "
                       ".git/info/exclude")
    ignore.add_argument("--root")
    ignore.add_argument("--project", action="append")
    ignore.set_defaults(func=cmd_ignore)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
