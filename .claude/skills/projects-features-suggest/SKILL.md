---
name: projects-features-suggest
description: >-
  Propose new features for workspace projects with a stack-matched expert and write a
  features.md into each, covering capabilities the project does not have yet — core,
  adjacent, cross-project integration, and usability. Tracks every idea across runs as
  still wanted, built, or declined, so a re-run never re-proposes something already
  turned down. Runs on one project or batched across the whole workspace. Use when the
  user wants feature ideas, asks what to build next, asks what a project is missing or
  could grow into, wants a roadmap, or wants to see the ideas already proposed. For
  defects, cleanups, and performance work use projects-recommendations instead.
---

# Project Feature Suggestions

Two modes over the same workspace:

- **Suggest** (default) — pick projects, ideate on each with a subagent framed
  as a product-minded expert in that project's actual stack, write
  `features.md` into the project directory.
- **View** (`-view`) — read the `features.md` files that already exist and
  report them back, per project.

This skill proposes; it never implements. It is the forward-looking half of a
pair — `/projects-recommendations` reviews the code that exists, this one
suggests code that does not. Keep the split: a defect found here belongs in
that report, not this one.

A script handles discovery, stack detection, staleness, parsing, and git
exclusion. Do not re-derive any of that by hand.

## Run the script

Paths below use `$SKILL_DIR` — the base directory printed when this skill
loads. It is not a real environment variable: substitute the printed path, or
set it inline in the same command (`SKILL_DIR=... python3 "$SKILL_DIR/..."`),
because shell state does not persist between calls.

```bash
# macOS / Linux
python3 $SKILL_DIR/features.py <command>

# Windows
python $SKILL_DIR/features.py <command>
```

| Command | Purpose |
|---------|---------|
| `scan` | Every repo: stack, size, and whether its report is missing, stale, current, or foreign |
| `brief` | Refresh each project's code graph, then write the complete agent prompt for each to a file |
| `graph` | Build or refresh the code graph only, without writing briefs |
| `view` | Parsed contents of existing reports; add `--full` for raw markdown |
| `decline` | Move an idea into `## Declined` with a reason |
| `ignore` | Add `features.md` and `graphify-out/` to `.git/info/exclude` |

All of them take `--root DIR`, and all but `decline` take repeatable
`--project NAME` — one call with many `--project` flags, never one call per
project. Output is JSON on stdout; `{"error": ...}` means stop and show the
user the message. Requires Python 3.7+ and git on PATH, nothing outside the
standard library. A full scan of ~38 repos takes about a second — no network.

`scan --format table` prints the picker rows already formatted. Use it for the
selection step: reading the JSON and retyping it as a table costs tokens twice
over, once in and once out.

`brief` also takes `--out DIR` (default: `bbmax-features` under the system
temp directory), `--date YYYY-MM-DD` (default: today, local), and the graph
flags described under **The code graph**: `--no-graph`, `--force-graph`,
`--graph-timeout`.

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
| `never` | No `features.md` yet |
| `stale` | HEAD moved or the tree is dirty since `analyzed-commit` |
| `current` | Report matches HEAD and the tree is clean |
| `foreign` | A `features.md` exists that this skill did not write |

**`foreign` is a hard stop.** Never overwrite a foreign report, never include
one in a selection, and never present its contents as skill output. Mention it
exists, and move on unless the user explicitly says to replace it.

## The code graph

Before any agent is dispatched, `brief` builds a graphify code graph for each
selected project and points the agent at it. Ideation needs the same map a
review does, for a different reason: the fastest way to waste a proposal is to
propose something the project already does, and an agent that has only skimmed
a repo cannot tell.

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
`brief` returns `"graphify": null`, writes briefs with no map section, and
ideation proceeds by reading source exactly as it did before. Report it as a
note, not a failure.

| Flag | When to use it |
|------|----------------|
| `--no-graph` | Skip graphify entirely. An existing graph is still offered to the agent, marked as built from an older commit if HEAD has moved |
| `--force-graph` | Full re-extract rather than an incremental update — for a repo whose code was deleted or moved wholesale, where an incremental pass can leave dead symbols in the graph |
| `--graph-timeout N` | Seconds allowed per project (default 600) |

`brief` returns `graph_totals`, a count by status, and a `graph` object per
project. The statuses are `built`, `updated`, `no-code`, `error` and
`unavailable`. `no-code` is the normal answer for a `KBX_` or `PRJ_` repo:
graphify maps code, and those hold prose, so their agents work from the
documents as before.

## Suggest mode

### 1. Scan and offer the selection

Run `scan --format table` and show the output as printed — it already sorts
`never` and `stale` first, numbers the rows, and totals by state.

If the user named a project, skip the picker entirely and go to step 2 with
just that one.

Otherwise pre-select every `never` and `stale` repo, say how many that is, and
ask with **AskUserQuestion**, three options:

1. **Ideate on the N stale and never-analyzed** (recommended) — the default set
2. **Ideate on all M projects** — everything, including `current`
3. **Let me pick** — user replies with names or row numbers

If they pick option 3, take their list as given: names, numbers, or a mix.
Drop anything `foreign` from whatever set results and say so.

### 2. Exclude the report and the graph from git first

Run `ignore` once with a `--project` flag per selected repo. It excludes both
`features.md` and `graphify-out/` by appending to `.git/info/exclude`, which is
local and untracked — unlike editing `.gitignore`, it leaves no pending change
in the repo and keeps `/projects-git-status` clean. Do this **before** the
analysis so neither the report nor the graph is ever briefly visible as
untracked work; the graph in particular runs to tens of megabytes.

### 3. Build the graphs and write the briefs

Run `brief` once, with one `--project` flag per selected repo. For each one it
refreshes the code graph and then writes a complete agent prompt, returning
where each landed. The graph build is part of this step on purpose — a brief
that points an agent at a code graph must never be able to point it at a stale
one, and a separate step is a step that can be skipped.

Expect a few seconds per project — a couple of minutes for a full-workspace
sweep, against the one second a scan takes. Read `graph_totals` when it returns: `error` and `unavailable` are
worth a line in the final report, since the agents involved ideated on those
projects without a map.

The brief already carries everything an agent needs: the persona matched to the
project's `primary_stack`, the absolute path, size, HEAD sha and timestamp for
the metadata stamps, today's date, the roster of sibling projects for
integration ideas, the path to `TEMPLATE.md`, the constraints, and — when a
prior report exists — the carry-forward rules plus the lists of open, built,
and declined ideas.

**Do not restate any of that in the Agent prompt, and do not paraphrase the
carry-forward rules.** Writing them out per project costs roughly 800 tokens
each across 30-odd repos, and a paraphrase that loses the "never re-propose a
declined idea" clause turns every run into a repeat of a conversation the user
already had.

### 4. Dispatch one expert subagent per project

Use the **Agent** tool with `subagent_type: general-purpose`. The prompt is one
line, using the `brief` path from the previous step verbatim — the temp
directory differs by platform, so do not reconstruct it:

```
Follow the feature brief at <brief>.
```

Dispatch them in a single message so they run concurrently rather than in
batches — they are independent and each writes to a different directory, so
there is nothing to serialize. `brief` returns its results largest-repo-first;
keep that order, because a long job started last is what makes a run finish
late.

### 5. Report

Use the two-section structure described under **Report structure** below.

**Actionable** — a table of project, stack, ideas by priority, and the top idea
from each. Call out every idea whose `Needs` is not `none`, grouped by the
dependency it wants: those are the ones that cannot be started without a
decision from the user. On a re-run, add a **Built** column and state the net
movement — ideas shipped versus ideas newly raised.

**Non-Actionable** — where the files were written and that they are excluded
from git, plus any project the agents found little to build on. Name any
project whose graph failed to build or that was ideated on without one, since
those proposals are the likeliest to duplicate something already built. Offer
`-view` for the full contents.

## Declining an idea

When the user turns an idea down, record it:

```bash
python3 $SKILL_DIR/features.py decline --project CODE_Youtube_Rater \
  --title "plugin architecture" --reason "overkill for a 400-line tool"
```

`--title` matches a substring of the heading and must hit exactly one open
idea; the script names the open ideas if it misses. Always offer this when the
user reacts negatively to a specific suggestion — an idea rejected in
conversation and not recorded comes straight back on the next run, because the
file is the only memory this skill has.

## Report structure

Both modes report in exactly two top-level sections: **Actionable** first,
then **Non-Actionable**. Every finding goes in one or the other — no third
section, nothing unplaced.

The test is whether it is work the user could pick up. Open ideas are
actionable; the record of what has already shipped or been turned down is not.

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

- **Open ideas, per project** — a table of project, stack, when it was
  analyzed, ideas by priority, and built/declined counts. Then, for each, its
  summary line and its High-priority ideas with the `Where` path **and the
  `Raised` date**.

  **Every idea shown to the user carries its date.** An idea raised months ago
  and still unbuilt is a different fact from one raised today, and the reader
  cannot tell them apart without the date. Where an idea's `Raised` date is
  well behind the others, flag it as long-standing rather than letting it read
  as new.
- **Ideas needing a new dependency** — `view` returns `needs_new_dependency`
  per project and a total. These are blocked on a decision this workspace
  requires the user to make, so list them together with the library each one
  wants. Do not bury them in the per-project tables.
- **Cross-project themes** — patterns repeating across projects: the same
  integration proposed from both ends, three projects each wanting their own
  scheduler, a capability that would be better built once. These are the
  findings a per-project pass cannot see, so do not skip this.
- **Stale reports** — reports carry an `analyzed-commit`. If `scan` says a
  project is now `stale`, say so next to it; the reader should know which ideas
  predate the current code. Offer a regenerate.
- **Not yet analyzed** — a count, names on request. Offer suggest mode.

### Non-Actionable

- **Shipped** — once any project has a `## Built` section, report what has
  landed: totals, which projects are moving, and any High idea open across
  multiple analysis dates. Skip this entirely while every report is on its
  first run.
- **Declined** — a count per project, names on request. Worth surfacing so the
  user can see what the skill has been told to stop suggesting.
- **Foreign reports** — named, with the note that they are not skill output
  and will never be overwritten.
- **Totals** — projects with a report, open ideas, counts by priority, ideas
  built and declined to date. A summary line, last.

`-view <project>` scopes to one project and prints its full report; use
`--full --project NAME` to get the raw markdown rather than re-reading the
file with Read.

## Usage

| Invocation | Effect |
|-----------|--------|
| `/projects-features-suggest` | Scan, offer the picker, ideate |
| `/projects-features-suggest CODE_Youtube_Rater` | Ideate on one project, no picker |
| `/projects-features-suggest -all` | Ideate on every repo, no picker |
| `/projects-features-suggest -view` | Report every existing report |
| `/projects-features-suggest -view CODE_MCP_Google` | Full report for one project |

## Gotchas

- **A declined idea must never be re-proposed.** It is the failure this file
  format exists to prevent, and it is invisible until the user notices the
  same rejected suggestion for the third month running. The brief states the
  rule and lists the declined titles; if a returned report re-raises one
  anyway, say so and re-run that project rather than passing it on.
- **An agent may not decline on its own.** Declining is the user's judgement.
  An agent may only retire an idea that has become impossible or meaningless
  — the module was deleted, the project changed direction — and must say which
  in the `Reason`.
- **`Needs` is load-bearing, not decoration.** This workspace never installs a
  library without asking first, so an idea that assumes a new dependency
  cannot be started until the user agrees. An agent that leaves `Needs` off,
  or writes `none` for an idea that plainly requires a new package, produces a
  proposal the reader cannot act on.
- **Ideas already in `TODOs.md` are not new ideas.** Several projects keep a
  TODO list, and re-proposing its contents as fresh insight makes the whole
  report look unread. The brief tells the agent to read it first; a concrete
  design for an existing TODO is fine, as long as it says that is what it is.
- **The map is for checking, not just orienting.** The graph lists what the
  project already contains, so an idea that duplicates an existing module is a
  failure with the evidence sitting right there in `GRAPH_REPORT.md`. If a
  returned report proposes something the graph plainly shows, re-run that
  project rather than passing it on.
- **`Docs`-primary repos are knowledge bases, not software.** `KBX_*` and most
  `PRJ_*` repos have no code to add features to. The persona handles this, but
  if a report for one comes back proposing a CLI or a database, it is wrong —
  those projects want content and structure.
- The reports live outside git, so `features.md` is the only record there is.
  A re-run that drops an idea loses it permanently, which is why the
  carry-forward rules are stated verbatim in the brief rather than
  paraphrased per project.
- `## Built` and `## Declined` grow without bound by design. If a report gets
  unwieldy, trimming the oldest entries is a deliberate decision for the user
  to make, not something a re-run should do on its own.

## Notes

- Repos are found by the presence of `.git`, so directories outside the naming
  convention are included. `DBX_` data directories are skipped by
  configuration — there is nothing to propose for a SQLite file.
- The script inventories files via `git ls-files`, so `.gitignore` is honored
  and virtualenvs, `node_modules`, and build output never reach an agent.
- Stack detection and the picker table are shared with
  `/projects-recommendations` through `.claude/skills/_lib/projectscan.py`, and
  the graphify pipeline through `.claude/skills/_lib/codegraph.py`. A fix to
  how projects are typed, or to how the graph is built, benefits both skills;
  the personas, the brief, and the report shape are this skill's own.
- The graph lives in `<project>/graphify-out/` rather than a temp directory,
  which is what makes the second run cheap: `graphify update` re-extracts only
  what changed, and the agent can run `graphify query` from the project
  directory with no `--graph` flag. It is excluded from git by step 2, and
  deleting it costs nothing but a rebuild. Both skills share the one graph per
  project, so whichever runs second usually finds it already current.
- Use the `graph` command to rebuild a graph outside a run — after a large
  refactor, or with `--force` when a deletion left symbols behind that an
  incremental update kept. Ideation does not need it; `brief` already refreshes
  every graph it uses.
- Every brief carries the full workspace roster — name, stack, and size per
  repo — so integration ideas can name a specific sibling. It is one line per
  project, which is cheap next to what it unlocks.

## Related

- `/projects-recommendations` — the same shape, for defects and cleanups
- `/prd-builder` — turn an idea from here into a buildable spec
- `/todo-list` — this project's own `TODOs.md`
