---
name: projects-recommendations
description: Analyze workspace projects with a stack-matched expert and write a recommendations.md into each, covering fixes, enhancements, features, and optimizations. Also reports back the recommendations already generated across all projects. Use when the user wants code review across projects, project recommendations, or to see what to work on next.
---

# Project Recommendations

Two modes over the same workspace:

- **Generate** (default) — pick projects, analyze each with a subagent framed
  as an expert in that project's actual stack, write `recommendations.md` into
  the project directory.
- **View** (`-view`) — read the `recommendations.md` files that already exist
  and report them back, per project.

A script handles discovery, stack detection, staleness, parsing, and git
exclusion. Do not re-derive any of that by hand.

## Run the script

Paths below use `$SKILL_DIR` — the base directory printed when this skill
loads. It is not a real environment variable: substitute the printed path, or
set it inline in the same command (`SKILL_DIR=... python3 "$SKILL_DIR/..."`),
because shell state does not persist between calls. This is what lets the
commands run from any project, whether they reach this skill in ASST_BBMax or
in the copy that project carries.

```bash
# macOS / Linux
python3 $SKILL_DIR/recommendations.py <command>

# Windows
python $SKILL_DIR/recommendations.py <command>
```

| Command | Purpose |
|---------|---------|
| `scan` | Every repo: stack, size, and whether its report is missing, stale, current, or foreign |
| `brief` | Refresh each project's code graph, then write the complete agent prompt for each to a file |
| `graph` | Build or refresh the code graph only, without writing briefs |
| `view` | Parsed contents of existing reports; add `--full` for raw markdown |
| `stamp` | Backfill missing `**Raised**` dates into existing reports |
| `ignore` | Add `recommendations.md` and `graphify-out/` to `.git/info/exclude` |

All six take `--root DIR` and repeatable `--project NAME` — one call with many
`--project` flags, never one call per project. Output is JSON on stdout;
`{"error": ...}` means stop and show the user the message. Requires Python 3.7+
and git on PATH, nothing outside the standard library. A full scan of ~30 repos
takes about a second — no network.

`scan --format table` prints the picker rows already formatted. Use it for the
selection step: reading the JSON and retyping it as a table costs tokens twice
over, once in and once out.

`brief` also takes `--out DIR` (default: `bbmax-recommendations` under the
system temp directory), `--date YYYY-MM-DD` (default: today, local), and the
graph flags described under **The code graph**: `--no-graph`, `--force-graph`,
`--graph-timeout`.

`stamp` also takes `--date YYYY-MM-DD` (default: each report's own
`analyzed-at`) and `--dry-run`. It is a repair tool for reports written before
per-item dates existed — run it if `view` reports `undated_items`, and always
dry-run first.

Roots and prefixes come from `$SKILL_DIR/../skills_config.json`.

### Availability in other projects

This skill is **copied** into every project by `/project-bootstrap`, together
with `_lib/` and `/graphify-update`, which it imports. `bundled_skills` in
`skills_config.json` lists all three, so
`/project-bootstrap-audit --audit-skills` reports any project whose copy is
missing or has drifted, and `--update-skills` refreshes it.

Copied, never symlinked: most projects open in a devpod, where the workspace
root does not exist and a link into `~/AI_Projects` resolves to nothing. The
same holds in a fresh clone, in CI, and on Windows.

**A copy scopes itself to the repository it sits in.** `skills_config.json` is
a file beside the bundled directories rather than inside one, so it is never
copied, and without it the script falls back to the repository it was copied
into: `scan` reports one project and `scope: project` instead of the whole
workspace. That is the only honest answer in a devpod, where nothing above the
repository exists. For the full sweep, run it from `ASST_BBMax`, which has the
config — or pass `--root ~/AI_Projects` anywhere.

## Report states

| State | Meaning |
|-------|---------|
| `never` | No `recommendations.md` yet |
| `stale` | HEAD moved or the tree is dirty since `analyzed-commit` |
| `current` | Report matches HEAD and the tree is clean |
| `foreign` | A `recommendations.md` exists that this skill did not write |

**`foreign` is a hard stop.** `PRJ_Car_Stereo/recommendations.md`, for one, is
the user's own research document. Never overwrite a foreign report, never
include one in a selection, and never present its contents as skill output.
Mention it exists, and move on unless the user explicitly says to replace it.

## The code graph

Before any agent is dispatched, `brief` builds a graphify code graph for each
selected project and points the agent at it. That is what makes a wide review
affordable: an agent that has to discover an unfamiliar repo by reading it
spends most of its context before it has judged anything, and the biggest repos
— the ones a review is worth most on — are where that goes worst.

The pipeline is deterministic and offline. No API key, no LLM, roughly two
seconds of CPU on a mid-sized repo:

| Step | Command | Why |
|------|---------|-----|
| First build | `graphify extract <path> --code-only` | AST only. Without `--code-only`, graphify sends documents to an LLM backend |
| Later builds | `graphify update <path>` | Re-extracts just what changed, and leaves a richer prior graph intact |
| Report | `graphify cluster-only <path> --no-label --no-viz` | Writes `GRAPH_REPORT.md`. `--no-label` skips LLM community naming; `--no-viz` skips a multi-megabyte `graph.html` nothing here reads |

`--code-only` and `--no-label` are load-bearing. Drop either and the step that
exists to save tokens starts spending them on an API instead.

Each agent is handed `graphify-out/GRAPH_REPORT.md` — the architecture in about
two thousand tokens: god nodes, communities with their member lists, import
cycles, cross-community bridges, isolated nodes — plus the query commands
(`query`, `explain`, `path`, `affected`, `god-nodes`) that return a scoped
subgraph instead of a grep across the tree. The brief tells it to open source
only where the map points, and never to cite the graph as evidence: the graph
is AST-derived, `INFERRED` edges are model guesses, and community names are
placeholders like `Community 7`.

**graphify is optional.** It is a per-machine install outside version control,
so it is absent in a fresh clone and inside a devcontainer. When it is missing,
`brief` returns `"graphify": null`, writes briefs with no map section, and the
review proceeds by reading source exactly as it did before. Report it as a
note, not a failure.

| Flag | When to use it |
|------|----------------|
| `--no-graph` | Skip graphify entirely. An existing graph is still offered to the agent, marked as built from an older commit if HEAD has moved |
| `--force-graph` | Full re-extract rather than an incremental update — for a repo whose code was deleted or moved wholesale, where an incremental pass can leave dead symbols in the graph |
| `--graph-timeout N` | Seconds allowed per project (default 600) |

`brief` returns `graph_totals`, a count by status, and a `graph` object per
project. The statuses are `built`, `updated`, `no-code`, `error` and
`unavailable`. `no-code` is the normal answer for a prose repo: graphify maps
code, so a `KBX_` knowledge base has no call graph to draw and its agent reads
the prose instead.

## Generate mode

### 1. Scan and offer the selection

Run `scan --format table` and show the output as printed — it already sorts
`never` and `stale` first, numbers the rows, and totals by state.

Pre-select every `never` and `stale` repo and say how many that is. Then ask
with **AskUserQuestion**, three options:

1. **Analyze the N stale and never-analyzed** (recommended) — the default set
2. **Analyze all M projects** — everything, including `current`
3. **Let me pick** — user replies with names or row numbers

If they pick option 3, take their list as given: names, numbers, or a mix.
Drop anything `foreign` from whatever set results and say so.

Repos whose only content is data or a couple of config files (`Data`,
`Config`, `Unknown` stacks, near-zero LOC) are usually not worth an agent.
Leave them selected if the user asked for all, but call out that there is
little to review.

### 2. Exclude the report and the graph from git first

Before writing anything, run `ignore` once with a `--project` flag per selected
repo. It excludes both `recommendations.md` and `graphify-out/` by appending to
`.git/info/exclude`, which is local and untracked — unlike editing
`.gitignore`, it leaves no pending change in the repo and keeps
`/projects-git-status` clean. Do this **before** the analysis so neither the
report nor the graph is ever briefly visible as untracked work; the graph in
particular runs to tens of megabytes.

### 3. Build the graphs and write the briefs

Run `brief` once, with one `--project` flag per selected repo. For each one it
refreshes the code graph and then writes a complete agent prompt, returning
where each landed. The graph build is part of this step on purpose — a brief
that points an agent at a code graph must never be able to point it at a stale
one, and a separate step is a step that can be skipped.

Expect a few seconds per project — a couple of minutes for a full-workspace
sweep, against the one second a scan takes. Read `graph_totals` when it returns: `error` and `unavailable` are
worth a line in the final report, since the agents involved reviewed those
projects without a map.

The brief already carries everything an agent needs: the persona matched to the
project's `primary_stack`, the secondary stacks, the absolute path, file count
and LOC, the full 40-character HEAD sha and ISO timestamp for the metadata
stamps, today's date, the scan's signals, the path to `TEMPLATE.md`, the
constraints, and — when a prior report exists — the re-run protocol together
with the list of open items the agent has to account for.

**Do not restate any of that in the Agent prompt, and do not paraphrase the
re-run protocol.** Writing it out per project costs roughly 800 tokens each
against 30-odd repos, and a protocol retyped 30 times drifts. The reports live
outside git, so the file is the only record there is: an item an agent quietly
drops is gone permanently, and that is what the fixed wording protects.

### 4. Dispatch one expert subagent per project

Use the **Agent** tool with `subagent_type: general-purpose`. The prompt is one
line, using the `brief` path from the previous step verbatim — the temp
directory differs by platform, so do not reconstruct it:

```
Follow the review brief at <brief>.
```

Dispatch them in a single message so they run concurrently rather than in
batches — they are independent and each writes to a different directory, so
there is nothing to serialize. `brief` returns its results largest-repo-first;
keep that order, because a long job started last is what makes a run finish
late.

### 5. Report

Use the two-section structure described under **Report structure** below.

**Actionable** — a table of project, stack, items by priority, and the top
recommendation from each. On a re-run, add a **Resolved** column and a line
stating the net movement, items closed versus items newly raised, since that
trend is the whole point of keeping the history.

**Non-Actionable** — where the files were written and that they are excluded
from git, plus any project the agents found little to review in. Name any
project whose graph failed to build or that was reviewed without one, since
that review is the weaker of the two kinds. Offer `-view` for the full
contents.

## Report structure

Both modes report in exactly two top-level sections: **Actionable** first,
then **Non-Actionable**. Every finding goes in one or the other — no third
section, nothing unplaced.

The test is whether it is work the user could pick up. Open recommendations
are actionable; the history of what has already been fixed is not.

Separate the two sections with **two horizontal rules**, so the break is
unmissable when the report is skimmed in a terminal. Emit them exactly like
this — blank lines around each rule, and a blank line between them, or the
renderer collapses the pair into one rule and reads the first as a heading
underline:

```markdown
...last line of the Actionable section.

---

---

## Non-Actionable
```

## View mode

Run `view`, then report:

### Actionable

- **Open items, per project** — a table of project, stack, when it was
  analyzed, items by priority, and completed count. Then, for each, its
  summary line and its High-priority items with the `Where` path **and the
  `Raised` date**.

  **Every itemized recommendation shown to the user carries its date.** In a
  table that is a `Raised` column; in a list it goes with the item. An item
  raised months ago and still open is a different fact from one raised today,
  and the reader cannot tell them apart without the date. `view` returns
  `raised` on each item, and `undated_items` names any that lack one — if
  that count is non-zero, say so and offer `stamp`.

  Age is worth calling out directly: when an item's `Raised` date is well
  behind the others, flag it as carried-over rather than letting it read as
  new.
- **Cross-project themes** — patterns repeating across projects (no tests
  anywhere, the same dependency pinned three different ways, a security
  pattern repeated). These are the findings a per-project review cannot see,
  so do not skip this.
- **Stale reports** — reports carry an `analyzed-commit`. If `scan` says a
  project is now `stale`, say so next to it; the reader should know which
  advice predates the current code. Offer a regenerate.
- **Not yet analyzed** — a count, names on request. Offer generate mode.

### Non-Actionable

- **Progress** — once any project has a `## Completed` section, report what
  has been resolved: totals closed, which projects are moving, and any High
  item that has been open across multiple analysis dates. Skip this entirely
  while every report is still on its first run.
- **Foreign reports** — named, with the note that they are not skill output
  and will never be overwritten.
- **Totals** — projects with a report, open items, counts by priority, and
  items completed to date. A summary line, last.

`-view <project>` scopes to one project and prints its full report; use
`--full --project NAME` to get the raw markdown rather than re-reading the
file with Read.

## Usage

| Invocation | Effect |
|-----------|--------|
| `/projects-recommendations` | Scan, offer the picker, generate |
| `/projects-recommendations CODE_Youtube_Rater` | Generate for one project, no picker |
| `/projects-recommendations -all` | Generate for every repo, no picker |
| `/projects-recommendations -view` | Report every existing report |
| `/projects-recommendations -view CODE_MCP_Google` | Full report for one project |

## Notes

- Repos are found by the presence of `.git`, so directories outside the naming
  convention are included. Directories with no repo are not — run
  `/projects-git-status` to find those.
- The script inventories files via `git ls-files`, so `.gitignore` is honored
  and virtualenvs, `node_modules`, and build output never reach an agent.
- LOC is a size signal for scoping the review, not a quality measure. Marker
  files (`pyproject.toml`, `Dockerfile`, `ansible.cfg`) outrank extension
  counts when identifying the stack, but only where the marker is evidence:
  a `.devcontainer/` is scaffolded into every project here, so it ranks last
  and leads only a repo with nothing else in it. `Docs` is held off the top
  spot wherever a repo has real code, since markdown lines are cheap and a
  well-documented project easily carries more prose than code.
- The persona is a pure function of `primary_stack` and lives in the script,
  not in this file — `brief` writes it into each prompt. Adding a stack means
  adding a `PERSONAS` entry beside the `EXT_STACKS` and `MARKER_STACKS` that
  produce it; unlisted languages fall back to a generic senior-engineer frame.
- Regenerating rewrites the file, but the re-run protocol carries prior items
  forward — open ones with their original dates, resolved ones into
  `## Completed`. The file accumulates rather than resetting, which is what
  makes raised-versus-fixed answerable. Since the reports are outside git,
  that in-file history is the only record there is: an agent that drops an
  item loses it permanently.
- The graph lives in `<project>/graphify-out/` rather than a temp directory,
  which is what makes the second run cheap: `graphify update` re-extracts only
  what changed, and the agent can run `graphify query` from the project
  directory with no `--graph` flag. It is excluded from git by step 2, and
  deleting it costs nothing but a rebuild.
- Use the `graph` command to rebuild a graph outside a review — after a large
  refactor, or with `--force` when a deletion left symbols behind that an
  incremental update kept. A review does not need it; `brief` already refreshes
  every graph it uses.
- The graph maps code, not prose. A `Docs`-primary repo comes back `no-code` or
  close to it, and its review rests on reading the documents as it always has.
- `## Completed` grows without bound by design. If a report gets unwieldy,
  trimming the oldest resolved entries is a deliberate decision for the user
  to make, not something a re-run should do on its own.

## Related

- `/projects-git-status` — repo health: uncommitted work, sync, stale branches
- `/todo-list` — this project's own `TODOs.md`
