---
name: build-loop
description: >-
  Build a project to completion by looping plan → build → test → fix, with one
  herdr agent dispatched per task on the local model and a persistent state file
  so a run survives the session. Takes a PRD from ASST_BBMax/plans/ when one exists. Use when the user
  wants to implement a spec or PRD, build out a project autonomously, work
  through a feature backlog until the tests pass, or keep iterating on failures
  without being asked each time — including phrasings like "build this until it
  works", "implement the whole thing", or "keep going until it's done". Not for
  a single edit or one bug fix.
metadata:
  archetype: workflow
  state_file: .buildloop/state.json
---

# Build Loop

Drives a project from a spec to working, tested, committed code. You plan the
work into verifiable tasks, dispatch one `/herdr-agents` agent per task, run the
tests yourself, and loop fixes back in — up to a per-task attempt cap, then stop
and ask.

**`/herdr-agents` is the runner.** Read its SKILL.md before your first dispatch:
it owns the preconditions, the worktree and pane mechanics, the developer ladder,
hang detection, and the teardown. This file owns the loop around it. Two of its
rules reshape the work here — an agent may never write the tests it is judged
by, and there is no attachment mechanism, so everything the agent must conform
to is pasted into the prompt.

A finished run leaves: every task `done` in the state file, the project's full
test suite passing from a clean tree, one commit per task on the run branch, no
`herdr_*` worktrees or agents left alive, and a report. It does **not** merge to
`main`/`master` or push.

## Before you start

1. **The project must already exist and be scaffolded.** This skill assumes a
   git repo with its `README.md`/`CLAUDE.md`/`.gitignore` in place. If the
   directory is missing or bare, stop and run `/project-bootstrap` first —
   `buildloop.py init` refuses a non-repo and tells you the same thing.
2. **Satisfy `/herdr-agents`' three preconditions**, in its order: this session
   must be inside a Herdr pane (`HERDR_ENV=1`), `herdr integration status` must
   show `opencode` as `current`, and the tree must be clean. Stop at the first
   failure — none has a safe workaround. Outside a Herdr pane there is no runner
   and no build loop; say so and let the user decide whether to relaunch inside
   Herdr or to have Claude write the tasks directly instead.
3. **Work on a `claude_` branch in the project directory, not an
   `EnterWorktree` worktree.** Each task gets its own worktree from Herdr, cut
   from this branch and merged back into it; a second layer of worktree only
   confuses which tree the tests run in. Never build on `main`/`master`.
4. **One repo per run.** A build loop targets a single project. Work spanning
   two projects is two runs.
5. **Budget the wall clock before promising anything.** The measured figure is
   ~900s per task, taken against the pre-upgrade model, so treat it as an order
   of magnitude rather than a number — divide by the configured concurrency and
   round up for the dependency chain. A ten-task plan three at a time is closer
   to an hour than to ten minutes. Say so before starting.

Paths below use `$SKILL_DIR` — the base directory printed when this skill
loads. It is not a real environment variable: substitute the printed path, or
set it inline in the same command, because shell state does not persist between
calls.

## Workflow

- [ ] Step 1: Establish the spec — a PRD path, or a written spec file
- [ ] Step 2: Establish the verification gate — a test command that runs today
- [ ] Step 3: Plan into tasks — `buildloop.py init` accepts the plan
- [ ] Step 4: Loop build → test → fix until `next` reports nothing ready
- [ ] Step 5: Final verification from a clean tree
- [ ] Step 6: Report, then ask before merging or pushing

### Step 1: Establish the spec

Prefer a PRD. Check `~/AI_Projects/ASST_BBMax/plans/` for one matching the
project; a PRD's numbered requirements map straight onto tasks and are what the
planning step leans on hardest.

With no PRD, do not stop — write a short spec yourself from the user's request
into `.buildloop/spec.md` in the target project: what it does, the functional
requirements as a numbered list, and what is explicitly out of scope. Show it to
the user in your next message. If the request is too vague to produce even that,
recommend `/prd-builder` instead of guessing at requirements.

### Step 2: Establish the verification gate

This is the step most likely to be skipped, and skipping it makes the rest of
the loop meaningless. Find the command that proves the build works:

1. Look for an existing runner — `tests/`, `pytest.ini`, a `[tool.pytest]`
   section in `pyproject.toml`, a `test` script in `package.json`, a `Makefile`
   target.
2. Run it *before* building anything, and record what it prints. A suite that
   is already red gives you a baseline; discovering that after a build agent
   runs wastes an attempt on a failure it did not cause.
3. **If there is no runner, create it yourself before planning** — not as a
   task. Most workspace projects have no `tests/` directory, so this is the
   common case. For Python, add `pytest` to the project's dependency manifest,
   create `tests/`, and make the gate `python3 -m pytest -q`.

**You write the tests, not the agents.** `/herdr-agents` forbids an agent
writing the tests it is judged by, and the reason is sharper here than anywhere
else in this workflow: the test *is* the loop's pass/fail signal, so an agent
that authors it is grading its own homework and `pass` becomes meaningless.
Write each task's test before dispatching that task, commit it on the run
branch, and paste it into the prompt. A test you cannot write yet is a task that
is not specified yet.

Pass the result to `init` as `--test-command`. It is stored once and every later
step reads it from the state file.

### Step 3: Plan into tasks

Decompose the spec into tasks that are each **independently verifiable**. Task
sizing rules, in priority order:

- One task covers **one requirement**, and names it in `requirement`.
- A task touches **1–3 source files**, and names the test file that judges it in
  `test_file`. That test is already written and committed by the time the task
  is dispatched.
- **Size it to one module, and state the interface in full.** These are local
  models, and the context budget in `/opencode-agents`' reference was measured
  against the junior rung — the ladder runs to 27B now, so check
  `context_limit` for the level you chose rather than assuming the old figure.
  Either way the window binds before the coding ability does. A task that begins
  "find where…" is the wrong shape — find it yourself and name the file.
- `acceptance` must be checkable by running something, not by reading the code.
  "`parse()` returns `[]` for an empty file; `pytest tests/test_parse.py` passes"
  is acceptance. "Parsing works correctly" is not.
- `depends_on` only for real ordering constraints. Over-declaring serializes a
  run that could have gone wide, and it also decides the order tasks are cut
  from the branch — which is what makes a dependency's code visible to the task
  that needs it.

Write the plan to a JSON file, then hand it over:

```json
[
  {
    "id": "T1",
    "title": "Config loader with defaults",
    "requirement": "PRD 3.1",
    "files": ["src/config.py"],
    "test_file": "tests/test_config.py",
    "depends_on": [],
    "acceptance": "load_config() returns defaults when the file is absent; pytest tests/test_config.py passes"
  },
  {
    "id": "T2",
    "title": "CLI wiring",
    "requirement": "PRD 4",
    "files": ["src/cli.py"],
    "test_file": "tests/test_cli.py",
    "depends_on": ["T1"],
    "acceptance": "python3 -m src.cli --help exits 0 and lists --config"
  }
]
```

```bash
python3 $SKILL_DIR/scripts/buildloop.py init \
  --project ~/AI_Projects/CODE_Thing \
  --tasks plan.json \
  --test-command 'python3 -m pytest -q' \
  --spec ~/AI_Projects/ASST_BBMax/plans/thing-PRD.md
```

`init` validates ids, required fields, and dependency references, and exits 3
rather than overwriting an existing run. It stores a known set of fields and
drops anything else, so a key it has not been taught is silently lost —
`test_file` is stored, and `next` returns it with each task. Show the user the
task list before building: not as an approval gate, but so a wrong decomposition
is caught in the cheapest place.

**Choose one developer level for the whole plan**, from
`/herdr-agents`' ladder — read it with
`python3 ../opencode-agents/scripts/opencode_agents.py levels`, never from
memory. The endpoint keeps one model resident, so alternating levels between
tasks unloads and reloads weights and costs minutes per switch. Most build-loop
tasks are `mid`; a task whose correctness depends on an interface defined
elsewhere pulls the whole batch up to `senior`.

### Step 4: The loop

Repeat until `next` exits 5.

**a. Ask what is runnable.**

```bash
python3 $SKILL_DIR/scripts/buildloop.py next --project <project>
```

Returns a `batch` of tasks whose dependencies are satisfied and whose file lists
do not overlap. Take the batch as given; do not add the `deferred` ids to it.
**Run at most the configured number of agents at once** — read it, never assume:
`python3 $SKILL_DIR/../_lib/agents_config.py --project <project>`. File
disjointness is what makes running several together safe; the config value is
what keeps them from contending.

**b. Dispatch the batch through `/herdr-agents` steps 2–5**, up to the
configured concurrency, marking each task started as it goes. Cut every worktree
from the **run branch**, not from a fixed `HEAD` captured earlier:

```bash
python3 $SKILL_DIR/scripts/buildloop.py start --project <project> --id T1
herdr worktree create --workspace "$HERDR_WORKSPACE_ID" \
  --branch herdr_t1 --base claude_<run> --label t1 --no-focus
herdr agent start t1 --kind opencode --pane <pane-id> --timeout 60000 \
  -- --model <the id the level resolved to>
herdr agent prompt t1 "<the prompt from references/agent-prompt.md>" \
  --wait --timeout 1800000
```

**Create each worktree at dispatch time, never up front**, and merge a
concurrent group before cutting the next. See the Gotchas for why.

**c. Verify against the worktree, then run the test command yourself.** In
order: the diff is non-empty, it touches only the task's files, then the full
suite. Never accept the transcript as the result — see the Gotchas on `idle`.

```bash
git -C <worktree-path> status --porcelain          # did it write anything?
git -C <worktree-path> diff --stat                 # what, exactly?
```

An agent that answered in prose without writing a file is a prompt that read as
a question. Rewrite it as an imperative naming exact files and re-dispatch; that
is a prompt defect, not a task failure, so do not spend a `fail` attempt on it.

**d. Record the outcome.**

```bash
# green
python3 $SKILL_DIR/scripts/buildloop.py pass --project <project> --id T1 --commit <sha>
# red
python3 $SKILL_DIR/scripts/buildloop.py fail --project <project> --id T1 \
  --reason 'test_defaults: AssertionError, expected {} got None'
```

`fail` increments the attempt counter and prints `attempts_remaining`. On the
5th failure it exits **4**, marks the task `blocked`, and tells you to stop.
Honour that — do not retry a blocked task.

**e. On failure, re-prompt the same agent** with the *verbatim* test output,
not a summary — a paraphrased traceback is the commonest cause of a fix solving
the wrong problem. Re-prompt rather than rebuild: the worktree and agent are
still there. A failure inside two seconds having produced nothing is a transient
endpoint blip, not a task failure; re-prompt those without spending an attempt.

**f. Commit from outside the agent, check the contract, then merge.** The agent
never touches git; you control the message and see the diff first.

```bash
git -C <worktree-path> diff --name-only            # contract check, see below
git -C <worktree-path> add -A
git -C <worktree-path> commit -m 'feat: add config loader'
git -C <project> merge --no-ff herdr_t1 -m 'merge T1'
herdr worktree remove --workspace <workspace-id>
python3 $SKILL_DIR/scripts/buildloop.py pass --project <project> --id T1 --commit <sha>
```

**The contract check is not optional.** If the commit touches the test file, or
any file whose contents you pasted into the prompt as the interface, the agent
changed what it was supposed to conform to — the shortest path to "done" for a
model under pressure. Never merge such a commit unread; treat it as a failed
attempt with the reason naming the file it rewrote.

Merging each task before the next is cut is what makes the next worktree contain
this task's code. One commit per task means a later failure never costs you the
earlier work.

### Step 5: Final verification

When `next` exits 5 with `complete: true`, verify from a clean tree rather than
trusting the accumulated per-task greens:

1. `git status` — the tree must be clean; anything uncommitted means a task
   finished without its commit.
2. Run the full test command once more, from the project directory on the run
   branch. This is the tree everything was merged into, and the only one that
   has all of it.
3. `herdr worktree list` and `herdr agent list` must show none of the run's
   worktrees or agents, and no `herdr_*` branch may still hold unmerged work.
4. Re-read the spec and confirm every numbered requirement appears as a task
   `requirement` value. An unmapped requirement is a planning miss — add it as a
   new task and resume the loop rather than declaring the build done.

### Step 6: Report and hand back

```bash
python3 $SKILL_DIR/scripts/buildloop.py report --project <project>
```

Pass the markdown table through as-is. Then **stop and ask** before merging or
pushing — invoking this skill is not authorization for either. When the user
agrees, `/commit2repo` handles the merge and push, and `ExitWorktree` removes
the worktree and its branch.

## Agent prompt template

`herdr agent prompt` types text into the opencode TUI. **There is no attachment
mechanism**, so anything the agent must conform to is in the prompt text — never
a path to a spec, a PRD, or a design document. The agent reads what you paste
and nothing else.

**Read [references/agent-prompt.md](references/agent-prompt.md) before writing
your first task prompt**, and again before a re-prompt after a failure. It holds
both templates and the four properties that decide whether a task comes back
written or comes back as prose.

## Gotchas

- **Most workspace projects have no test suite** — 11 of 37 repos have a
  top-level `tests/` directory (counted 2026-08-24). Assuming a runner exists is
  the default failure of this workflow; Step 2 exists because of it.
- **`idle` is not success.** This is the failure mode that most looks like a
  clean run. If the endpoint refuses fast, opencode prints the error and settles
  straight back to `idle`, so `--wait` returns settled while nothing was
  written. Confirm every task against `git -C <worktree> status --porcelain`
  before believing it ran.
- **A build agent claiming "all tests pass" usually ran one file.** Always run
  the full command yourself in step 4c. This is where cross-task regressions
  surface.
- **An agent under pressure will edit the test instead of the code** — deleting
  an assertion, adding `pytest.mark.skip`, loosening a comparison. Here the test
  is committed on the run branch *before* dispatch, so this shows up as the
  contract check in step 4f finding the test file in the diff. Any commit
  touching the test file is a failed attempt, not a pass.
- **The concurrency is a config value, not a constant.** It was one agent
  before the models were upgraded and is three now, which is why
  `_lib/agents_config.py` resolves it — flag, then `$AGENTS_MAX_PARALLEL`, then
  the project's `.claude/agents-config.json`, then the machine file, then a
  built-in 3. Read it at the start of a run and tell the user the wall clock it
  implies. `next` still excludes overlapping tasks from a batch, which is what
  makes running a batch together safe at any concurrency.
- **A herdr worktree is a snapshot of its base at the moment it is cut**, and
  lives outside the project under `~/.herdr/worktrees/`. Cut one before its
  dependency merged and the agent cannot see that code. Cut, run, merge, remove,
  then cut the next.
- **Run the test command from the project directory on the run branch**, where
  every task has been merged. A single worktree holds only its own task's work,
  so a suite passing there proves less than it looks like.
- **`/projects-git-cleanup` never touches `herdr_*` branches** — it sweeps
  `claude_*` and `worktree-*` only, so an abandoned task's branch is yours.
- **`fail --reason` is stored and shown to the next fix agent.** Put the real
  assertion text in it, not "tests failed".
- **State lives in `.buildloop/` inside the target project** and `init` adds it
  to `.git/info/exclude`, not `.gitignore` — so it never appears as pending work
  in `/projects-git-status` and never dirties a tracked file. Do not add it to
  `.gitignore` instead.
- **`--spec` and `--tasks` resolve relative to your current directory**, not to
  `--project`. Use absolute paths when the two differ.
- **Resuming is `next`, not `init`.** `init` exits 3 on an existing run;
  `--force` discards all task history including attempt counts. Reach for
  `status` first.

## Stop conditions

Stop and ask the user when:

- Any of `/herdr-agents`' preconditions fails — no Herdr pane, no opencode
  integration, or a dirty tree. There is no runner without them.
- An agent reports `blocked`: it is waiting on an approval or a question, and
  answering on the user's behalf is their call.
- A task hits the attempt cap (`fail` exits 4). Report what failed, the last
  error, and what you tried — do not start a sixth attempt or re-plan around it.
- An agent's commit is in contract violation — it edited the test or the
  interface it was told to conform to. Report it; do not merge it to make the
  run look clean.
- The work needs a credential, external service, or paid API not already
  configured in the project.
- A requirement is ambiguous enough that two readings produce different
  software. Note it and keep building the tasks that do not depend on it.
- Anything would merge to `main`/`master`, push to a remote, or delete a branch.
- The spec would require changing another project in the workspace.

## Bundled files

| File | Purpose |
| --- | --- |
| `scripts/buildloop.py` | Task state, dependency scheduling, attempt cap. `--help` for the full interface |
| `references/agent-prompt.md` | The task and re-prompt templates. Read before writing either |
| `evals/evals.json` | Trigger queries and test cases for this skill |

The runner itself is not bundled here: `/herdr-agents` owns the dispatch
mechanics and `/opencode-agents` ships the developer-level ladder and the token
reader both skills read. All three sit side by side in every project's
`.claude/skills/`.

## Done condition

- [ ] `buildloop.py status` reports `complete: true` with zero blocked tasks
- [ ] The full test command passes from the project directory on the run branch,
      run by you, after the last merge
- [ ] `git status` is clean, and `herdr worktree list` / `herdr agent list` show
      none of the run's worktrees or agents
- [ ] Every numbered spec requirement maps to a task
- [ ] The report has been shown and the merge/push question asked
