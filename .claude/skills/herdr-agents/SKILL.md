---
name: herdr-agents
description: >-
  Run opencode subagents inside Herdr panes — one git worktree and workspace per
  task — then watch their live lifecycle state, review the diff, commit, merge,
  and tear the worktrees down. Use when the user wants to farm work out through
  Herdr, spin up agents in herdr panes, watch or take over an agent while it
  works, or run a batch of independent tasks on the local model with a terminal
  to look at — including phrasings like "use herdr for this", "start some herdr
  agents", "have herdr run these tasks", or "I want to watch them work". Requires
  Claude Code to be running inside a Herdr pane. Not for a single edit Claude
  should make itself, and not for configuring Herdr.
metadata:
  runtime: herdr-cli
  requires: herdr 0.8+, opencode CLI, git
---

# Herdr agents

Dispatch tasks to `opencode` subagents that Herdr runs in real panes. Each task
gets its own git worktree, workspace, and pane; you drive it through the `herdr
agent` surface and come back with a commit to review.

The reason to use Herdr rather than a headless dispatcher is **observability**:
the agent is on screen, its lifecycle state is authoritative rather than
inferred, and you can focus its pane and take over mid-task. The price is that
agents run **unconfined** — see [Agents are not sandboxed](#agents-are-not-sandboxed).

For confined, fully headless dispatch instead, use `/opencode-agents`. The two
skills differ only in the runner; the task-shaping rules below are shared.

## Before you start

Three preconditions. Check them in this order and stop at the first failure.

**1. This session must be inside a Herdr pane.**

```bash
test "${HERDR_ENV:-}" = 1 && printf '%s\n' "$HERDR_WORKSPACE_ID" "$HERDR_PANE_ID"
```

If `HERDR_ENV` is unset, stop and tell the user to relaunch Claude Code from
inside Herdr. Do not work around it: outside a pane the CLI talks to whatever
sits on the default socket, which is either the user's own foreground session or
nothing at all (`server_not_running`).

**2. The opencode integration must be installed.**

```bash
herdr integration status | grep '^opencode'
```

It must say `current`. That plugin — `~/.config/opencode/plugins/herdr-agent-state.js` —
is what makes `idle`/`working`/`blocked` authoritative rather than screen-scraped;
it reports over the socket using `HERDR_ENV`, `HERDR_PANE_ID`, and
`HERDR_SOCKET_PATH`, which Herdr injects into every managed pane. Install it with
`herdr integration install opencode` if it is missing or outdated.

**3. The project tree must be clean.** Worktrees are cut from `HEAD`, so
uncommitted work is invisible to every agent you start. Commit first.

## Workflow

- [ ] Step 1: Shape the tasks — each names exact files and fits one module
- [ ] Step 2: Create a worktree workspace per task — `worktree create` returns its IDs
- [ ] Step 3: Start the agent — `agent start` returns `agent_status: idle`; `-- --model` carries the developer level
- [ ] Step 4: Prompt and wait — settles on `idle`/`done`, not `working`
- [ ] Step 4a: If it runs long — separate a hung agent from a slow one
- [ ] Step 5: Read the result — judge the diff, not the transcript
- [ ] Step 6: Commit, review, merge, tear down — `worktree list` comes back empty

### Step 1: Shape the tasks

This step decides whether the work comes back right. The model is small and its
context window, not its coding ability, is usually what fails.

**Inline the contract; there is no attachment mechanism.** A headless dispatcher
can attach a file to the prompt. `herdr agent prompt` types text into the
opencode TUI, so anything the agent must conform to has to be *in the prompt
text*. Paste the interface — the signature, the field names, two examples — and
never point the agent at a spec, PRD, or design document. Pointing at a document
is the most expensive habit there is: the agent reads it, and re-reads it, and
each read is charged again.

Write each prompt as if to a competent stranger:

- Name the exact file to create or edit, and say **"Touch no other file."**
- State the interface in full rather than describing where to find it.
- Make it imperative. A prompt that reads as a question comes back as an answer
  with nothing written.
- A task that begins "find where…" is the wrong shape. Find it yourself and
  name the file.
- Size it to one module. Two agents solving halves of one problem produce two
  incompatible halves — the worktrees isolate the filesystem, not the design.

**Two things a task must never let the agent do:**

1. **Write the tests it is judged by.** A green suite the agent authored
   verifies nothing. Write the test yourself and paste it into the prompt, or
   dispatch it as a separate task to a separate agent.
2. **Edit what it conforms to.** Nothing stops an agent rewriting the interface
   to make its own code compile — that is the shortest path to "done". You
   cannot prevent it here, so you must detect it: Step 6 checks the commit
   against the files you told it to conform to.

### Step 2: Create a worktree workspace per task

One command produces the worktree, a workspace, and a pane sitting in it:

```bash
herdr worktree create --workspace "$HERDR_WORKSPACE_ID" \
  --branch herdr_<id> --base HEAD --label <id> --no-focus
```

Read three values out of the JSON and keep them for the rest of the run:

| Value | Path in the response |
| --- | --- |
| workspace id | `.result.workspace.workspace_id` |
| pane id | `.result.root_pane.pane_id` |
| worktree path | `.result.worktree.path` |

The checkout lands at `~/.herdr/worktrees/<repo-name>/<branch-slug>` — **outside
the project**, with underscores in the branch slugged to hyphens, so
`herdr_parser` checks out at `.../herdr-parser`. Parse the path; do not
construct it.

Use `--no-focus` so the user keeps their pane. Never derive IDs from sidebar
order or from the examples here.

### Step 3: Start the agent

```bash
herdr agent start <id> --kind opencode --pane <pane-id> --timeout 60000
```

Returns once Herdr has confirmed opencode is present and ready — about 3
seconds — with `agent_status: idle` and `interactive_ready: true`. Anything
else means it did not start; read the error rather than prompting into the void.

#### Choosing the developer level

The endpoint serves more than one model, and they are not interchangeable —
they are **developers of different seniority**. Decide which rung the work
deserves before starting the agent; that is your call, not the user's.

Get the ladder from the config, not from memory. `/opencode-agents` ships the
reader and both skills read the same file:

```bash
python3 ../opencode-agents/scripts/opencode_agents.py levels
```

Both skills sit side by side in every project's `.claude/skills/`, so that
relative path holds; from elsewhere, point at the ASST_BBMax copy. Its bundled
model-levels reference covers the schema and where the file lives. Adding a
model is one edit there and **no change to this skill** — never paste an id in
as though it were fixed.

| Level | Reach for it when |
|-------|-------------------|
| senior | correctness depends on an interface defined elsewhere; call sites must stay consistent; a wrong design costs more than the extra latency |
| mid | one module against a spec you already wrote out — clear, self-contained, nothing to infer |
| junior | mechanical and fully specified — rename, extract, add a docstring, scaffold a file whose shape the prompt dictates |

Sending a junior task to senior burns wall clock for nothing; sending a senior
task to junior comes back green and wrong. A task between two rungs goes to the
higher.

Everything after a bare `--` reaches the `opencode` executable, so the resolved
id is applied there:

```bash
herdr agent start <id> --kind opencode --pane <pane-id> --timeout 60000 \
  -- --model <the id the level resolved to>
```

**Confirm it took effect before prompting.** The start result echoes the argv it
used, and the TUI names the live model in its status line:

```bash
herdr agent read <id> --source visible | grep -i 'Build ·'
```

Omit `--model` and opencode falls back to the `model` key in
`~/.config/opencode/opencode.jsonc` — one rung for every task, so pass it
whenever the task deserves a different one. Only `ham51-2/*` ids are the local
endpoint; the `opencode/*` ids are a hosted catalogue over the network, a
different trust and latency story and not what this skill is for.

**Pick one level per batch.** The endpoint keeps a single model resident, so
alternating makes it unload and reload weights between agents — minutes of wall
clock, not seconds. Across a batch, choose once.

Names must match `[a-z][a-z0-9_-]{0,31}` and be unique among live agents. The
name follows the pane's occupant and is cleared when that agent exits, so reuse
after teardown is fine.

### Step 4: Prompt and wait

```bash
herdr agent prompt <id> "<the task text from Step 1>" --wait --timeout 1800000
```

`--wait` returns on the first settled `idle`, `done`, or `blocked`. Do not
restate those with `--until`; use `--until` only for a state-specific wait such
as `herdr agent wait <id> --until blocked`.

**Always pass `--wait`, even when you intend to poll instead.** Without it the
command reports success whether or not the text took effect — observed: a prompt
sent to a just-started agent returned a normal result object, and the agent sat
on opencode's splash screen with `state_change_seq` still at 1, having never
seen it. `--wait` is what enforces the five-second lifecycle-change check that
turns that silent loss into `agent_prompt_stalled`. If you need to poll, send
with `--wait --timeout 60000` first, confirm the agent reached `working`, then
poll from there.

**Give it 1800000 ms, or 2400000 for a task that runs a suite each iteration.**
Herdr's own documentation shows `--timeout 120000`; that is for interactive
questions, not for unattended work against a local model. A measured
single-function task on this endpoint was still `working` after five minutes.
The clock, not the context window, is what usually kills these runs.

What the states mean:

| State | Meaning |
| --- | --- |
| `working` | Still running. Not a failure — extend the wait |
| `idle` / `done` | Settled and ready for input. `done` is idle after unseen background work |
| `blocked` | Herdr recognized an approval or question UI. **Stop and ask the user** |
| `unknown` | An agent is present but unclassified. **Not proof of completion** |

If `agent prompt` returns `agent_prompt_stalled`, the prompt produced no
observed state change within five seconds — inspect with `agent get` and
`agent read` before sending anything else.

### Step 4a: Detect a hung agent

A stalled model endpoint is indistinguishable from a busy one at the lifecycle
layer, and this is where Herdr earns its place — a child process gives you a
pid and a pipe that has simply gone quiet, while Herdr gives you the screen.

Measured against a dead endpoint, sampling every 12 seconds:

| Signal | During a hang | Useful? |
| --- | --- | --- |
| `agent_status` | `working`, forever | No |
| `state_change_seq` | frozen | **Yes** — only moves on a lifecycle transition |
| agent / pane `revision` | frozen — does not track repaints | No |
| md5 of the whole viewport | **changes every sample** | **No — this is the trap** |
| md5 of the viewport minus its last line | stable | **Yes** |
| process CPU time | climbing ~0.45 of a core | No — it busy-waits |

The whole-viewport hash moves because opencode animates a spinner on the last
line. Diff the viewport naively and a hung agent looks productive. Drop the
last line and the hash goes still the moment real output stops.

So, to check on a long-running agent:

```bash
herdr agent read <id> --source visible | sed '$d' | md5sum
```

Same hash twice a minute apart, with `state_change_seq` unchanged, means hung —
not slow. Interrupt with `herdr agent send-keys <id> esc` and check the endpoint
before re-prompting.

`herdr pane wait-output` is the API-native form and, unlike `agent read --lines`,
works while the agent is busy:

```bash
herdr pane wait-output <pane-id> --regex '<pattern only a reply would match>' \
  --source visible --timeout 120000
```

It returns `timeout: timed out waiting for output match` when nothing appears.
Choose the pattern with care: the pane echoes your own prompt, so a pattern
drawn from the task text matches immediately and tells you nothing.

### Step 5: Read the result

```bash
herdr agent get <id>
herdr agent read <id> --source recent-unwrapped --lines 200
```

`recent-unwrapped` joins soft wraps and is the right source for a transcript.

**Both of those are for a settled agent.** While one is still `working`, any
read with `--lines` is refused — `agent_not_idle: its alternate-screen history
can only be captured by scrolling while idle`. To check on a running agent use
`herdr agent read <id> --source visible`, which returns the current viewport:
enough to confirm the prompt landed and the model is generating, which is
usually the real question.

**Raising `--lines` often recovers nothing.** opencode runs on the terminal's
alternate screen, and rows that leave it never enter Herdr's scrollback. If a
larger line count reveals no more, do not keep raising it — ask the agent to
write its summary to a Markdown file in the worktree and reply with the path,
then read the file. Use that only as a fallback, never in the first prompt.

In practice the transcript is the weaker evidence anyway. Judge the diff.

### Step 6: Commit, review, merge, tear down

**Read what the run cost before you tear the worktrees down.** herdr drives the
opencode TUI, so there is no stream to parse here — but opencode records every
session either way, and `/opencode-agents` ships the reader:

```bash
python3 ../opencode-agents/scripts/opencode_agents.py tokens --agents-only --since 1
```

Both skills are installed side by side in every project's `.claude/skills/`, so
that relative path holds; from elsewhere, point at the ASST_BBMax copy. Rows are
attributed per task because each task has its own worktree and the command reads
the task id from the worktree's last path segment. A row with `total: 0` is an
agent that never got a reply — the same silent failure Step 4a hunts, visible
here after the fact.

That command belongs to `/opencode-agents`, not this skill, so its documentation
lives there: read `../opencode-agents/references/token-accounting.md` for the
fields and the caveats — notably that the ledger is container-local, so a
devcontainer rebuild resets it to nothing.

Then commit from **outside** the agent, so the agent never needs write access to
git metadata and you control the message:

```bash
git -C <worktree-path> add -A
git -C <worktree-path> -c user.name=... commit -m "feat: ..."
```

**Check for a contract violation before anything else.** If the commit touches a
file whose contents you pasted into the prompt as the interface, the agent
changed what it was supposed to conform to:

```bash
git -C <worktree-path> diff --name-only HEAD~1
```

Never merge such a commit unread.

Then review, merge, and remove:

```bash
git -C <worktree-path> diff HEAD~1
herdr worktree remove --workspace <workspace-id>
```

Read every diff. These agents ran unattended against a model that is not Claude;
treat the output as a contractor's pull request, not as finished work.

## Validation

Do not report the run complete until all four hold:

1. Every agent reached `idle`/`done` — never `blocked`, `unknown`, or still `working`.
2. Every diff has been read, and nothing sits in contract violation.
3. `herdr worktree list` shows none of the run's worktrees, and `herdr agent list`
   none of its agents.
4. No `herdr_*` branch is left holding unmerged work you have not reported.

If a task produced no commit, say so. An agent that answered in prose without
writing a file is a prompt that read as a question — rewrite it as an imperative
naming exact files and re-dispatch.

## Gotchas

All observed on this machine against herdr 0.8.0, not inferred.

- **Agents are not sandboxed.** <a id="agents-are-not-sandboxed"></a>Bubblewrap
  confinement and Herdr's agent API are mutually exclusive here. `agent start`
  runs a fixed `argv: ["opencode"]` with no wrapper hook, and `config.toml` has
  no launch-command override. Wrapping the pane's shell instead does confine it
  — verified, a write to `$HOME` returned `Read-only file system` — but then
  `agent start` refuses with `agent_pane_busy: not an available shell`, because
  bwrap stays resident between the pane's `shell_pid` and the foreground shell.
  Dropping `--unshare-pid` does not close the gap. **The worktree is isolation
  by convention only**; keep every prompt scoped to relative paths, and use
  `/opencode-agents` when confinement actually matters.

- **Never start an agent with `pane run`.** Launching `opencode` yourself does
  not register an agent: `agent get <pane>` returns `agent_not_found`, `agent
  list` stays empty, and `agent prompt`, `agent wait`, and every lifecycle state
  are unavailable — which is the entire reason to use Herdr. `agent start` is
  the only supported path.

- **`agent start` needs an *available* shell pane.** The shell itself must be in
  the foreground with no command running. A pane that already hosts an agent, or
  anything else in the foreground, returns `agent_pane_busy`. `agent start`
  never creates, splits, or moves layout — make the pane first.

- **`unknown` is not `done`.** It means an agent is present that Herdr could not
  classify. Treat it as unfinished and inspect the pane.

- **CLI reads do not mark a tab seen**, which is why finished background work
  reports `done` rather than `idle`. Both are settled; neither needs action.

- **Worktrees live outside the repository**, under `~/.herdr/worktrees/`. They
  never appear in `/projects-git-status` and never dirty the project, but
  nothing else will clean them up either — `worktree remove` is this skill's job.

- **Branches are `herdr_*`, deliberately not `claude_*` or `worktree-*`.**
  `/projects-git-cleanup` sweeps only those two prefixes, so an in-flight agent
  branch can never be deleted out from under a run.

- **Uncommitted files are invisible to agents.** The worktree is cut from `HEAD`.
  This bites hardest with `.opencode/agent/*.md`: edit one, dispatch without
  committing, and the agent runs with the old definition — or the wrong agent
  runs entirely.

- **Run one agent at a time.** Herdr makes parallelism look free — the panes are
  right there — but this is one local model on one endpoint. Concurrent agents
  contend for the same GPU rather than using idle capacity, so nothing finishes
  sooner and everything drifts toward its timeout. Budget wall clock as the
  *sum* of the tasks.

- **The endpoint blips.** A failure inside two seconds having produced nothing
  is a transient provider error, not a task failure. Re-prompt the same agent
  rather than rebuilding the worktree.

- **A dead endpoint has two faces, and one of them looks like success.** If the
  provider refuses fast, opencode reports the error and settles straight back to
  `idle` — so `--wait` returns "settled" and the run looks clean while nothing
  was written. **`idle` after a prompt is not evidence the task was done**;
  confirm against the worktree diff, never against the state alone. If the
  provider instead accepts and never answers, the agent stays `working`
  indefinitely (observed for 20 minutes on a single-function task). Step 4a
  separates that from a genuinely slow task.

## Stop conditions

Stop and ask the user when:

- `HERDR_ENV` is unset, or the opencode integration is missing. Neither has a
  safe workaround.
- Any agent reports `blocked` — it is waiting on an approval or a question, and
  answering on the user's behalf is their call, not yours.
- The project tree is dirty at preflight. Offer `/commit2repo`; do not stash or
  discard.
- A commit is in contract violation, or a task's tests were written by the agent
  that is judged by them. Report it; do not merge to make the run look clean.
- Merging a `herdr_*` branch into the project's main branch, or pushing.
  Invoking this skill authorizes neither.

## Related

| Skill | Difference |
| --- | --- |
| `/opencode-agents` | Same model and task rules, headless subprocess runner, supports `--sandbox` confinement, no live pane to watch. Takes `--level`/`--model` as flags and per task in the task file, where this skill passes the resolved id through `--` at `agent start`. Also ships the shared developer ladder, its `levels` reader, and the `tokens` reader Step 6 uses |
| `/commit2repo` | Merging and pushing a reviewed `herdr_*` branch |
| `/projects-git-cleanup` | Sweeps `claude_*` and `worktree-*` only — never `herdr_*` |
