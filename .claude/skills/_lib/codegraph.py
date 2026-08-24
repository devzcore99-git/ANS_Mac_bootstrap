"""The code-graph section of the agent briefs, for the two workspace sweeps.

The pipeline itself is not here. It lives in
../graphify-update/graph_pipeline.py because the /graphify-update skill is
copied into every project and has to run with nothing else present; holding a
second copy in _lib is how the two would drift. This module re-exports it so
/projects-recommendations and /projects-features-suggest can keep importing one
name.

What is genuinely this module's own is brief_section(): the wording that tells
a subagent to navigate by graph instead of by grep. It belongs with the two
skills that write briefs, not with the pipeline that builds graphs.
"""

import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(SCRIPT_DIR), "graphify-update"))
from graph_pipeline import (  # noqa: E402,F401  (re-exported for callers)
    DEFAULT_TIMEOUT, GRAPH_DIR, GRAPH_JSON, GRAPH_REPORT, build,
    exclude_entries, graphify_bin, info, repo_root)


def brief_section(path, graph, binp=None, purpose="review"):
    """The block of the agent brief that points at the graph.

    Written once, here, for the same reason the rest of the brief is: an agent
    told to "use the graph" in thirty differently-worded ways will use it
    thirty different amounts. The instruction that actually saves tokens is the
    last one — read files the graph points at, not the tree.
    """
    if not graph or not graph.get("report"):
        return []
    binp = binp or graphify_bin() or "graphify"
    size = ""
    if graph.get("nodes"):
        size = " (%s nodes, %s edges, %s communities)" % (
            "{:,}".format(graph["nodes"]), "{:,}".format(graph["edges"]),
            graph["communities"])

    if purpose == "features":
        lead = ("Use it to see what the project already does, so nothing you "
                "propose duplicates code that is already there, and to find "
                "the seams a new capability would attach to.")
    else:
        lead = ("Use it to find where the work is — hubs, cycles, bridges and "
                "orphans are where defects and structural problems live.")

    freshness = "current"
    if graph.get("stale"):
        # A graph built against an older commit still maps most of the repo,
        # but the agent has to know which of the two it is looking at.
        freshness = ("built from an **older commit** than the one you are "
                     "reviewing, so treat anything it shows as a starting "
                     "point to confirm in the source")

    return [
        "## Codebase map — use it before the source tree",
        "",
        "This project has a graphify code graph%s, %s. %s"
        % (size, freshness, lead),
        "",
        "1. Read `%s` first. It gives you the architecture in about two "
        "thousand tokens: god nodes (the most connected symbols), community "
        "structure with member lists, import cycles, cross-community bridges, "
        "isolated nodes, and the questions the graph itself flags."
        % graph["report"],
        "2. Then query the graph instead of grepping the tree. Run these from "
        "`%s`:" % path,
        "",
        "   ```bash",
        "   %s query \"<question>\" --budget 1500   # scoped subgraph for one question"
        % binp,
        "   %s explain \"<symbol>\"                 # a symbol and its neighbours"
        % binp,
        "   %s path \"<A>\" \"<B>\"                   # how two symbols connect"
        % binp,
        "   %s affected \"<symbol>\" --depth 2      # what a change to it reaches"
        % binp,
        "   %s god-nodes --top 15                 # the core abstractions"
        % binp,
        "   ```",
        "",
        "3. Open source files only where the map says to. Reading the whole "
        "tree is what the graph exists to make unnecessary, and on a repo of "
        "any size it costs many times what following the graph does.",
        "",
        "The graph is a map, not evidence. It is AST-derived, so it shows "
        "structure and not behaviour; it says nothing about runtime, config or "
        "prose; `INFERRED` edges are model-guessed; and community names are "
        "placeholders like `Community 7`, so use the member lists rather than "
        "the names. **Read the actual source before you write down any "
        "finding.** A claim sourced to the graph alone does not go in the "
        "report.",
        "",
    ]
