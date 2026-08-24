#!/usr/bin/env python3
"""Support script for the /graphify-update skill.

Builds or refreshes one project's graphify code graph and prints what the graph
now contains, so a session can navigate the repo by graph instead of by grep.

There is one decision in here worth naming: whether to extract or to update.
A first build has to run `graphify extract --code-only`; every build after that
has to run `graphify update`, which re-extracts only what changed and leaves a
richer prior graph intact. Getting that backwards is slow at best and, if the
`--code-only` flag goes missing on a first build, sends the project's documents
to an LLM backend and bills for them. The choice is made from the presence of
graphify-out/graph.json rather than left to whoever is typing.

The pipeline lives in graph_pipeline.py beside this file — self-contained, so
this skill keeps working in the copy every project carries. The two workspace
sweeps, /projects-recommendations and /projects-features-suggest, borrow that
same module, so all three build graphs identically.

Usage:
  python3 graphify-update.py [PATH ...] [--force] [--json]
                             [--timeout SECONDS] [--no-exclude]
  python  graphify-update.py ...    # Windows

PATH defaults to the current directory and is resolved to the repository root,
so running it from a subdirectory still maps the whole project. Exit status is
0 when every target has a graph, 1 when any failed.
"""

import argparse
import json
import os
import re
import sys

# The pipeline sits beside this file, not in ../_lib, because /project-bootstrap
# copies this skill into every project: a copy has to run with nothing else
# present. realpath, not abspath, so the import still resolves if the directory
# is reached through a link.
SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, SCRIPT_DIR)
import graph_pipeline as graph  # noqa: E402

GENERATED_BY = "/graphify-update"

GOD_RE = re.compile(r"^\s*\d+\.\s+`(.+?)`\s*-\s*(\d+)\s+edges")
HEADING_RE = re.compile(r"^##\s+(.+?)\s*$")


def digest(report_path):
    """Hubs and cycles out of GRAPH_REPORT.md, for the one-screen summary.

    Best effort by design: these are prose sections and the wording is
    graphify's to change. A miss costs two lines of output, never the run.
    """
    out = {"hubs": [], "cycles": None}
    try:
        with open(report_path, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return out
    section = None
    for line in lines:
        heading = HEADING_RE.match(line)
        if heading:
            section = heading.group(1).lower()
            continue
        if section and section.startswith("god nodes"):
            m = GOD_RE.match(line)
            # Deduplicated by label: a heading repeated across files is a
            # separate node per file, and three identical rows read as a bug
            # rather than as the three files they are.
            seen = {h[0] for h in out["hubs"]}
            if m and len(out["hubs"]) < 5 and m.group(1) not in seen:
                out["hubs"].append((m.group(1), int(m.group(2))))
        elif section and section.startswith("import cycles"):
            if line.strip().startswith("-") and out["cycles"] is None:
                out["cycles"] = line.strip().lstrip("- ").rstrip(".")
    return out


def run_one(path, args):
    root, in_repo = graph.repo_root(path)
    result = {"path": root, "in_repo": in_repo}

    if in_repo and not args.no_exclude:
        # Before the build, not after: a multi-megabyte graphify-out/ should
        # never exist as untracked work, not even briefly.
        result["exclude"] = graph.exclude_entries(
            root, ["%s/" % graph.GRAPH_DIR], GENERATED_BY)

    result.update(graph.build(root, force=args.force, timeout=args.timeout))
    info = graph.info(root, head=graph.head_commit(root)) or {}
    result["built_commit"] = info.get("built_commit")
    result["stale"] = info.get("stale")
    if info.get("report"):
        result.update(digest(info["report"]))
    return result


def plural(count, singular, plural_form=None):
    word = singular if count == 1 else (plural_form or singular + "s")
    return "%s %s" % ("{:,}".format(count), word)


def render(result, binp):
    name = os.path.basename(result["path"])
    status = result["status"]

    if status == "unavailable":
        print("%s: graphify is not installed on this machine." % name)
        print("  Nothing was changed. Install graphify, or work from the "
              "source directly.")
        return
    if status == "error":
        print("%s: graph build failed — %s"
              % (name, result.get("detail", "no detail")))
        return
    if status == "no-code":
        print("%s: nothing to map — graphify found no code files here." % name)
        print("  Normal for a prose repo; there is no call graph to draw.")
        return

    counts = ""
    if result.get("nodes"):
        counts = " — %s, %s, %s" % (
            plural(result["nodes"], "node"), plural(result["edges"], "edge"),
            plural(result["communities"], "community", "communities"))
    print("%s: graph %s%s" % (name, status, counts))
    if result.get("report"):
        print("  Report:  %s" % result["report"])
    if result.get("built_commit"):
        freshness = "current with HEAD" if result.get("stale") is False \
            else "HEAD has moved since" if result.get("stale") else "unknown"
        print("  Commit:  %s (%s)" % (result["built_commit"], freshness))
    exclude = result.get("exclude") or {}
    if exclude.get("status") == "excluded":
        print("  Git:     graphify-out/ added to .git/info/exclude")
    elif exclude.get("status") == "error":
        print("  Git:     could not exclude graphify-out/ — %s"
              % exclude.get("detail"))
    if result.get("hubs"):
        print("  Hubs:    %s" % " · ".join(
            "%s %d" % (n, e) for n, e in result["hubs"]))
    if result.get("cycles"):
        print("  Cycles:  %s" % result["cycles"])
    print("  Query:   %s query \"<question>\" --budget 1500   "
          "(also: explain, path, affected, god-nodes)" % binp)


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("path", nargs="*", default=["."],
                        help="project directories (default: the current one); "
                             "each is resolved to its repository root")
    parser.add_argument("--force", action="store_true",
                        help="full re-extract instead of an incremental "
                             "update, for a repo whose code was deleted or "
                             "moved wholesale")
    parser.add_argument("--timeout", type=int,
                        default=graph.DEFAULT_TIMEOUT,
                        help="seconds allowed per project (default: %d)"
                             % graph.DEFAULT_TIMEOUT)
    parser.add_argument("--no-exclude", action="store_true",
                        help="do not touch .git/info/exclude; the graph will "
                             "show up as untracked work")
    parser.add_argument("--json", action="store_true",
                        help="machine-readable output instead of the summary")
    args = parser.parse_args()

    binp = graph.graphify_bin()
    results = [run_one(p, args) for p in (args.path or ["."])]

    if args.json:
        print(json.dumps({"graphify": binp, "results": results}))
    else:
        for i, result in enumerate(results):
            if i:
                print("")
            render(result, binp or "graphify")

    failed = [r for r in results
              if r["status"] in ("error", "unavailable")]
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
