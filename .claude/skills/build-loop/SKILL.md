---
name: build-loop
version: 1.0.0
description: >-
  Build a project to completion by looping scope → design → build → test → fix,
  with a role-based methodology: a token-conscious Manager orchestrates a
  Project-Sponsor, an Architect, level-assigned Coders, and a Tester/QA — each a herdr
  agent named (ROLE)-(TaskID). A persistent state file lets a run survive the
  session. Escalates to the Architect after two back-and-forths and breaks the
  loop after five. Takes its spec from the target project's own PRD.md when one
  exists, falling back to ASST_BBMax/plans/. Use when the user wants to
  implement a spec or PRD, build out a project autonomously, work through a
  feature backlog until the tests pass, or keep iterating on failures without
  being asked each time — including phrasings like "build this until it works",
  "implement the whole thing", or "keep going until it's done". Not for a single
  edit or one bug fix.
metadata:
  archetype: workflow
  state_file: .buildloop/state.json
---

# Build Loop

**The purpose of this skill is to make software without a human in the loop.**
The Manager, the Project-Sponsor, the Architect, the Coders, and the Tester/QA
are a self-sufficient team: they run until the build is done and the tests pass,
and do not pause to ask the person for a decision they can make themselves.

Two principles, and their two named exceptions:

- **Escalate gating items to the agent who owns the decision, not to the human.**
  A blocked agent hands the item to the role whose seat it is (a Coder stuck on a
  design question goes to the Architect); the Manager routes it and does not sit on it.
- **The receiving agent has the autonomy to decide and keep the loop turning** —
  choose the lower-risk option, note the assumption in the spec or the diff, proceed.
  It stops only at an **authorization boundary** (merge to `main`, push, spend money,
  delete a branch) or when the escalation threshold in [Escalation](#escalation) is exhausted.
- **Two seats break the autonomy rule, on purpose — they gather the user's answer rather
  than guess:** the **Project-Sponsor** (Step 1), and the **initial architecture pass**
  (Step 3). Each is scoped to its own step below.

The agent that started the build-loop skill is the Manager unless otherwise specified.

**The Manager** — this session — is very token-conscious and delegates nearly everything:
it orchestrates, forwards information between roles, makes escalation calls, and approves
merges. It does not scope, design, code, or test. Those are herdr agents, one per role per
task: **Project-Sponsor** (what/why), **Architect** (architecture, specs, per-task level),
**Infrastructure** (environment setup, scaffolding, dependencies),
**Coder** (implement, senior/mid/junior), **Tester/QA** (run tests, report failures).
Information flows through the Manager as the only hub.

**The Manager also records the run's metrics.** On start, it captures the wall-clock time
and project name as the baseline. Throughout the run, it tracks the number of agents used,
their types, how long each ran, and how many tokens they consumed. It reports these metrics
at the end of the build as part of the final report, giving a clear picture of the project's
cost and duration.

**The Manager allows ample time for agents to complete their work.** If an agent is slow,
that is acceptable — quality is more important than speed. The Manager's concern is not
speed but whether the agent is stuck: it watches for stalls, idle states, or repeated
failures, and escalates when the agent has exhausted its attempts or cannot make progress.

**The Manager tracks pending escalations and outstanding questions.** When one agent
escalates to another — a Coder to the Architect on a design call, the Tester/QA raising
a failure — the Manager records which agent is waiting and who owes the answer. It ensures
the receiving agent gets the question promptly, and relays the answer back to the waiting
agent as soon as it arrives. If the Manager notices an escalation that has gone unanswered
for an unreasonably long time, it follows up with the receiving agent to unblock the team.

**The Manager sends a progress report to the user approximately every 5 minutes.** The
report includes: overall project status (which tasks are complete, in progress, pending),
percent complete (tasks done / total tasks), and an agents usage summary — which agents are
currently running, how long each has been active, and total tokens consumed so far. This
keeps the user informed of build progress without requiring them to monitor individual agents.

**The Manager never performs another agent's job.** It orchestrates, escalates, and reports —
it does not write code, design, scope, or test. The Manager knows very little about coding
and should rarely if ever attempt to perform a coding task. When a problem arises that no
agent role can resolve, the Manager informs the user rather than stepping into a role.

**Before dispatching any task, the Manager verifies the required agents exist.** The coder
levels (senior, mid, junior) may show `agent=None` / `model=None` in `model-levels.json` —
this means the agents are not configured. The Manager must verify what opencode agents actually
exist before starting any dispatch. Run `python3 ../opencode-agents/scripts/opencode_agents.py
levels` to check. If the required `--agent` values (senior, mid, junior, tester, architect)
are not configured, the build cannot proceed — stop and inform the user. Never guess agent
names or fall back to a default model.

Every herdr agent is named by role and task, `(ROLE)-(TaskID)` — e.g. `Project-Sponsor`,
`Architect`, `SnrCoder-T1`, `MidCoder-T1`, `JrCoder-T1`, `Tester`, or `Architect-T4` when
the Architect remediates T4. The Coder's level (senior / mid / junior) is part of the name
and determines the `--agent` value at start.
The name is the agent id and worktree label; the branch keeps the safe `herdr_` prefix
(see [Gotchas](#gotchas)).

Read [references/roles-and-levels.md](references/roles-and-levels.md) before dispatching
any role: it holds each role's contract, the developer ladder, the reasoning-effort variants,
the escalation thresholds, and the loop's decision tables. **`/herdr-agents` is the runner** and owns the preconditions, worktree and
pane mechanics, hang detection, and teardown — read its SKILL.md before your first dispatch.
This file owns the loop around it.

A finished run leaves: every task `done` in the state file, the full test suite passing from
a clean tree, one commit per task on the run branch, no run worktrees or agents alive, and
a report. It does **not** merge to `main`/`master` or push.

## Before you start

1. **The project must already exist and be scaffolded** — a git repo with
   `README.md`/`CLAUDE.md`/`.gitignore`. If missing or bare, run `/project-bootstrap`
   first; `buildloop.py init` refuses a non-repo and says so.
2. **Satisfy `/herdr-agents`' three preconditions, in its order:** inside a Herdr pane
   (`HERDR_ENV=1`), `herdr integration status` shows `opencode` as `current`, and the tree
   is clean. Stop at the first failure — outside a Herdr pane there is no runner and no loop;
   say so and let the user decide whether to relaunch inside Herdr or have Claude write the
   tasks directly.
3. **Work on a `claude_` branch in the project directory, not an `EnterWorktree` worktree.**
   Each task gets its own Herdr worktree cut from this branch and merged back into it; a
   second worktree layer only confuses which tree the tests run in. Never build on
   `main`/`master`.
4. **One repo per run.** Work spanning two projects is two runs.
5. **Budget the wall clock before promising anything.** The measured figure is ~900s per
   task (pre-upgrade model — an order of magnitude, not a number). Divide by the concurrency
   the budget allows (config) and round up for the dependency chain. A ten-task plan, three
   at a time, is closer to an hour than ten minutes. Say so before starting.
6. **Verify required opencode agents exist before starting.** Run `python3 ../opencode-agents/scripts/opencode_agents.py levels`
   and confirm `senior`, `mid`, `junior`, `tester`, and `architect` all show a configured
   `--agent` value (not `None`). The coder levels (senior/mid/junior) may show
   `agent=None` / `model=None` in `model-levels.json` — this means they are not configured
   and dispatch will fail. If any required agent is missing, stop and inform the user.

Paths below use `$SKILL_DIR` — the base directory printed when this skill loads. It is not a
real environment variable: substitute the printed path, or set it inline in the same command,
because shell state does not persist between calls.

## Workflow

- [ ] Step 1: Project-Sponsor identifies the scope — fills a PRD's gaps or gathers the user's answers
- [ ] Step 2: Establish the verification gate — a test command that runs today
- [ ] Step 3: Architect devises the architecture — framework, specs, and per-task level assignment
- [ ] Step 4: Loop build → test → fix until `next` reports nothing ready
- [ ] Step 5: Final verification from a clean tree
- [ ] Step 6: Report, then ask before merging or pushing

### Step 1: Project-Sponsor identifies the scope

Dispatch a **Project-Sponsor** (`Project-Sponsor`) to establish what is to be coded. It
represents the business needs behind the technical solution — it owns *what* the project must
do and *why*, not *how*. The Manager does not write the scope; it only forwards the result.

**Primary autonomy exception:** the Project-Sponsor does not resolve a business question
against the requirements and guess — it **asks the user** and records the answer, so the
Architect and Coders never build on an assumed business requirement.

**With a PRD** — prefer one; its numbered requirements map straight onto tasks. Look in two
places, **in this order**: (1) the target project itself, which wins — `PRD.md` at the root,
then `docs/PRD.md`, then any `*-PRD.md`; (2) `~/AI_Projects/ASST_BBMax/plans/`, for a file
matching the project name. The project's copy travels (devpod, fresh clone, cloud run);
`plans/` only exists where ASST_BBMax is reachable. **Never merge the two** — if both exist,
read the project's and ignore the other. A `plans/` file may be a pointer to a PRD moved into
its project; if so, follow it.

The Project-Sponsor reads the PRD and **populates the missing questions it needs** — any
vague requirement, any decision the PRD does not make, any interface it cannot infer — and
returns the completed scope to the Manager, which records it in `.buildloop/spec.md`.

**Without a PRD**, it **asks the user every question it needs before moving forward** — what
the project does, the functional requirements as a numbered list, and what is explicitly out of
scope — and returns them; the Manager records them in `.buildloop/spec.md` and shows them to
the user. It does not guess. If the request is too vague to scope at all, recommend
`/prd-builder` instead of guessing at requirements.

### Step 2: Establish the verification gate

This is the step most likely to be skipped, and skipping it makes the rest of the loop
meaningless. Find the command that proves the build works:

1. Look for an existing runner — `tests/`, `pytest.ini`, a `[tool.pytest]` section in
   `pyproject.toml`, a `test` script in `package.json`, a `Makefile` target.
2. Run it *before* building anything and record what it prints. A suite already red gives a
   baseline; discovering that after a Coder runs wastes an attempt on a failure it did not cause.
3. **If there is no runner, create it before planning — not as a task.** Most workspace projects
   have no `tests/` directory, so this is the common case. For Python: add `pytest` to the
   dependency manifest, create `tests/`, and make the gate `python3 -m pytest -q`.

**The Coder never writes the test it is judged by.** The test *is* the loop's pass/fail signal,
so a Coder that authors it grades its own homework and `pass` becomes meaningless. The
**Architect specifies each task's test** (Step 3) **and writes it** — it is authored and committed
on the run branch before the task is dispatched. The **Tester/QA runs it** (Step 4). A test that
cannot be written yet is a task that is not specified yet.

Pass the result to `init` as `--test-command`; it is stored once and every later step reads it
from the state file.

**Dispatch Infrastructure before the Architect and Coders if the environment needs setup.**
If the project requires dependency installation, tooling configuration, directory scaffolding,
or any other environment preparation, the Manager dispatches the **Infrastructure** agent
(`Infrastructure`) first. The Manager refers all scaffolding and infrastructure build/setup
to this agent — never attempting to set up the environment itself. The Infrastructure agent
ensures the environment is correct, follows all guidelines, and maintains proper security.

### Step 3: Architect devises the architecture

Dispatch an **Architect** (`Architect`) with the scoped project from Step 1. The Architect:
reviews the PRD or scoped input; devises the architecture and framework; defines the technical
specifications including each task's test specification from Step 2; **assigns each piece a
level** — which portions a senior, a mid, a junior Coder takes (the key output the Manager
delegates on); and produces `ARCHITECTURE.md` and `tasks.json` — the decomposition with exact
file targets, inline interface contracts, the dependency graph, and a level per task.

**The Architect designs for parallelism.** A team of Coders and a Tester/QA will execute
the build, not a single developer. Breaking the work into several independent coding tasks
that can be assigned concurrently is far more efficient than a single large task. The
Architect should decompose the project into as many parallelizable tasks as practical,
respecting real dependencies, so that multiple Coders can work simultaneously and the
Tester can run the suite frequently.

**Second autonomy exception, scoped to this initial pass:** a design decision that depends on a
business or usage fact only the user holds (which users, what scale, which integrations) — the
Architect raises it, the Manager carries it to the user, and the answer is folded in before the
architecture is finalized. Once `ARCHITECTURE.md` and `tasks.json` are set, the Architect
remediates autonomously under the normal rule and does not reopen business questions.

Task sizing rules the Architect applies, in priority order:

- One task covers **one requirement**, and names it in `requirement`.
- A task touches **1–3 source files**, and names the test file that judges it in `test_file` —
  already written and committed by dispatch time.
- **Size it to one module, and state the interface in full.** These are local models and the
  context window binds before the coding ability does; a task that begins "find where…" is the
  wrong shape — name the file.
- `acceptance` must be checkable by running something, not by reading the code.
- `depends_on` only for real ordering constraints. Over-declaring serializes a run that could
  have gone wide, and it also decides the order tasks are cut — which is what makes a dependency's
  code visible to the task that needs it.

The Manager takes `tasks.json` and hands it to `init`:

```bash
python3 $SKILL_DIR/scripts/buildloop.py init \
  --project ~/AI_Projects/CODE_Thing \
  --tasks tasks.json \
  --test-command 'python3 -m pytest -q' \
  --spec .buildloop/spec.md
```

`init` validates ids, required fields, and dependency references, and exits 3 rather than
overwriting an existing run. It stores a known set of fields and drops anything else. Show the
user the task list and the Architect's level assignments before building — not as an approval
gate, but so a wrong decomposition is caught in the cheapest place.

**Get the ladder from the config, not from memory:**

```bash
python3 ../opencode-agents/scripts/opencode_agents.py levels
```

The endpoint keeps one model resident, so a batch at two levels thrashes it between them — group
the Architect's assignments by level and run each level's batch together.

### Step 4: The loop

Repeat until `next` exits 5.

**Dispatch through the configured framework, with the configured auto-approve.** Read
`config/buildloop.json` before dispatching. `agent_framework` picks the runner: `herdr` (default,
via `/herdr-agents`) or `opencode` (headless, via `/opencode-agents`) — roles, briefings, budget,
and escalation are unchanged, only the runner differs. `auto_approve` decides permission prompts:
when **true**, add `--auto` to every `herdr agent start` so the agent auto-approves commands
without prompting; when **false**, omit it and the agent asks before each command. (`--auto`
auto-approves everything except an explicit `permission: deny`, which still blocks — see
`/opencode-agents`.) The command examples below assume `auto_approve: true`; drop `--auto` from
each `herdr agent start` when it is `false`.

**No attachment mechanism.** The runner types text into the TUI, so anything an agent must conform
to — the interface, the test, the contract — must be pasted inline in the prompt; never point an
agent at a spec, PRD, or design document.

Read [references/agent-prompt.md](references/agent-prompt.md) before writing your first task prompt,
and again before any re-prompt after a failure — it holds both templates and the four properties that
decide whether a task comes back written or comes back as prose.

**a. Ask what is runnable.** The Manager asks the state file, never the Architect, for the next work:

```bash
python3 $SKILL_DIR/scripts/buildloop.py next --project <project>
```

Returns a `batch` of tasks whose dependencies are satisfied and whose file lists do not overlap.
Take the batch as given; do not add the `deferred` ids to it.

**Respect the concurrency budget.** It is per model, in `config/buildloop.json`. Before starting a
task, map its level to a model (per [references/roles-and-levels.md](references/roles-and-levels.md))
and count the agents already running on that model; start it only if that model still has a free
slot. Different models run independently, so a `mid` and a `senior` task may be in flight together.
File disjointness keeps the worktrees safe; the per-model budget keeps the endpoint from contending.

**b. Dispatch the Coders.** Cut one worktree per task and start a Coder named
`(SnrCoder|MidCoder|JrCoder)-<Tid>` at the level the Architect assigned.

**The pane ID comes from the worktree create response, not generated.**
`herdr worktree create` returns JSON; read `.result.root_pane.pane_id` from
it and use that value verbatim in the `--pane` flag. Never invent a pane ID.

```bash
python3 $SKILL_DIR/scripts/buildloop.py start --project <project> --id T1
herdr worktree create --workspace "$HERDR_WORKSPACE_ID" \
  --branch herdr_<LEVEL>CODEr-T1 --base claude_<run> --label <LEVEL>CODEr-T1 --no-focus
# Parse the response: pane_id=$(echo "$WORKTREE_CREATE_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['result']['root_pane']['pane_id'])")
herdr agent start <LEVEL>CODEr-T1 --kind opencode --pane <pane-id> --timeout 60000 \
  -- --auto --agent <the level the Architect assigned>
herdr agent prompt <LEVEL>CODEr-T1 "<briefing from references/roles/coder.md> + <task body from references/agent-prompt.md>" \
  --wait --timeout 1800000
```

**c. Coder questions.** A design question goes to the Architect; a mechanical question the Manager
answers from the scoped spec; the Manager relays the answer back. The Coder never blocks on a
question it can escalate, and the Manager never answers a design question itself — that is the
Architect's seat.

**d. Tester/QA verifies.** Dispatch a **Tester/QA** (`Tester`) to run the suite against the merged
tree. It reports pass/fail per task with the *verbatim* failure text. It does not write code and
does not write the tests it runs — those were specified in Step 2/3.

**The pane ID comes from the worktree create response, not generated.**
`herdr worktree create` returns JSON; read `.result.root_pane.pane_id` from
it and use that value verbatim in the `--pane` flag. Never invent a pane ID.

```bash
herdr worktree create --workspace "$HERDR_WORKSPACE_ID" \
  --branch herdr_Tester --base claude_<run> --label Tester --no-focus
# Parse the response: pane_id=$(echo "$WORKTREE_CREATE_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['result']['root_pane']['pane_id'])")
herdr agent start Tester --kind opencode --pane <pane-id> --timeout 60000 \
  -- --auto --agent tester
herdr agent prompt Tester "Run the test suite for <Tid>. Report pass/fail with verbatim failures. Touch no other file." \
  --wait --timeout 2400000
```

Never accept the Coder's transcript as the result — see the Gotchas on `idle`. An agent that
answered in prose without writing a file is a prompt that read as a question; rewrite it as an
imperative naming exact files and re-dispatch.

**e. On failure, back to the Coder.** The Tester/QA sends the failure back to the owning Coder
(`SnrCoder-T1`, `MidCoder-T1`, or `JrCoder-T1`); that is one back-and-forth. The Coder fixes
against the *verbatim* failure and the Tester/QA re-runs. A failure inside two seconds having
produced nothing is a transient endpoint blip, not a task failure; re-prompt without spending a
back-and-forth.

**f. Escalate, then break.** After the second back-and-forth on the same item, the Tester/QA
escalates to the Architect; after the fifth loop, break. See [Escalation](#escalation).

**g. Commit from outside the agent, check the contract, then merge.** The agent never touches git;
the Manager controls the message and sees the diff first.

```bash
git -C <worktree-path> diff --name-only            # contract check
git -C <worktree-path> add -A
git -C <worktree-path> commit -m 'feat: add config loader'
git -C <project> merge --no-ff herdr_<LEVEL>CODEr-T1 -m 'merge <LEVEL>CODEr-T1'
herdr worktree remove --workspace <workspace-id>
python3 $SKILL_DIR/scripts/buildloop.py pass --project <project> --id T1 --commit <sha>
```

The commit message and branch name use the actual agent name (`herdr_SnrCoder-T1`,
`herdr_MidCoder-T1`, `herdr_JrCoder-T1`), not a generic `herdr_Coder-<id>`.

**The contract check is not optional.** If the commit touches the test file, or any file whose
contents were pasted into the prompt as the interface, the Coder changed what it was supposed to
conform to. Never merge such a commit unread; treat it as a failed attempt naming the file it
rewrote. Merging each task before the next is cut is what makes the next worktree contain this
task's code; one commit per task means a later failure never costs the earlier work.

### Escalation

Two thresholds keep a stuck item from burning wall clock. The Manager owns both decisions.

- **More than two back-and-forths** between the Tester/QA and the Coder on the same item → the
  Tester/QA **escalates to the Architect** (`Architect-T<id>`). The Architect resolves the root
  cause, the Manager relays the resolution to the Coder, and the Coder re-implements. This is a new
  Architect task, not a repeat of the Coder's.
- **More than five loops** on the same item — counting Coder fixes and Architect remediations — →
  **break the loop.** `buildloop.py fail` marks the task `blocked` on the fifth failure and exits 4;
  honour that, stop, and ask the user. Do not start a sixth attempt or re-plan around it.

`fail` increments the attempt counter and prints `attempts_remaining`. Record every outcome through
the state file so a resume knows where it is:

```bash
python3 $SKILL_DIR/scripts/buildloop.py fail --project <project> --id T1 \
  --reason 'test_defaults: AssertionError, expected {} got None'
```

### Step 5: Final verification

When `next` exits 5 with `complete: true`, verify from a clean tree rather than trusting the
accumulated per-task greens:

1. `git status` — the tree must be clean; anything uncommitted means a task finished without its commit.
2. Run the full test command once more, from the project directory on the run branch — the tree
   everything was merged into, the only one that has all of it.
3. `herdr worktree list` and `herdr agent list` must show none of the run's worktrees or agents, and
   no run branch may still hold unmerged work.
4. Re-read the scoped spec and confirm every numbered requirement appears as a task `requirement`
   value. An unmapped requirement is a planning miss — add it as a new task and resume the loop
   rather than declaring the build done.

### Step 6: Report and hand back

```bash
python3 $SKILL_DIR/scripts/buildloop.py report --project <project>
```

Pass the markdown table through as-is. Then **stop and ask** before merging or pushing — invoking
this skill is not authorization for either. When the user agrees, `/commit2repo` handles the merge
and push, and `ExitWorktree` removes the worktree and its branch.

## Compaction

The only durable record of a run is `.buildloop/state.json` (progress, attempts, commits),
`.buildloop/spec.md` (the scoped requirements), and this file — **the conversation is not the
record.** If the harness compacts the session mid-run, do not rely on memory: before the next
dispatch, re-read this SKILL.md, run `buildloop.py status`, and re-read `.buildloop/spec.md`, then
resume with `next` (never `init`). Because progress lives in the state file, a compaction costs
nothing — the loop picks up exactly where it left off.

## Config

[config/buildloop.json](config/buildloop.json) holds three settings the Manager reads before
dispatching:

- `agent_framework` — `herdr` (default) or `opencode`; which runner dispatches the agents.
- `concurrency_budget` — the per-model slot counts (how many agents may run at once on each model family).
- `auto_approve` — boolean; when `true`, add `--auto` to each `herdr agent start` so agents auto-approve
  commands instead of prompting for permission.

## Gotchas

- **Most workspace projects have no test suite** — 11 of 37 repos have a top-level `tests/`
  (counted 2026-08-24). Assuming a runner exists is the default failure; Step 2 exists because of it.
- **`idle` is not success.** If the endpoint refuses fast, opencode prints the error and settles
  straight back to `idle`, so `--wait` returns settled while nothing was written. Confirm every task
  against `git -C <worktree> status --porcelain` before believing it ran.
- **A Coder claiming "all tests pass" usually ran one file.** The Tester/QA runs the full command in
  Step 4d — this is where cross-task regressions surface.
- **A Coder under pressure will edit the test instead of the code** — deleting an assertion, adding
  `pytest.mark.skip`, loosening a comparison. The test is committed before dispatch, so this shows up
  as the Step 4g contract check finding the test file in the diff. Any commit touching the test file
  is a failed attempt, not a pass.
- **The concurrency budget is per model, in config** (`concurrency_budget`): 3 slots for
  `qwen3.6-35b-a3b`, 2 for `qwen3.8-27b`, 2 for `qwen3.5-9b`. The Manager counts live agents per model
  before each dispatch and stays within each model's cap; different models run independently. The
  shared `_lib/agents_config.py` is a separate, single-number mechanism for other skills — the
  build-loop per-model budget governs here.
- **A herdr worktree is a snapshot of its base at the moment it is cut**, and lives outside the
  project under `~/.herdr/worktrees/`. Cut one before its dependency merged and the agent cannot see
  that code. Cut, run, merge, remove, then cut the next.
- **Run the test command from the project directory on the run branch**, where every task has been
  merged. A single worktree holds only its own task's work, so a suite passing there proves less than
  it looks like.
- **Agent branches keep the `herdr_` prefix** (`herdr_Coder-T1`, `herdr_Architect`, `herdr_Tester`)
  even though the agent id and label are named by role. `/projects-git-cleanup` sweeps `claude_*` and
  `worktree-*` only, never `herdr_*`, so an in-flight run branch can never be deleted out from under a
  run. Do not rename a branch to bare `Coder-T1`.
- **`fail --reason` is stored and shown to the next fix agent.** Put the real assertion text in it,
  not "tests failed".
- **State lives in `.buildloop/` inside the target project**, and `init` adds it to
  `.git/info/exclude`, not `.gitignore` — so it never appears as pending work in
  `/projects-git-status` and never dirties a tracked file. Do not add it to `.gitignore` instead.
- **`--spec` and `--tasks` resolve relative to your current directory, not to `--project`.** Use
  absolute paths when the two differ.
- **Resuming is `next`, not `init`.** `init` exits 3 on an existing run; `--force` discards all task
  history including attempt counts. Reach for `status` first.

## Stop conditions

The loop runs without a human in the loop, so most blocking items are **escalated to the agent who
owns the decision**, which then decides and keeps the loop turning. Stop and ask the human only at an
**authorization boundary** or when the loop is genuinely **exhausted**.

**Escalate to the owning agent and keep going** (do not ask the human):

- A Coder is gated on a **design question** → the Architect decides and the Coder proceeds.
- A requirement reads two ways → the Architect picks the reading the spec supports, documents it, and
  keeps building the tasks that do not depend on it.
- A Coder's commit is in contract violation → the Architect decides whether the change was legitimate;
  re-dispatch with a tighter prompt; do not merge it unread.

**Exceptions to the autonomy rule — ask the user** (these two seats gather answers, they do not guess):

- The **Project-Sponsor** (Step 1) hits a business need, constraint, or a call that is the user's to
  make → it asks the user and records the answer.
- The **initial architecture pass** (Step 3) reaches a design decision that depends on a business or
  usage fact only the user holds → the Architect raises it, the Manager carries it to the user, and the
  answer is folded in before the architecture is finalized.

**Stop and ask the human — authorization boundaries:**

- Anything would merge to `main`/`master`, push to a remote, or delete a branch. Invoking this skill
  authorizes none of these.
- The work needs a credential, external service, or paid API not already configured in the project.
- The scoped spec would require changing another project in the workspace.

**Stop and ask the human — the loop is exhausted:**

- Any of `/herdr-agents`' preconditions fails — no Herdr pane, no opencode integration, or a dirty tree.
- An agent reports `blocked` on an item that no role can resolve.
- A task hits the attempt cap (`fail` exits 4) — the loop is broken at five. Report what failed, the
  last error, and what was tried; do not start a sixth attempt or re-plan around it.

## Bundled files

| File | Purpose |
| --- | --- |
| `config/buildloop.json` | Run config: `agent_framework` (default `herdr`), the per-model `concurrency_budget`, and `auto_approve` (add `--auto` to agent starts). Read before dispatching |
| `scripts/buildloop.py` | Task state, dependency scheduling, attempt cap. `--help` for the full interface |
| `references/agent-prompt.md` | The task and re-prompt templates. Read before writing either |
| `references/roles-and-levels.md` | The six roles, role→model→budget mapping, developer ladder, escalation thresholds, and loop decision tables. Read before dispatching any role |
| `references/roles/project-sponsor.md` | Project-Sponsor briefing — paste at the top of its prompt |
| `references/roles/architect.md` | Architect briefing (initial pass + remediation) |
| `references/roles/infrastructure.md` | Infrastructure briefing — paste at the top of its prompt |
| `references/roles/coder.md` | Coder briefing — substitute the Architect's level |
| `references/roles/tester.md` | Tester/QA briefing |
| `references/roles/manager.md` | Manager seat (this session; no briefing to send) |
| `evals/evals.json` | Trigger queries and test cases for this skill |

The runner itself is not bundled here: `/herdr-agents` (the default `agent_framework`) owns the dispatch
mechanics and `/opencode-agents` is the `opencode` alternative — both sit side by side in every
project's `.claude/skills/`.

## Done condition

- [ ] `buildloop.py status` reports `complete: true` with zero blocked tasks
- [ ] The full test command passes from the project directory on the run branch, run by the Tester/QA, after the last merge
- [ ] `git status` is clean, and `herdr worktree list` / `herdr agent list` show none of the run's worktrees or agents
- [ ] Every numbered spec requirement maps to a task
- [ ] No item looped more than five times without the loop being broken and the user asked
- [ ] The report has been shown and the merge/push question asked
