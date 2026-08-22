---
name: build-loop
description: >-
  Build a project to completion by looping plan → build → test → fix, with one
  subagent dispatched per task and a persistent state file so a run survives the
  session. Takes a PRD from ASST_BBMax/plans/ when one exists. Use when the user
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
work into verifiable tasks, dispatch a subagent per task, run the tests
yourself, and loop fixes back in — up to a per-task attempt cap, then stop and
ask.

A finished run leaves: every task `done` in the state file, the project's full
test suite passing from a clean tree, one commit per task on the worktree
branch, and a report. It does **not** merge or push.

## Before you start

1. **The project must already exist and be scaffolded.** This skill assumes a
   git repo with its `README.md`/`CLAUDE.md`/`.gitignore` in place. If the
   directory is missing or bare, stop and run `/project-bootstrap` first —
   `buildloop.py init` refuses a non-repo and tells you the same thing.
2. **Work in a worktree.** Per the workspace rules, create one with
   `EnterWorktree` named for the work before writing any code. Every command
   below, including the test command, runs from inside the worktree.
3. **One repo per run.** A build loop targets a single project. Work spanning
   two projects is two runs.

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
3. **If there is no runner, creating one is task T1 of the plan** — not an
   afterthought. Most workspace projects have no `tests/` directory, so this is
   the common case, not the exception. For Python, add `pytest` to the project's
   dependency manifest, create `tests/`, and make the gate `python3 -m pytest -q`.

Pass the result to `init` as `--test-command`. It is stored once and every later
step reads it from the state file.

### Step 3: Plan into tasks

Decompose the spec into tasks that are each **independently verifiable**. Task
sizing rules, in priority order:

- One task covers **one requirement**, and names it in `requirement`.
- A task touches **1–3 source files plus its own test file**. Listing files
  accurately matters — the loop derives its parallelism from file disjointness.
- `acceptance` must be checkable by running something, not by reading the code.
  "`parse()` returns `[]` for an empty file; `pytest tests/test_parse.py` passes"
  is acceptance. "Parsing works correctly" is not.
- `depends_on` only for real ordering constraints. Over-declaring dependencies
  serializes the run for nothing.

Write the plan to a JSON file, then hand it over:

```json
[
  {
    "id": "T1",
    "title": "Config loader with defaults",
    "requirement": "PRD 3.1",
    "files": ["src/config.py", "tests/test_config.py"],
    "depends_on": [],
    "acceptance": "load_config() returns defaults when the file is absent; pytest tests/test_config.py passes"
  },
  {
    "id": "T2",
    "title": "CLI wiring",
    "requirement": "PRD 4",
    "files": ["src/cli.py"],
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
rather than overwriting an existing run. Show the user the task list before
building — not as an approval gate, but so a wrong decomposition gets caught in
the cheapest place.

### Step 4: The loop

Repeat until `next` exits 5.

**a. Ask what is runnable.**

```bash
python3 $SKILL_DIR/scripts/buildloop.py next --project <project>
```

Returns a `batch` of tasks whose dependencies are satisfied and whose file lists
do not overlap, so the batch is safe to run in parallel. Take the batch as
given; do not add the `deferred` ids to it.

**b. Mark each task started, then dispatch one subagent per task**, all in a
single message so they run concurrently. Use `subagent_type: "general-purpose"`.
Brief each one with the template below.

**c. Run the test command yourself** when the agents return. Do not accept an
agent's word that its tests pass — an agent typically runs only its own test
file and will not see what it broke elsewhere.

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

**e. On failure, dispatch a fix agent** with the *verbatim* test output, not a
summary. A paraphrased traceback is the single most common cause of a fix agent
solving the wrong problem.

**f. Commit each passing task on its own**, on the worktree branch, with a
conventional-commit message (`feat: add config loader`). Pass the sha to `pass`.
One commit per task means a later failure never costs you the earlier work.

### Step 5: Final verification

When `next` exits 5 with `complete: true`, verify from a clean tree rather than
trusting the accumulated per-task greens:

1. `git status` — the tree must be clean; anything uncommitted means a task
   finished without its commit.
2. Run the full test command once more, from the worktree root.
3. Re-read the spec and confirm every numbered requirement appears as a task
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

## Agent brief template

A subagent shares none of your context. Everything it needs goes in the prompt:

```
Project: <absolute path to the worktree>
Task <id>: <title>
Requirement: <spec section>, quoted in full below.

<the requirement text, verbatim from the spec>

Files you may create or modify — do not touch anything else:
  <files from the task>

Write the implementation AND its tests in the same task.

Acceptance: <acceptance string>
Verify with: <test command> — it must pass before you return.

Conventions: match the surrounding code's style, naming, and error handling.
Read <project>/CLAUDE.md first if it exists.

Do not: commit, run git, install packages not already in the manifest, or edit
files outside the list above.

Return: a JSON object {"status": "done"|"blocked", "files_changed": [...],
"tests_added": [...], "notes": "..."}. This text is a return value, not a
message to a human — no preamble.
```

For a fix agent, keep the same shape and add the failure verbatim:

```
Task <id> failed its verification. Attempt <n> of 5.

Test command: <test command>
Output:
<paste the complete failure output, unedited>

Fix the code so the test passes. Do NOT weaken, skip, xfail, or delete the
failing assertion — if you believe the test itself is wrong, return
{"status": "blocked", "notes": "<why the test is wrong>"} instead of changing it.
```

## Gotchas

- **Most workspace projects have no test suite** — 4 of 34 repos have a `tests/`
  directory. Assuming a runner exists is the default failure of this workflow;
  Step 2 exists because of it.
- **A build agent claiming "all tests pass" usually ran one file.** Always run
  the full command yourself in step 4c. This is where cross-task regressions
  surface.
- **A fix agent under pressure will edit the test instead of the code** —
  deleting an assertion, adding `pytest.mark.skip`, loosening a comparison. The
  brief forbids it explicitly; check the diff of any fix that lands suspiciously
  fast.
- **Parallel agents editing one file clobber each other.** `next` already
  excludes overlapping tasks from a batch. If you hand-expand the batch you lose
  that guarantee, and the loss shows up as a mysterious reverted edit rather
  than a conflict.
- **Run the test command from the worktree, not the repo root.** Both trees hold
  the project; the repo root has none of the new code, so the suite passes there
  for the wrong reason.
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

- A task hits the attempt cap (`fail` exits 4). Report what failed, the last
  error, and what you tried — do not start a sixth attempt or re-plan around it.
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
| `evals/evals.json` | Trigger queries and test cases for this skill |

## Done condition

- [ ] `buildloop.py status` reports `complete: true` with zero blocked tasks
- [ ] The full test command passes from the worktree, run by you, after the last commit
- [ ] `git status` is clean
- [ ] Every numbered spec requirement maps to a task
- [ ] The report has been shown and the merge/push question asked
