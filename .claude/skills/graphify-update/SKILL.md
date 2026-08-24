---
name: graphify-update
description: >-
  Build or refresh a project's graphify code graph — a first extract when there
  is none, an incremental update when there is — then report what the map now
  holds: node and edge counts, the most connected symbols, import cycles, and
  the path to GRAPH_REPORT.md. Deterministic and offline, no API key and no LLM
  call. Use when the user asks to update, rebuild, or refresh the code graph,
  to graphify or re-graphify a project, to map or re-map a codebase, or to get
  the graph current before asking questions about the code — including
  phrasings like "run graphify here", "update the graph", or "build me a map of
  this repo". Not for querying a graph that already exists, which is
  `graphify query` directly, and not needed before /projects-recommendations or
  /projects-features-suggest, which refresh their own graphs.
---

# Graphify Update

One command, run when the user asks for it. It leaves
`<project>/graphify-out/` holding a current code graph and prints a summary of
what is in it.

```bash
# macOS / Linux
python3 $SKILL_DIR/graphify-update.py [PATH ...]

# Windows
python $SKILL_DIR/graphify-update.py [PATH ...]
```

`$SKILL_DIR` is the base directory printed when this skill loads. It is not a
real environment variable: substitute the printed path, or set it inline in the
same command (`SKILL_DIR=... python3 "$SKILL_DIR/..."`), because shell state
does not persist between calls.

`PATH` defaults to the current directory and is resolved to its repository
root, so running from a subdirectory still maps the whole project. Pass several
paths to do several projects in one call.

| Flag | When |
|------|------|
| `--force` | Full re-extract rather than an incremental update. For a repo whose code was deleted or moved wholesale, where an incremental pass leaves dead symbols in the graph |
| `--json` | Machine-readable output instead of the summary |
| `--timeout N` | Seconds allowed per project (default 600) |
| `--no-exclude` | Leave `.git/info/exclude` alone, and accept `graphify-out/` showing as untracked work |

Run `python3 $SKILL_DIR/graphify-update.py --help` for the full interface.

### Availability in other projects

This skill is **copied** into every project by `/project-bootstrap`, into that
project's own `.claude/skills/graphify-update/`, and listed in
`bundled_skills` so `/project-bootstrap-audit --audit-skills` reports any
project whose copy is missing or has drifted. Refresh drifted copies with
`--update-skills`.

Copied, never symlinked: most projects open in a devpod, where the workspace
root does not exist and a link into `~/AI_Projects` resolves to nothing — and
the same holds in a fresh clone, in CI, and on Windows, which is exactly where
a project most needs to carry its own tooling.

That is why `graph_pipeline.py` sits in this directory rather than in
`../_lib/`. The three files here are the whole skill; it imports nothing
outside the standard library, reads no `skills_config.json`, and works with
ASST_BBMax nowhere in sight. Keep it that way — an import from `../_lib` would
work here and fail in all thirty-odd copies.

## What it does

1. Resolves each path to its repository root.
2. Adds `graphify-out/` to `.git/info/exclude` — before the build, so a
   multi-megabyte graph is never briefly visible as untracked work. That file
   is local and untracked, unlike `.gitignore`, so this leaves no pending
   change and keeps `/projects-git-status` clean.
3. Builds the graph: `graphify extract <path> --code-only` on a first run,
   `graphify update <path>` on every run after, then
   `graphify cluster-only <path> --no-label --no-viz` when the report is
   missing.
4. Prints the summary below.

Steps 2–4 come from `graph_pipeline.py` beside this file.
`/projects-recommendations` and `/projects-features-suggest` borrow that same
module through `../_lib/codegraph.py`, so all three build graphs identically.

## What you get back

```
CODE_Pacman: graph built — 386 nodes, 957 edges, 20 communities
  Report:  /home/ahill/AI_Projects/CODE_Pacman/graphify-out/GRAPH_REPORT.md
  Commit:  c4911c01 (current with HEAD)
  Git:     graphify-out/ added to .git/info/exclude
  Hubs:    update() 21 · cmd_dispatch() 19 · run_one() 16 · git() 16 · Report 15
  Cycles:  None detected
  Query:   graphify query "<question>" --budget 1500   (also: explain, path, affected, god-nodes)
```

Show it as printed. It is already the report — do not re-render it as a table
or a prose paragraph.

**Then use the graph for the rest of the session.** That is the point of
building it. Before grepping the tree or opening files to find something, run:

```bash
graphify query "<question>" --budget 1500   # scoped subgraph for one question
graphify explain "<symbol>"                 # a symbol and its neighbours
graphify path "<A>" "<B>"                   # how two symbols connect
graphify affected "<symbol>" --depth 2      # what a change to it reaches
graphify god-nodes --top 15                 # the core abstractions
```

Run them from the project directory; they default to `graphify-out/graph.json`.
Read `GRAPH_REPORT.md` when you want the whole architecture at once — it is
about two thousand tokens for god nodes, communities with member lists, import
cycles, cross-community bridges and isolated nodes.

The graph is a map, not evidence: it is AST-derived, `INFERRED` edges are model
guesses, and it says nothing about runtime behaviour. Read the source before
asserting anything from it.

## Statuses

| Status | Meaning |
|--------|---------|
| `built` | First graph for this project |
| `updated` | Existing graph re-extracted against the current tree |
| `no-code` | graphify found nothing it can parse. Normal for a prose repo — say so and stop |
| `error` | The build failed; the detail line says how |
| `unavailable` | graphify is not installed here |

Exit status is 1 when any target ended `error` or `unavailable`, 0 otherwise.

## Gotchas

- **`--code-only` and `--no-label` are load-bearing, and the script owns
  them.** Without `--code-only` a first build sends the project's documents to
  an LLM backend; without `--no-label` the clustering pass calls one to name
  communities. Either flag going missing turns a free, offline step into a
  billed one. Do not hand-run `graphify extract` in place of this script.
- **`extract` does not write `GRAPH_REPORT.md`.** It stops at `graph.json` and
  prints a "next: run cluster-only" line. A graph built by an older run can
  therefore have no report at all — this script runs the clustering pass when
  the report is missing, which is why it is what you call rather than
  `graphify` directly.
- **The first build maps code; the next one also maps documents.** `update`
  re-extracts every file type structurally, so node counts jump on the second
  run and markdown headings start appearing among the hubs. No LLM is involved
  either way — it is not a sign that something billed.
- **graphify refuses to write a smaller graph.** A rebuild with fewer nodes
  than the last one is rejected to protect a richer graph from being clobbered.
  After deleting or moving a lot of code, that means the graph keeps symbols
  that no longer exist — re-run with `--force`.
- **Community names are placeholders** (`Community 7`) because naming them
  costs an LLM call. Use the member lists in `GRAPH_REPORT.md`, not the names.
- **This is not the `/graphify` skill that ships with graphify itself.** That
  one drives a full semantic pipeline through subagents and an API key. This
  one is the cheap deterministic subset, and it is what this workspace wants
  unless the user explicitly asks for semantic extraction over documents.

## Done when

`graphify-out/graph.json` and `graphify-out/GRAPH_REPORT.md` both exist, the
summary reports a node count and a commit marked `current with HEAD`, and
`git status` in the project is unchanged. A `no-code` result is also done —
there was nothing to map.

## Related

- `/projects-recommendations` — code review across the workspace; refreshes
  each project's graph itself before dispatching its agents
- `/projects-features-suggest` — feature ideation, same graph, same refresh
