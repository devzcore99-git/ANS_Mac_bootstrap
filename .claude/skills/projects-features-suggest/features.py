#!/usr/bin/env python3
"""Support script for the /projects-features-suggest skill.

Subcommands emitting JSON on stdout, except where noted:

  scan     Discover repos, detect each one's tech stack, and report whether its
           features.md is missing, stale, current, or foreign. Drives the
           project picker. --format table prints those rows ready to display.

  brief    Build each project's code graph, then write a complete,
           ready-to-use agent prompt per project into a directory, so
           dispatching N ideators costs one line of prompt each rather than N
           copies of the same instructions.

  graph    Build or refresh the graphify code graph for the given projects
           without writing briefs. brief does this for you; this is the way to
           rebuild one by hand, or to force a full re-extract.

  view     Read the features.md files that already exist and return them as
           structured data, split into wanted / built / declined.

  decline  Move an idea to ## Declined with a reason. This is how an idea
           leaves the list without being built, and how a later run knows not
           to propose it again.

  ignore   Add features.md and graphify-out/ to a repo's .git/info/exclude.
           That file is local and untracked, so the entries never show up as
           pending changes the way editing .gitignore would.

Repo discovery, stack detection, and report parsing live in
../_lib/projectscan.py, and the graphify code graph in ../_lib/codegraph.py,
both shared with /projects-recommendations. What stays here
is what makes this skill an ideation pass rather than a code review: the
product-minded personas, the agent brief, and the report shape.

Runs on Windows, macOS, and Linux. Requires Python 3.7+ and git on PATH;
nothing outside the standard library.

Usage:
  python3 features.py scan [--root DIR] [--project NAME ...]
                           [--format json|table]
  python3 features.py brief [--root DIR] [--project NAME ...]
                            [--out DIR] [--date YYYY-MM-DD]
                            [--no-graph] [--force-graph]
  python3 features.py graph [--root DIR] [--project NAME ...] [--force]
  python3 features.py view [--root DIR] [--project NAME ...] [--full]
  python3 features.py decline --project NAME --title TEXT --reason TEXT
                              [--root DIR] [--date YYYY-MM-DD] [--dry-run]
  python3 features.py ignore --project NAME [--root DIR]
  python  features.py ...    # Windows
"""

import argparse
import json
import os
import re
import sys
import tempfile
from collections import Counter
from datetime import datetime, timezone

# realpath, not abspath: a skill reached through a symlink must resolve back
# into the repo that holds it, or the shared library is not there.
SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(SCRIPT_DIR), "_lib"))
import codegraph  # noqa: E402
from projectscan import (  # noqa: E402
    ITEM_RE, ReportSpec, die, exclude_report, load_root, print_scan_table,
    read_report, resolve_projects, scan_one, scope_of)

# An idea leaves the open list two ways, and they are not the same fact. Built
# is verifiable in the code; Declined is a decision the user made. Both are
# "settled" to the parser, and both must survive every future run.
SPEC = ReportSpec(
    report_name="features.md",
    generated_by="/projects-features-suggest",
    done_categories=("Built", "Declined"),
    fields=("Where", "Why", "How", "Effort", "Needs", "Raised", "Built",
            "Declined", "Evidence", "Reason"),
)

OPEN_CATEGORIES = ("Core", "Adjacent", "Integration", "Experience")

# How to frame the ideating agent, keyed by primary stack. Kept here rather
# than in the shared library on purpose: /projects-recommendations keys its own
# table on the same stacks, but a reviewer hunting defects and an ideator
# proposing capabilities are different voices. What matters in this one is
# ecosystem fluency — knowing what already exists so the proposal is "wire up
# X" rather than "build X from scratch".
PERSONAS = {
    "Python": "a senior Python engineer with a product instinct. You know the "
              "ecosystem well enough to say which capability is a weekend and "
              "which is a month, and when a library already solves it",
    "JavaScript/TypeScript": "a senior TypeScript/JavaScript engineer with a "
                             "product instinct, fluent in what the npm "
                             "ecosystem and the modern browser already give "
                             "you for free",
    "PowerShell": "a Windows automation architect who knows what PowerShell "
                  "modules, scheduled tasks, and WMI/CIM already expose, and "
                  "what is worth automating next",
    "Shell": "a Unix tooling expert who knows when a shell script should grow "
             "a capability and when it has outgrown shell entirely",
    "Batch": "a Windows scripting expert who knows what a .bat can still do "
             "well and when the job belongs in PowerShell instead",
    "Ansible": "an infrastructure automation architect, thinking about what "
               "else this playbook could provision, verify, or roll back",
    "Docker": "a container platform engineer, thinking about what services "
              "this stack could add, expose, or monitor",
    "Dev Container": "a developer-experience engineer, thinking about what "
                     "would make this environment faster to start and harder "
                     "to get wrong",
    "Web": "a frontend product engineer, thinking about what the interface "
           "could show, capture, or make faster for the person using it",
    "SQL": "a data platform engineer, thinking about what questions this "
           "schema cannot answer yet and what it would take to answer them",
    "Jupyter": "a data science lead, thinking about what analysis this "
               "notebook is one step away from supporting",
    "AmiBroker AFL": "a quantitative trading systems expert, thinking about "
                     "what signals, filters, or backtest capabilities this "
                     "system is missing",
    "Docs": "an information architect. This is a knowledge base, not a "
            "codebase — propose content and structure it should gain, not "
            "software features it has no code to host",
    "Config": "a pragmatic reviewer — if there is too little here to build "
              "on, say so plainly rather than inventing a roadmap",
}
PERSONAS["Data"] = PERSONAS["Config"]
PERSONAS["Unknown"] = PERSONAS["Config"]

GENERIC_LANG = ("a senior %s engineer with a product instinct, fluent in what "
                "that language's ecosystem already offers")


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


SIGNAL_LABELS = [
    ("readme", "a README"),
    ("claude_md", "a CLAUDE.md"),
    ("tests", "a test suite"),
    ("ci", "a CI workflow"),
    ("lockfile", "a dependency lockfile"),
    ("license", "a LICENSE"),
]


def build_brief(rec, today, template_path, report, siblings, graph=None):
    """The full agent prompt for one project, as markdown.

    Everything invariant lives here rather than being retyped into each Agent
    call. On a 38-repo workspace that is the difference between the model
    generating ~800 tokens per project and ~30, and it removes the chance of
    the carry-forward rules being paraphrased differently for each agent —
    which matters most for Declined, where a paraphrase that loses the "never
    re-propose" clause makes every run repeat ideas the user already turned
    down.
    """
    loc = " | ".join("%s: %s" % (s, "{:,}".format(n))
                     for s, n in rec["loc_by_stack"].items()) or "none counted"
    secondary = ", ".join(rec["stacks"][1:]) or "none"
    absent = [label for key, label in SIGNAL_LABELS
              if not rec["signals"].get(key)]

    out = [
        "# Feature brief — %s" % rec["project"],
        "",
        "You are %s." % rec["persona"],
        "",
        "Propose what this project should gain next. Read "
        "`%s` and write exactly one file: `%s`."
        % (rec["path"], os.path.join(rec["path"], SPEC.report_name)),
        "",
        "This is not a code review. Defects, cleanups, and performance work "
        "belong to `/projects-recommendations` and are out of scope here — if "
        "you notice one, leave it alone. You are answering \"what could this "
        "do that it cannot do today?\"",
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
        "- **Today's date is %s.** Use it for `**Raised**` on new ideas. Do "
        "not infer the date from anything else — you have no reliable clock."
        % today,
        "",
        "## Ground the ideas before you have them",
        "",
        "Read the project's own `README.md`, `CLAUDE.md`, and `TODOs.md` "
        "first, where they exist. A proposal that ignores what the project "
        "says it is trying to be is worse than no proposal. In particular:",
        "",
        "- Anything already listed in `TODOs.md` is **already known**. Do not "
        "re-propose it as your idea. You may propose a concrete design for "
        "it, saying plainly that the TODO already asks for it.",
        "- If `CLAUDE.md` or the README rules something out — a scope limit, "
        "a deliberate non-goal — respect it. Proposing it anyway wastes the "
        "reader's time and the file's credibility.",
        "",
    ]

    if absent:
        out += [
            "This project has none of: %s. That is context for judging "
            "scale, not a to-do list — missing scaffolding is "
            "`/projects-recommendations`' business, not yours."
            % ", ".join(absent),
            "",
        ]

    out += codegraph.brief_section(rec["path"], graph, purpose="features")

    if siblings:
        out += [
            "## Other projects in this workspace",
            "",
            "These repos sit alongside it. Integration ideas — one project "
            "feeding, reading, or triggering another — are the ones a "
            "single-project review cannot see, so they are worth real "
            "attention. Name the specific sibling and the specific data or "
            "event that would cross between them; do not propose vague "
            "\"integrate with X\" items.",
            "",
        ]
        out.append("| Project | Stack | Size |")
        out.append("|---------|-------|------|")
        for sib in siblings:
            out.append("| %s | %s | %s lines |" % (
                sib["project"], sib["primary_stack"],
                "{:,}".format(sib["total_loc"])))
        out.append("")

    if report and report["items"]:
        wanted = [i for i in report["items"] if not i["done"]]
        built = [i for i in report["items"] if i["category"] == "Built"]
        declined = [i for i in report["items"] if i["category"] == "Declined"]
        out += [
            "## Re-run protocol — this project already has a %s"
            % SPEC.report_name,
            "",
            "The existing file is an input, not something to overwrite. Read "
            "it **before** any source, and account for every item in it.",
            "",
            "For each idea currently open, decide one of three things:",
            "",
            "- **Still wanted** — carry it forward into the same section with "
            "its `**Raised**` date **unchanged**. Sharpen `Why`/`How` if you "
            "have learned more; it is the same idea and keeps its date.",
            "- **Built** — move it to `## Built` with `**Built**: %s`, the "
            "original `**Raised**` date, and an `**Evidence**` line pointing "
            "at the code that now does it. Verify it in the source; a "
            "plausible-looking commit message is not proof." % today,
            "- **No longer applicable** — move it to `## Declined` with "
            "`**Declined**: %s` and a `**Reason**` that says why (\"the "
            "module it extended was removed\", \"the project changed "
            "direction\"). Never silently drop it." % today,
            "",
            "**Do not decline an idea because you disagree with it.** "
            "Declining is the user's call, and `## Declined` is where their "
            "decisions are recorded. Yours is limited to ideas that have "
            "become impossible or meaningless.",
            "",
        ]
        if declined:
            out += [
                "### Already declined — do not propose these again",
                "",
                "The user has turned these down. Re-raising a declined idea "
                "in a new section is the single failure this file exists to "
                "prevent: it makes every run repeat a conversation that was "
                "already had. If you believe one deserves another look, say "
                "so in the `## Summary` — do not move it back into the open "
                "sections.",
                "",
            ]
            for item in declined:
                out.append("- %s — %s" % (
                    item["title"], item.get("reason", "no reason recorded")))
            out.append("")
        if built:
            out += ["Already built, and staying in `## Built` untouched, "
                    "newest first:", ""]
            for item in built:
                out.append("- %s (built %s)" % (
                    item["title"], item.get("built", "?")))
            out.append("")
        if wanted:
            out += ["The %d open idea(s) you must account for:"
                    % len(wanted), ""]
            for item in wanted:
                where = item.get("where", "?").strip("`") or "?"
                out.append("- [%s] %s — `%s` (Raised: %s)" % (
                    item["priority"], item["title"], where,
                    item.get("raised", "undated")))
            out.append("")

    out += [
        "## Output format",
        "",
        "Follow `%s` exactly. Its structure is load-bearing — `scan` and "
        "`view` parse this file, so the metadata comments, the `## ` section "
        "headings, the `### [High] Title` item headings, and the "
        "`**Where**:` field lines must all match. Delete the template's own "
        "\"Format rules\" section from what you write." % template_path,
        "",
        "The four open sections are `## %s`. Drop any that came back empty "
        "rather than padding it." % "`, `## ".join(OPEN_CATEGORIES),
        "",
        "## What makes an idea worth writing down",
        "",
        "- **It is grounded.** Point at the module it would extend or the "
        "data it would use. \"Add a plugin system\" is not an idea; \"let "
        "`fetch.py` take a `--source` flag so the Yahoo and Stooq paths stop "
        "being copy-pasted\" is.",
        "- **It fits the project's size.** A 400-line personal utility does "
        "not want a plugin architecture, a web UI, or a plugin marketplace. "
        "Saying \"this is the right size already, here are two small things\" "
        "is a legitimate and useful answer.",
        "- **It says what it costs.** `**Effort**` is S, M, or L. "
        "`**Needs**` names any new third-party dependency the idea would "
        "require, or `none`. This workspace does not install libraries "
        "without asking, so an idea that quietly assumes a new one is an idea "
        "the reader cannot act on.",
        "- **Ten specific beats thirty generic.** An empty section is "
        "deleted, not filled.",
        "",
        "## Constraints",
        "",
        "- **Write only `%s` at the project root. Change no other file.** "
        "Propose; do not implement. No code changes, no refactors, no `git` "
        "commands." % SPEC.report_name,
        "- Every open idea carries a `**Raised**` date.",
        "- Do not propose work that is already in `TODOs.md`, already in "
        "`## Built`, or already in `## Declined`.",
        "",
        "## What to return",
        "",
        "Two lines, as your final message — not the file itself:",
        "",
        "1. Idea counts by priority, and (on a re-run) how many prior ideas "
        "you carried forward, marked built, or retired.",
        "2. The single highest-value idea, in one sentence.",
        "",
    ]
    return "\n".join(out)


def cmd_brief(args):
    root = load_root(args.root)
    repos = resolve_projects(root, args.project)

    out_dir = (os.path.abspath(os.path.expanduser(args.out)) if args.out
               else os.path.join(tempfile.gettempdir(), "bbmax-features"))
    try:
        os.makedirs(out_dir, exist_ok=True)
    except OSError as exc:
        die("Could not create the brief directory %s: %s" % (out_dir, exc))

    today = args.date or datetime.now().strftime("%Y-%m-%d")
    template = os.path.join(SCRIPT_DIR, "TEMPLATE.md")
    scanned_at = datetime.now(timezone.utc).astimezone().isoformat(
        timespec="seconds")

    # Integration ideas need to know what else is in the workspace, so every
    # brief carries the full roster regardless of which projects were selected.
    # It is one line per repo — cheap next to what it unlocks.
    all_repos = discover_siblings(root)
    # Refreshing the graph here rather than in a step of its own is deliberate:
    # a brief that points an agent at a code graph must not be able to point it
    # at a stale one, and a separate step is a step that can be skipped.
    build_graphs = not args.no_graph and bool(codegraph.graphify_bin())

    results = []
    graph_states = Counter()
    for name, path in repos:
        rec = scan_one(name, path, SPEC)
        if rec["state"] == "foreign":
            results.append({"project": name, "status": "skipped-foreign",
                            "detail": rec["reason"]})
            continue
        rec["persona"] = persona_for(rec["primary_stack"])
        rec["scanned_at"] = scanned_at
        report = read_report(path, SPEC)
        siblings = [s for s in all_repos if s["project"] != name]

        graph_result = None
        if build_graphs:
            graph_result = codegraph.build(path, force=args.force_graph,
                                           timeout=args.graph_timeout)
            graph_states[graph_result["status"]] += 1
        graph = codegraph.info(path, head=rec["head_full"])
        if graph is None:
            graph_states["none"] += 1

        brief_path = os.path.join(out_dir, "%s.md" % name)
        try:
            with open(brief_path, "w", encoding="utf-8") as fh:
                fh.write(build_brief(rec, today, template, report, siblings,
                                     graph))
        except OSError as exc:
            results.append({"project": name, "status": "error",
                            "detail": str(exc)})
            continue
        counts = {"wanted": 0, "built": 0, "declined": 0}
        if report:
            for item in report["items"]:
                if item["category"] == "Built":
                    counts["built"] += 1
                elif item["category"] == "Declined":
                    counts["declined"] += 1
                else:
                    counts["wanted"] += 1
        results.append({
            "project": name,
            "status": "written",
            "brief": brief_path,
            "path": rec["path"],
            "primary_stack": rec["primary_stack"],
            "state": rec["state"],
            "total_loc": rec["total_loc"],
            "prior": counts,
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


_SIBLING_CACHE = None


def discover_siblings(root):
    """One line per repo in the workspace, for the integration section.

    Deliberately cheap: name, stack, and size only. Reading each sibling's
    README would be better context and is not worth 38 file reads per brief.
    """
    global _SIBLING_CACHE
    if _SIBLING_CACHE is None:
        _SIBLING_CACHE = []
        for name, path in resolve_projects(root, None):
            rec = scan_one(name, path, SPEC)
            _SIBLING_CACHE.append({
                "project": name,
                "primary_stack": rec["primary_stack"],
                "total_loc": rec["total_loc"],
            })
    return _SIBLING_CACHE


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
        wanted = [i for i in report["items"] if not i["done"]]
        built = [i for i in report["items"] if i["category"] == "Built"]
        declined = [i for i in report["items"] if i["category"] == "Declined"]
        entry = {
            "project": name,
            "path": report["path"],
            "stack": report["meta"].get("stack"),
            "analyzed_at": report["meta"].get("analyzed-at"),
            "analyzed_commit": (report["meta"].get("analyzed-commit") or "")[:8],
            "summary": report["summary"],
            "by_priority": dict(Counter(i["priority"] for i in wanted)),
            "by_category": dict(Counter(i["category"] for i in wanted)),
            "wanted_count": len(wanted),
            "built_count": len(built),
            "declined_count": len(declined),
            "needs_new_dependency": [
                {"title": i["title"], "needs": i["needs"]} for i in wanted
                if i.get("needs") and i["needs"].strip().lower() != "none"],
            "raised_dates": sorted({i["raised"] for i in wanted
                                    if i.get("raised")}),
            "undated_items": [i["title"] for i in wanted if not i.get("raised")],
            "wanted": wanted,
            "built": built,
            "declined": declined,
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
            "wanted": sum(e["wanted_count"] for e in found),
            "built": sum(e["built_count"] for e in found),
            "declined": sum(e["declined_count"] for e in found),
            "undated_items": sum(len(e["undated_items"]) for e in found),
            "needs_new_dependency": sum(len(e["needs_new_dependency"])
                                        for e in found),
            "by_priority": dict(totals),
        },
        "without_report": absent,
        "foreign_reports": foreign,
        "projects": found,
    }, indent=None))


DECLINE_KEEP = ("where", "raised")


def decline_text(text, title, reason, date):
    """Move the item whose heading matches `title` into ## Declined.

    Returns (new_text, moved_title) or (text, None) if nothing matched. The
    item keeps Where and Raised and loses Why/How/Effort/Needs: the idea is
    settled, and the detail is what made it worth considering, not worth
    storing.
    """
    lines = text.splitlines()
    start = end = None
    priority = matched = None

    for i, line in enumerate(lines):
        hit = ITEM_RE.match(line)
        if hit and start is None and title.lower() in hit.group(2).lower():
            start, priority, matched = i, hit.group(1).title(), hit.group(2)
            continue
        if start is not None and end is None:
            # The block runs to the next heading of any level.
            if line.startswith("#"):
                end = i
    if start is None:
        return text, None
    if end is None:
        end = len(lines)

    kept = []
    for line in lines[start + 1:end]:
        hit = SPEC.field_re.match(line)
        if hit and hit.group(1).lower() in DECLINE_KEEP:
            kept.append(line)

    block = ["### [%s] %s" % (priority, matched), ""]
    block += kept
    block.append("**Declined**: %s" % date)
    block.append("**Reason**: %s" % reason)
    block.append("")

    remaining = lines[:start] + lines[end:]

    # Land it at the top of ## Declined, newest first, creating the section at
    # the end of the file if this is the first one.
    try:
        anchor = next(i for i, line in enumerate(remaining)
                      if line.strip() == "## Declined")
        insert = anchor + 1
        while insert < len(remaining) and not remaining[insert].strip():
            insert += 1
        out = remaining[:insert] + block + remaining[insert:]
    except StopIteration:
        while remaining and not remaining[-1].strip():
            remaining.pop()
        out = remaining + ["", "## Declined", ""] + block

    return "\n".join(out) + "\n", matched


def cmd_decline(args):
    root = load_root(args.root)
    repos = resolve_projects(root, [args.project])
    date = args.date or datetime.now().strftime("%Y-%m-%d")
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
        die("--date must be YYYY-MM-DD, got %r" % date)

    name, path = repos[0]
    report = read_report(path, SPEC)
    if report is None:
        die("%s has no %s to edit." % (name, SPEC.report_name))
    if report["meta"].get("generated-by") != SPEC.generated_by:
        die("%s here is not skill output — refusing to edit it."
            % SPEC.report_name)

    new_text, matched = decline_text(report["raw"], args.title, args.reason,
                                     date)
    if matched is None:
        open_titles = [i["title"] for i in report["items"] if not i["done"]]
        die("No open idea in %s matches %r. Open ideas: %s"
            % (name, args.title, "; ".join(open_titles) or "none"))

    if args.dry_run:
        print(json.dumps({"project": name, "status": "would-decline",
                          "title": matched, "date": date}))
        return
    try:
        with open(report["path"], "w", encoding="utf-8") as fh:
            fh.write(new_text)
    except OSError as exc:
        die("Could not write %s: %s" % (report["path"], exc))
    print(json.dumps({"project": name, "status": "declined",
                      "title": matched, "date": date,
                      "path": report["path"]}))


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
            "note": "graphify is not installed — ideation falls back to "
                    "reading source directly",
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
                                     "bbmax-features under the system temp "
                                     "directory")
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

    view = subs.add_parser("view", help="read existing features.md files")
    view.add_argument("--root")
    view.add_argument("--project", action="append")
    view.add_argument("--full", action="store_true",
                      help="include each report's full markdown body")
    view.set_defaults(func=cmd_view)

    decline = subs.add_parser(
        "decline", help="retire an idea into ## Declined with a reason")
    decline.add_argument("--root")
    decline.add_argument("--project", required=True)
    decline.add_argument("--title", required=True,
                         help="substring of the idea's heading; must match "
                              "exactly one open idea")
    decline.add_argument("--reason", required=True,
                         help="why it is being turned down — this is what "
                              "stops a later run proposing it again")
    decline.add_argument("--date", help="YYYY-MM-DD; defaults to today")
    decline.add_argument("--dry-run", action="store_true")
    decline.set_defaults(func=cmd_decline)

    ignore = subs.add_parser(
        "ignore", help="exclude features.md and graphify-out/ via "
                       ".git/info/exclude")
    ignore.add_argument("--root")
    ignore.add_argument("--project", action="append")
    ignore.set_defaults(func=cmd_ignore)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
