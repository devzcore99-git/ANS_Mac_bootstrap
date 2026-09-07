# Roles, Developer Levels, and Escalation for Build Loop

This file is the contract for the build loop's roles. Read it before
dispatching any role. `/herdr-agents` owns the mechanics of starting, stopping,
and checking on a herdr agent; this file owns who does what, at which level, and
what happens when work stalls.

## Naming convention

Every herdr agent is named by role and task using `(ROLE)-(TaskID)`:

| Role | Agent id / label | Branch (safe prefix) |
| --- | --- | --- |
| Project-Sponsor | `Project-Sponsor` | `herdr_Project-Sponsor` |
| Architect (initial) | `Architect` | `herdr_Architect` |
| Architect (remediating T4) | `Architect-T4` | `herdr_Architect-T4` |
| Coder (task T1) | `Coder-T1` | `herdr_Coder-T1` |
| Coder (task T2) | `Coder-T2` | `herdr_Coder-T2` |
| Tester/QA | `Tester` | `herdr_Tester` |

The **agent id and label** carry the role name; the **branch** keeps the `herdr_`
prefix so `/projects-git-cleanup` (which sweeps `claude_*` and `worktree-*`
only) can never delete an in-flight run branch. The Coder's level is not part of
the name — it is the `--agent` value passed at start.

## Role → model → budget slot

Each role runs on a fixed seat. These come from the machine config
(`~/.config/opencode/model-levels.json`, read via
`python3 ../opencode-agents/scripts/opencode_agents.py levels`) — never from
memory, and never repointed ad hoc.

| Role | `--agent` | Model | Effort | Budget slot | Role in the loop |
| --- | --- | --- | --- | --- | --- |
| **Manager** (the hub) | `manager` | `ham51/qwen3.6-35b-a3b-manager` | thinking | 3 | Orchestrates, routes escalations, approves merges. Not dispatched as a task agent. |
| **Project-Sponsor** | `senior` | `ham51/qwen3.8-27b` | xhigh | 2 | Represents business needs; scopes the work, owns the *what/why*. |
| **Architect** | `architect` | `ham51/qwen3.8-27b` | xhigh | 2 | Designs architecture + specs; assigns per-task levels; resolves escalations. |
| **Coder — senior** | `senior` | `ham51/qwen3.8-27b` | xhigh | 2 | Cross-module / interface-critical work. |
| **Coder — mid** | `mid` | `ham51/qwen3.6-35b-a3b` | thinking | 3 | One module against a clear spec (the default). |
| **Coder — junior** | `junior` | `ham51/qwen3.5-9b` | — | 2 | Mechanical, fully-specified edits. |
| **Tester/QA** | `tester` | `ham51/qwen3.6-35b-a3b` | thinking | 3 | Runs the suite, reports failures verbatim, escalates at two. |

Two notes on this table:

- The **Project-Sponsor** has no dedicated ladder agent, so it borrows the
  `senior` seat (27B, xhigh) — the strongest general-reasoning model, suited to
  eliciting and articulating business requirements. It is a distinct *role* from
  the Architect even though both sit on 27B.
- The **Coder's level** is chosen *per task* by the Architect from the
  senior / mid / junior rows above; the `--agent` value at dispatch is whatever
  the Architect assigned that task.

## Concurrency budget

The endpoint has a fixed number of slots per model family, recorded in
[../config/buildloop.json](../config/buildloop.json) under `concurrency_budget`.
The Manager keeps the number of **live** agents on each model at or below its
slot count at every moment.

| Model family | Slots | Roles that draw from it |
| --- | --- | --- |
| `qwen3.6-35b-a3b` | 3 | Manager, Coder-mid, Tester/QA |
| `qwen3.8-27b` | 2 | Project-Sponsor, Architect, Coder-senior |
| `qwen3.5-9b` | 2 | Coder-junior |

Rules the Manager enforces before each dispatch:

1. Map the task to a model (the Architect's level → the table above).
2. Count the agents already running on that model.
3. Start the task only if that model still has a free slot; otherwise hold it
   until a slot frees up.
4. Different model families run independently — a `mid` task (3-slot) and a
   `senior` task (2-slot) may be in flight together even though each is at its
   own family's cap.

## Agent framework

[../config/buildloop.json](../config/buildloop.json) also names `agent_framework`
— which runner dispatches the agents. The Manager reads it before Step 4 and
routes accordingly:

| Value | Runner | Notes |
| --- | --- | --- |
| `herdr` (default) | `/herdr-agents` | Live panes, worktrees, watchable. The default. |
| `opencode` | `/opencode-agents` | Headless, supports `--sandbox` confinement. |

Only the runner changes. The roles, briefings, concurrency budget, and
escalation are identical across both frameworks.

## The five roles

### Manager (you) — the hub

The Manager is the session that started the loop. It is **very token-conscious**
and makes every effort to save tokens, so it delegates nearly all work. It does
not scope, design, code, or test. It:

1. Reads [../config/buildloop.json](../config/buildloop.json) for
   `agent_framework` (which runner) and `concurrency_budget` (per-model slots).
2. Dispatches the Project-Sponsor and forwards the scoped result on.
3. Dispatches the Architect and forwards the architecture and level assignments
   on.
4. Dispatches the Coders per the Architect's level assignments, staying within
   the per-model concurrency budget.
5. Routes Coder questions to the Architect (design) or answers them itself
   (mechanical).
6. Dispatches the Tester/QA and relays failures to the owning Coder.
7. Owns both escalation decisions (escalate at two, break at five).
8. Commits from outside the agent, checks the contract, merges, and approves.

The Manager is the only hub: information flows through it between every pair of
roles. It reads diffs and records outcomes, but it does not write code, write
the scope, design the architecture, or run the test suite — those are the four
other seats.

### Project-Sponsor

The Project-Sponsor represents the business needs and concerns behind the
technical solution. It owns *what* the project must do and *why* — the value,
the users, the constraints, and the decisions that are business calls rather
than engineering ones. It runs once, at the start, and its output is the scoped
spec the rest of the loop builds from.

- **With a PRD**: reads it and populates the missing questions it needs — any
  requirement left vague, any decision the PRD does not make, any business
  constraint it cannot infer.
- **Without a PRD**: asks the user every question it needs before moving
  forward — what the project does, the functional requirements as a numbered
  list, and what is explicitly out of scope. It does not guess.

It returns the completed scope to the Manager. It does not design the
architecture, decompose into tasks, or write code — representing the business
needs and establishing scope is its entire seat.

### Architect

The Architect devises the architecture and assigns the work. It runs after the
Project-Sponsor, with the scoped project as input.

**What it produces:**

1. **`ARCHITECTURE.md`** — module structure, boundaries, inter-module contracts,
   key design decisions, and file layout.
2. **`tasks.json`** — a task decomposition with exact file targets, inline
   interface contracts, the dependency graph, each task's test specification,
   and a **level recommendation** per task (senior / mid / junior).

The key output is the **level assignment**: which portions a senior Coder takes,
which a mid Coder, which a junior Coder. The Manager delegates on this directly.

The Architect also resolves any escalation the Tester/QA raises: it diagnoses
the root cause and returns a remediation the Manager relays to the Coder.

**When it runs:**

- Once, after the Project-Sponsor, to produce the initial architecture and
  decomposition.
- On any escalation (an item stuck after two back-and-forths).
- For a final review once the Tester/QA reports all green, before the run is
  declared complete.

**The architect's level criteria:**

| Level | Assign when |
|-------|-------------|
| **senior** | Touches multiple modules, must maintain external interfaces, involves non-obvious design tradeoffs, or a wrong impl is expensive to fix |
| **mid** | One module against a clear spec, self-contained, straightforward logic |
| **junior** | Fully specified mechanical work — scaffolding, renaming, docstrings, pattern copying |

When in doubt, go up one rung. Under-assigning is cheaper than a wrong
implementation that cascades into other tasks.

**Running the architect:**

```bash
herdr worktree create --workspace "$HERDR_WORKSPACE_ID" \
  --branch herdr_Architect --base HEAD --label Architect --no-focus
herdr agent start Architect --kind opencode --pane <pane-id> --timeout 60000 \
  -- --auto --agent architect
herdr agent prompt Architect "<scoped project text>\n\nProduce ARCHITECTURE.md and tasks.json. Assign each task a senior/mid/junior level. Touch no other file." \
  --wait --timeout 2400000
```

The architect runs the **same model as senior** (27B dense, xhigh effort)
because architecture requires the same depth of codebase understanding as
senior-level implementation — just a different output: design over code.

**The architect is a task agent, not a replacement for the Manager.** The
Manager still orchestrates, routes questions, and approves merges.

### Coders (senior / mid / junior)

Coders implement the tasks the Architect assigned. Each is named `Coder-T<id>`
and started at the level the Architect recommended for that task.

- **May ask questions as they arise.** The Manager routes a design question to
  the Architect and a mechanical question to the scoped spec; the Manager
  relays the answer back. A Coder never blocks on a question it can escalate.
- **Never write the test it is judged by.** The test is specified by the
  Architect (in `tasks.json`) and committed before dispatch. A Coder that edits
  the test is a contract violation, not a pass.
- **If a test appears broken, escalate rather than modify it.** If a Coder
  believes a test contains an error or bug that prevents completion — it hangs,
  times out, or fails in a way that suggests a flaw in the test itself — the
  Coder states the problem and stops. The Architect reviews the test, advises on
  the correct direction, and the Manager relays that guidance back to the Coder.
  The Coder never modifies, skips, or weakens a test to make it pass.
- **Never edit the interface it conforms to.** The contract check in Step 4g
  catches this.

**Choosing one level per batch.** The endpoint keeps one model resident, so
alternating levels unloads and reloads weights between agents — minutes of wall
clock, not seconds. Group the Architect's assignments by level and run each
level's batch together. Efforts within one level are free to vary — the
`-dispatch` twins share a server-side model, so `senior` and `senior-low` never
trade weights.

**Get the ladder from the config, not from memory:**

```bash
python3 ../opencode-agents/scripts/opencode_agents.py levels
```

### Tester/QA

The Tester/QA verifies coder work. It runs after a Coder (or batch) completes
and before the Architect does a final review.

**What it does:**

1. **Runs the test suite** and captures pass/fail/error counts.
2. **Reports every failure verbatim** — which test failed, what error was
   raised, which production file it targets.
3. **Sends failures back to the owning Coder** (`Coder-T<id>`). That is one
   back-and-forth.
4. **Escalates to the Architect** when an item is stuck after two
   back-and-forths.

It does **not** write code and does **not** write the tests it runs — those were
specified by the Architect. Its seat is to verify and to route failures.

The tester runs the same model as mid (35B MoE at thinking effort) — it needs
the reasoning to analyze failure patterns but does not need the senior model
because it does not write code.

```bash
herdr worktree create --workspace "$HERDR_WORKSPACE_ID" \
  --branch herdr_Tester --base claude_<run> --label Tester --no-focus
herdr agent start Tester --kind opencode --pane <pane-id> --timeout 60000 \
  -- --auto --agent tester
herdr agent prompt Tester "Run the test suite for <Tid>. Report pass/fail with verbatim failures. Touch no other file." \
  --wait --timeout 2400000
```

**The tester's template lives at** `opencode-agents/assets/tester-agent-template.md`
— copy it into the project's `.opencode/agent/` and commit it before running,
or the tester agent will not be found.

## Developer level selection

The endpoint serves more than one model, and they are **developers of different
seniority**. Decide which rung the work deserves before starting the agent.

| Level | Reach for it when |
|-------|-------------------|
| senior | correctness depends on an interface defined elsewhere; call sites must stay consistent; a wrong design costs more than the extra latency |
| mid | one module against a spec you already wrote out — clear, self-contained, nothing to infer |
| junior | mechanical and fully specified — rename, extract, add a docstring, scaffold a file whose shape the prompt dictates |

**Choosing reasoning effort.** Each rung has an effort dial — opencode calls it
a **variant**. Take the default unless the task argues otherwise. There is no
`--variant` flag on `herdr agent start`; the effort comes from the agent
definition instead.

| Want | Start with |
|------|------------|
| the rung's default effort | `-- --agent senior` (or the appropriate level) |
| a specific effort | `-- --agent <the name under `agents`>` |
| the junior rung | `-- --agent junior` — no variants declared |

Read `../opencode-agents/references/model-levels.md` before changing any of
this. Names must match `[a-z][a-z0-9_-]{0,31}` and be unique among live agents.

## Escalation

Two thresholds keep a stuck item from burning wall clock. The Manager owns both
decisions.

| Threshold | Trigger | Action |
|-----------|---------|--------|
| **Two back-and-forths** | The Tester/QA has sent the same item to the Coder twice and it still fails | Tester/QA **escalates to the Architect** (`Architect-T<id>`); the Architect resolves the root cause; the Manager relays the resolution to the Coder; the Coder re-implements |
| **Five loops** | The same item has looped five times total — counting Coder fixes and Architect remediations | **Break the loop.** `buildloop.py fail` marks the task `blocked` on the fifth failure and exits 4; stop and ask the user |

A "back-and-forth" is one Tester→Coder→Tester round on the same item. A "loop"
is a full cycle of Coder fix (or Architect remediation) followed by a Tester
re-run. The five-loop cap is enforced by `buildloop.py fail`, which increments
the attempt counter, prints `attempts_remaining`, marks the task `blocked`, and
exits 4 on the fifth failure.

## How work moves through the loop

The loop has decision points that determine the next step based on what the
Tester/QA reports.

### After a Coder completes

| What you see | Next step |
|---|---|
| No changes (`no-changes`) — first time | Rewrite the prompt (it read as a question) and re-dispatch the same Coder |
| No changes (`no-changes`) — second time | **Back to Architect** — the prompt is not working; ask the Architect to rewrite the task |
| Contract violation | **Never merge.** The Architect decides if the Coder legitimately needed to change the contract; the Manager re-dispatches with a tighter prompt |
| Changes look complete | **To Tester/QA** — run the suite against the merged tree |

### After the Tester/QA completes

| What you see | Next step |
|---|---|
| Tester reports failures, first back-and-forth | **Back to the Coder** — send the verbatim failure; Coder fixes; Tester re-runs |
| Tester reports failures, second back-and-forth | **Escalate to the Architect** — `Architect-T<id>` resolves the root cause; Manager relays to the Coder; Coder re-implements |
| Tester reports all pass | **To the Architect for final review** — pass the pass count, the Coder diffs, and the failure history. The Architect approves (run complete) or finds additional changes (back to Coders, then Tester again) |

### Decision rules

1. **A Coder finished and produced code** → Tester/QA runs the suite.
2. **Tester found failures** → back to the Coder, up to two back-and-forths.
3. **Two back-and-forths, still failing** → Architect resolves; Manager relays
   to the Coder; Coder re-implements; Tester re-runs.
4. **Five loops on the same item** → break the loop; `buildloop.py fail` marks
   it `blocked`; stop and ask the user.
5. **Tester reports all pass** → Architect final review; on approval the run is
   complete.

### Architect approval gate

**A run is not complete until the Architect has approved.** The Manager does not
judge whether the code is right or troubleshoot failures — it dispatches the
Project-Sponsor, the Architect, the Coders, and the Tester/QA, routes their output, owns
the escalation calls, and approves merging.