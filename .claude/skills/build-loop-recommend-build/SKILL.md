---
name: build-loop-recommend-build
description: >-
  Build a project to passing tests with /build-loop, then repeatedly review it
  with /projects-recommendations and /projects-features-suggest and build what
  they find — a capped number of improvement rounds, three by default, asked at
  the start. The initial build must go green before any review round begins.
  Use when the user wants a project built and then improved on its own, wants
  the review findings implemented rather than just reported, or asks for
  iterative or self-improving build passes — including phrasings like "build it
  then make it better", "build and apply the recommendations", "keep improving
  it for a few rounds", or "build it, review it, fix it, repeat". For a single
  build to green use /build-loop; to review without building use the two review
  skills directly.
metadata:
  archetype: workflow
  state_file: .buildloop/rounds.json
---

# Build Loop → Recommend → Build

An outer loop around `/build-loop`. One initial build to green, then N rounds
of *review the result, build what the review found, verify again*.

```
/build-loop  ──►  green  ──►  ┌─ review (both skills) ─► draft ─► /build-loop ─► green ─┐
                              └──────────────── round 2 … N ◄───────────────────────────┘
```

**Read `/build-loop`'s SKILL.md before running this one.** Everything about
task decomposition, agent prompts, the attempt cap, and the test gate comes from
there and is not repeated here. This skill adds the loop around it, the
review-to-task conversion, and the rules for what must never be auto-built.

**Two different runners, deliberately.** The code-writing agents are
`/herdr-agents` agents on the local model, dispatched by `/build-loop` in steps
1 and 4 — this skill inherits that and changes nothing about it. The two
*review* agents in step 2 stay Claude subagents. See the Gotchas for why that
split is not an oversight.

## Before you start

1. **The project exists and is scaffolded, and `/herdr-agents`' three
   preconditions hold** — a Herdr pane, the opencode integration `current`, a
   clean tree. `/build-loop` checks them at every dispatch; check them once here
   before promising the user N rounds of anything.
2. **Work on a `claude_` branch in the project directory, not a worktree.**
   This is the one place this skill deliberately departs from `/build-loop`,
   and the reason is in the Gotchas: the two reports are this loop's only
   memory, and they live in the project directory.
3. **One repo per run.** The reviews and the state file are per-project.
4. **Budget wall clock, not just tokens.** Each round costs two Claude review
   subagents plus up to `--max` herdr agents, running at the configured
   concurrency — three by default, read with
   `python3 <skills>/_lib/agents_config.py --project <project>`, and a project
   may carry its own number. The per-task figure that exists is ~900s, measured
   against the pre-upgrade model, so it is an order of magnitude rather than a
   number: three rounds of a dozen tasks is still hours. Say that out loud
   before the user commits to it; it decides how many rounds they want.

Paths below use `$SKILL_DIR` — the base directory printed when this skill
loads. It is not a real environment variable: substitute the printed path, or
set it inline in the same command, because shell state does not persist
between calls.

## Workflow

- [ ] Step 0: Ask how many review rounds, then `start`
- [ ] Step 1: Initial build with `/build-loop`, to green — the gate
- [ ] Step 2: Review the built code with both review skills
- [ ] Step 3: `draft` the findings into a task plan, then tighten it
- [ ] Step 4: Integrate — `/build-loop` over that plan, to green
- [ ] Step 5: Close the round; loop to step 2 until the cap or convergence
- [ ] Step 6: Report, then ask before merging or pushing

### Step 0: Ask how many rounds, then start

Ask with **AskUserQuestion** before anything else. Offer 3 (recommended), 1,
and 5; the cap exists because this loop would otherwise run forever, each round
finding smaller things than the last.

```bash
python3 $SKILL_DIR/scripts/rbloop.py start --project <project> --rounds 3
```

`start` rejects more than 10 rounds as a usage error (exit 2), and exits 3
rather than overwriting a run already in progress — reach for `status` first,
since resuming is normal.

### Step 1: The initial build, and the gate

Run `/build-loop` exactly as its own SKILL.md describes: spec, test command,
task plan, loop, final verification from a clean tree.

Then record it:

```bash
python3 $SKILL_DIR/scripts/rbloop.py advance --project <project> \
  --result passed --counts '{"tasks": 8}'
```

`--result failed` exits **4** and moves nothing. That is the gate the user
asked for: a review round never starts on a red suite, because every finding it
produced would be about code that does not work yet. If the initial build
cannot go green, report what failed and stop — do not start reviewing instead.

### Step 2: Review the built code

Run both skills against **this project only**, after the round's commits are in:

```bash
python3 <skills>/projects-recommendations/recommendations.py ignore --root <project>
python3 <skills>/projects-recommendations/recommendations.py brief --root <project> --out <tmp>
python3 <skills>/projects-features-suggest/features.py       brief --root <project> --out <tmp>
```

Then dispatch one **Claude** subagent per brief, as those skills describe —
`subagent_type: general-purpose`, both in one message. Passing the project path
as the root points them at the repository itself rather than at the workspace,
so they scope to the one project and work in a devpod too.

Both skills refresh a graphify code graph first. That is free and offline, and
it is what lets the review agents navigate the code you just built instead of
reading all of it.

### Step 3: Draft the plan, then tighten it

```bash
python3 $SKILL_DIR/scripts/rbloop.py draft --project <project>
```

Reads both reports and writes `.buildloop/round<N>-plan.json` in `/build-loop`'s
task format. It applies the rules that must not be left to judgement:

| Dropped | Why |
|---------|-----|
| Anything under `## Completed`, `## Built`, `## Declined` | Settled. Rebuilding a declined idea is the failure those sections exist to prevent |
| `Low` priority | Noise at this scale. `--include-low` if the user wants it |
| A feature whose `Needs` is not `none` | This workspace never installs a library without asking. `--allow-deps` only *after* the user approves that specific library |
| A foreign report | Not skill output; never build from it |
| Anything past `--max` (default 12) | Reported in `over_cap`, not silently dropped |

**The draft is not ready to build.** Each `acceptance` is the report's `How`
field — prose, not a runnable check — and `/build-loop` requires acceptance that
something proves. For every task: rewrite the acceptance as a runnable check,
**write the test yourself and commit it on the run branch**, name it in
`test_file` (`init` stores that field and `next` hands it back), and declare
`depends_on` where two tasks touch the same file.
`needs_tightening` names the worst offenders; an empty list does not mean the
rest are good.

Writing the tests is the expensive half of a round and it is not delegable: a
herdr agent may never write the test it is judged by, and here the test is also
the only thing standing between a review finding and a regression in code that
already worked.

Show the user the tightened task list and the `skipped` list before building.
The skipped list is where a decision of theirs may be waiting.

### Step 4: Integrate

```bash
python3 <skills>/build-loop/scripts/buildloop.py init --project <project> \
  --tasks <project>/.buildloop/round<N>-plan.json \
  --test-command '<the same command as the initial build>' --force
```

`--force` is required from round 2 on: `init` refuses to overwrite the previous
round's finished run. It discards `state.json` only — `rounds.json` and the
round history are untouched.

Then run `/build-loop`'s step 4 loop unchanged: `next`, dispatch, run the tests
yourself, `pass`/`fail`, one commit per task.

### Step 5: Close the round

```bash
python3 $SKILL_DIR/scripts/rbloop.py advance --project <project> \
  --result passed --counts '{"built": 6}'
```

Exit **5** means the cap is reached and the run is complete. Otherwise the
round advances and step 2 begins again — and this is the part that makes the
loop worth running: the re-run protocol in both review skills carries the
previous round's items forward, verifies which are actually fixed, and moves
those to `## Completed` / `## Built`. That movement is the progress signal.

If the review in step 2 produced nothing actionable — `draft` reports zero
tasks and exits 5 — stop early:

```bash
python3 $SKILL_DIR/scripts/rbloop.py advance --project <project> \
  --result passed --converged
```

Converging before the cap is a good outcome, not a failed run.

### Step 6: Report and hand back

```bash
python3 $SKILL_DIR/scripts/rbloop.py report --project <project>
```

Pass the table through as-is, then add what each round changed, drawn from the
reports' `## Completed` and `## Built` sections. Then **stop and ask** before
merging or pushing — invoking this skill authorizes neither. `/commit2repo`
does both when the user agrees.

## Gotchas

- **Use a `claude_` branch, not a worktree.** `/build-loop` prefers a worktree;
  here it breaks the loop two ways. The reviews write `recommendations.md` and
  `features.md` into the directory they scan, so building in a worktree while
  reviewing the repo root reviews the *pre-round* code and re-raises everything
  you just fixed. Review the worktree instead and the reports die with it at
  `ExitWorktree remove`, taking the raised/completed/declined history — the
  only memory this loop has — with them. If you must use a worktree, review it
  with `--root <worktree path>` and copy both reports back to the repo root
  before removing it. Note that the reports will name the project after the
  worktree directory, not the repo.
- **The review agents stay on Claude, and that is a decision, not an
  oversight.** `/herdr-agents` has no attachment mechanism, so a review brief
  would have to be pasted whole into a TUI prompt, and the agent would then have
  to hold an entire repository in a local model's context — the largest rung on
  the ladder declares 160k, against a repository plus a report format — and emit
  a report whose exact heading and field structure `scan` and `view` parse. The reports
  are also the loop's only memory of what was raised, built, and declined — a
  malformed one does not degrade, it loses history. Code writing is bounded,
  specified, and verified by a test; reviewing is none of those.
- **`/build-loop` merges each concurrent group before cutting the next**, so a
  round's tasks land on the run branch in waves rather than all at once. Do not
  re-cut a whole round's worktrees up front to save time — a herdr worktree is a
  snapshot of its base, and the ones cut early would miss every fix merged after
  them.
- **`herdr_*` branches are invisible to `/projects-git-cleanup`.** If a round
  abandons a task, its branch and worktree are yours to remove; nothing else
  will.
- **Never hand-edit the reports to mark an item done.** It is the next round's
  review that verifies a fix and moves it to `## Completed`, against the actual
  code. An agent marking its own work complete is a self-graded exam, and the
  report is the only record there is.
- **Re-review after the commits land, not before.** A review of an uncommitted
  tree still sees the new code, but `analyzed-commit` will point at the
  previous commit and the next round will read the report as stale.
- **A round that builds nothing is not a failed round.** Convergence is the
  designed ending. Manufacturing tasks to fill the cap produces exactly the
  low-value churn — renaming things, adding docstrings — that `Low` is filtered
  out to avoid.
- **The reports are excluded from git and are not deliverables.** The code and
  its tests are. Do not commit `recommendations.md` or `features.md`; both
  skills' `ignore` step already keeps them out.
- **`--allow-deps` is not a shortcut.** It exists for the case where the user
  has already said yes to a specific library. Passing it because a feature
  looked good is how an unapproved dependency lands in a manifest.
- **Every task in a drafted round is a change to working code.** The initial
  build's tests are the safety net: if the suite is thin, the loop will happily
  refactor behaviour out from under it. Where a round's finding is "no tests
  for X", build that first and let it gate the rest via `depends_on`.

## Stop conditions

Everything `/build-loop` stops for, plus:

- Any `/herdr-agents` precondition fails, or an agent reports `blocked`. There
  is no runner without a Herdr pane, and answering a blocked agent's question is
  the user's call.
- The initial build cannot reach green — `advance` exits 4 and no round starts.
- A round's integration hits `/build-loop`'s attempt cap. Report the blocked
  task; do not carry it into the next round as if it were new.
- A finding would change another project, or needs a credential, service, or
  paid API not already configured.
- A review re-raises an item the previous round marked built. That means the
  fix did not hold and the loop is chasing itself — stop and show the user both
  versions rather than building it a third time.

## Bundled files

| File | Purpose |
| --- | --- |
| `scripts/rbloop.py` | Round state, the phase gate, and the report-to-plan draft. `--help` for the full interface |

## Done condition

- [ ] `rbloop.py status` reports `phase: complete`
- [ ] The full test command passes from a clean tree, run by you, after the
      last round's last commit
- [ ] `git status` is clean and every task committed on the `claude_` branch
- [ ] Both reports exist, and each round's fixes appear under `## Completed` /
      `## Built` rather than still being open
- [ ] The report has been shown and the merge/push question asked
