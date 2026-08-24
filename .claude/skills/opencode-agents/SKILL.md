---
name: opencode-agents
description: >-
  Delegate coding tasks to subagents run by the opencode CLI against a locally
  configured model, each in its own git worktree, then review, merge, and clean
  up their work. Use when the user wants to farm work out to opencode, run tasks
  on their own/local LLM instead of Claude, orchestrate several opencode agents
  in parallel over a project, or hand a batch of independent changes to a cheaper
  model — including phrasings like "use my local model for this", "spin up
  opencode agents", "have opencode build these", or "run these tasks on qwen".
  Not for a single edit Claude should just make, and not for configuring opencode
  itself.
metadata:
  runtime: python3-stdlib
  requires: opencode CLI, git
---

# opencode agents

Dispatch work to the `opencode` CLI as subagents. Each task gets its own git
worktree and branch, runs unattended against a configured model, and comes back
as a commit you review and merge.

The window is the binding constraint on these models, so read
[keeping a task inside the context window](#keeping-a-task-inside-the-context-window)
before writing the task file — it is where most of the quality comes from.

Everything goes through one script:

```bash
python3 scripts/opencode_agents.py --help
```

Use `--project PATH` to target a repository other than the current directory.

## When this is the right tool

Use it when the work splits into **independent, well-scoped tasks** that a
smaller model can do — scaffolding modules, writing tests against a stated
interface, mechanical refactors, boilerplate across many files.

Use `/herdr-agents` instead when you want to watch the agents work or take one
over mid-task: it runs the same opencode agents in Herdr panes with authoritative
lifecycle state, at the cost of `--sandbox` confinement, which Herdr's agent API
cannot be combined with. This skill remains the one for confined, headless runs.

Do not use it for a single edit (just make the edit), for work needing judgement
across the whole codebase, or for tasks whose file sets overlap — the worktrees
isolate the *filesystem*, not the design decisions, and two agents solving
halves of one problem produce two incompatible halves.

## The loop

### 1. Preflight

```bash
python3 scripts/opencode_agents.py --project PATH check
```

Reports the opencode version, available models, discovered agent definitions,
and a `problems` list. Exit 3 means something will break — read `problems`
before going further. Fix the problems, or pass around them (`--model`), then
continue.

### 2. Define the agent

opencode agents are markdown files with frontmatter, in `.opencode/agent/` in
the project (or `~/.config/opencode/agent/` globally). Copy
[assets/agent-template.md](assets/agent-template.md) and edit the system prompt:

```bash
mkdir -p .opencode/agent
cp assets/agent-template.md .opencode/agent/builder.md
```

**`mode:` must be `primary` or `all`.** See the gotchas — this is the single
most common way a run silently does the wrong thing.

**Commit the agent file before dispatching.** Worktrees are checked out from
`HEAD`, so an uncommitted `.opencode/agent/*.md` does not exist inside the
worktree and the agent will not be found.

The template's `tools:` block and its context rules are not decoration — they
trim the fixed overhead of every step and forbid the re-reading that wastes the
window. Keep them unless you have a reason not to, and do not add `patch: false`
back: it takes `write` and `edit` with it.

Read [references/agent-files.md](references/agent-files.md) when you need
per-agent tool restrictions, temperature, or a model override.

### 3. Write the task file

JSON — an array of tasks, or an object with defaults plus `tasks`:

```json
{
  "model": "ham51-2/qwen/qwen3.5-9b",
  "agent": "builder",
  "tasks": [
    {
      "id": "parser",
      "files": ["src/model.py"],
      "prompt": "Create src/parser.py with a parse(text) function that ... Touch no other file."
    },
    {
      "id": "cli",
      "prompt": "Create src/cli.py with an argparse entry point that ... Touch no other file.",
      "agent": "reviewer",
      "timeout": 2400
    }
  ]
}
```

`id` becomes a branch name (`opencode_<id>`) and must be unique. Per-task
`agent`, `model`, `timeout`, and `files` override or extend the defaults.

Write prompts as if to a competent stranger with no context: name the exact
files, state the interface, and say what not to touch. A small local model
follows a concrete instruction far better than an aspirational one.

`files` attaches each path to the prompt, so the agent **starts** holding that
content instead of spending tool calls hunting for it — and cannot re-read it
later. Attach the interface the task must match, not the file it is writing.
Paths are relative to the project root and must be committed; the agent works in
a worktree cut from `HEAD`, so an uncommitted file is not there. Absolute paths
and `..` escapes are refused, since under `--sandbox` nothing outside the
worktree is readable anyway.

### Keeping a task inside the context window

These models are small, and the window — not their coding ability — is usually
what decides whether the work comes back right. A task that fills its context
does not fail. It gets vague, forgets the interface it was given, and re-reads
files it already has, and none of that shows in the exit code.

Measured against `ham51-2/qwen/qwen3.5-9b`: ~4,900 tokens of fixed overhead per
step plus ~1,900 of growth, so a 128,000 budget is about **60 tool calls**. Most
tasks are nowhere near it — the worst so far peaked at 55,842 over 27 steps.

Four rules, in order of how much they buy:

1. **Never point an agent at a spec, PRD, or design document.** The most
   expensive habit observed — one task read a 14,000-token PRD *three times*
   before writing a line. Read it yourself and put the signature, the field
   names, and two examples in the prompt, which is counted once.
2. **Attach with `files`, don't make the agent search.** Same token cost as a
   read, one fewer step, lands exactly once, and deletes the `glob`/`list`/`read`
   hunting phase entirely.
3. **Restrict the toolset** in the agent file, but never with `patch: false` —
   it disables `write` and `edit` too (see the gotchas). The template's four
   safe exclusions cost ~4,900 tokens of overhead against 5,501, paid back on
   every step.
4. **Size tasks to finish under ~20 steps, and give them 1800–2400s.** One
   module — and note that pairing it with the test that grades it is a
   correctness problem, not just a size one (see below). A task that begins
   "find where…" is the wrong shape: find it yourself and name the file. Step
   count and wall clock are separate limits and the clock usually binds
   first.

### The clock binds before the context does

Step count and wall clock are independent limits, and the clock hits first. Nine
measured `CODE_GitTracker` runs took 787–1008s while sitting far inside the
60-call context budget — all nine would have died against the old 900s default,
killed mid-write with nothing committed. **`DEFAULT_TIMEOUT` is now 1800**; use
2400 when a task runs an attached suite each iteration. Steps do not predict
seconds: the median step is 15–24s but individual steps reach 335s, so 11 steps
took 796s while 52 steps took 877s. Budget by task shape, never by step count.

Give opencode the window so compaction can act as a backstop, since for a custom
openai-compatible provider it otherwise has no idea:

```jsonc
"models": { "qwen/qwen3.5-9b": { "name": "qwen/qwen3.5-9b",
                                 "limit": { "context": 128000, "output": 8192 } } }
```

Read [references/context-budget.md](references/context-budget.md) for the full
measurements, what compaction costs when it fires, and how to read the report.

### Two things the agent must never be allowed to do

Both were caught on 2026-08-09 returning results that looked clean and were not.
Neither is really a model failure — they are what any agent does when the task
lets it choose between fixing its code and moving the goalposts.

**1. It must not write the tests it is judged by.** Every green result from an
agent that authored its own test file was wrong; every result measured against a
suite it did not write was honest. Write the test yourself and attach it, or
dispatch it as a separate task run by a separate agent. If one task must produce
both, its passing suite verifies nothing until you have read the test.

**2. It must not be able to edit what it conforms to.** `files` puts the
contract in front of the agent; nothing stops it rewriting the interface, which
is the shortest path to making its own code work. `--sandbox` does not help —
it makes everything *outside* the worktree read-only, and an attachment is
inside it. So `dispatch` detects instead: an attached path appearing in the
task's commit sets status `contract_violation` (not `done`, so the run exits 1)
and is hoisted into a top-level `contract_violations` list. The commit is kept
for inspection — never merge one unread.

### 4. Dispatch

Preview first — this creates nothing:

```bash
python3 scripts/opencode_agents.py dispatch --tasks tasks.json --dry-run
```

Then run:

```bash
python3 scripts/opencode_agents.py dispatch --tasks tasks.json --sandbox
```

**Selecting the model.** `--model` overrides the task file's default for one
run without editing it; a task naming its own `model` keeps it either way.
Precedence: per-task `model` > `--model` > the file's top-level `model` > the
`model` key in `~/.config/opencode/opencode.jsonc`.

```bash
python3 scripts/opencode_agents.py dispatch --tasks tasks.json --model ham51-2/qwen/qwen3.6-35b-a3b
```

Both `dispatch` and `check` validate the id against `opencode models` and exit
3 before any work starts, so a typo costs a second rather than a run of failed
agents. Mixing models across a batch is fine — the endpoint serves one at a
time regardless, so the choice moves quality, not throughput.

**Use `--sandbox` whenever the machine supports it.** It confines each agent
with bubblewrap so the only writable paths are its own worktree and its own
state — everything else, including the project's `.git` and your home
directory, is read-only, and an attempted write outside fails with an error the
agent reports. Without it the worktree is isolation by convention only. It is
Linux-only and needs `bwrap`; `check` reports availability, and `dispatch`
exits 3 rather than quietly running unconfined. Read
[references/sandboxing.md](references/sandboxing.md) for what it does and does
not cover — notably, **the network is not isolated**.

Expect it to be unavailable inside a container: bubblewrap needs a user
namespace, and `check` reports "cannot create a namespace here" when the
container does not grant one. There is no workaround from inside — dispatch from
the host, or accept unconfined agents and lean on the task-shape rules above.

Each task gets a worktree under `.opencode-agents/worktrees/<id>`, runs, and has
its changes committed on `opencode_<id>`. Progress goes to stderr; the JSON
result lands on stdout. Exit 1 means at least one task did not end in `done` or
`no-changes`.

### Watching an agent work

Agents take minutes. Live progress goes to **stderr**, one line per tool call,
reply, and completed step, each tagged with its task id:

```
  [notes] read hwreport.py
  [notes] — step done (5,776 tokens)
  [notes] write NOTES.md
  [notes] · Created NOTES.md with a bullet list of all public functions...
  [done] notes (27.9s)
```

On by default when only one agent runs at a time; add `--stream` to get it with
several in flight (the task-id prefix keeps that readable), or `--no-stream` to
silence it.

Two ways to watch a run you did not start in the foreground, both of which work
whether or not `--stream` is on, because the per-task log is always written as
events arrive rather than at exit:

```bash
tail -f .opencode-agents/logs/<id>.log            # raw NDJSON, one event per line
python3 scripts/opencode_agents.py ... 2>run.log  # then tail -f run.log
```

Per-task `status` values:

| Status | Meaning |
| --- | --- |
| `done` | Ran clean and committed changes |
| `no-changes` | Ran clean but wrote nothing — usually a prompt the model treated as a question |
| `agent_mismatch` | The requested agent did not run; **the reply is from the wrong agent** |
| `contract_violation` | It committed changes to a file attached via `files` — read the diff before trusting anything else in it |
| `timeout` | No completion within the task's timeout |
| `transient` | Provider error on every attempt, zero tokens produced — endpoint problem |
| `failed` | Anything else; read the `log` path in the result |

Every result also carries a `context` block — `peak_tokens` (the largest
single-step input, which is the high-water mark of the conversation), `pct` of
the budget, `steps`, and `tokens_per_step`. Tasks at or above 75% are collected
into a top-level `context_warnings` list and printed as they finish. That is a
quality signal, not a failure: the task still committed, but its later work was
done with a crowded window. Note that the summed `tokens.input` beside it is a
different number and says nothing about headroom — it grows with step count
even when every step stayed small.

### 5. Review, merge, clean up

```bash
python3 scripts/opencode_agents.py diff --task parser     # or omit --task for all
python3 scripts/opencode_agents.py merge --all            # skips tasks with no commits
python3 scripts/opencode_agents.py cleanup --all
```

**Read the diffs before merging.** These agents ran unattended against a model
that is not Claude; treat the output as a contractor's pull request, not as done
work. Start with anything in `context_warnings` — a task that peaked near its
budget produced its last edits with a full window, and that is where the quiet
mistakes are. `merge` refuses to run if the project tree is dirty, and aborts and stops
at the first conflict rather than leaving a half-merged tree.

`cleanup` keeps any worktree whose commits were never merged unless you pass
`--force`.

## Gotchas

These are all observed on this machine, not guesses.

- **opencode resolves its project root from `$PWD`, not the real working
  directory.** Anything that sets a child's cwd without also setting `PWD` —
  Python's `subprocess`, most process spawners — makes opencode load the
  *parent's* repository instead. Two symptoms, both observed: an instant
  provider error with zero tokens (it packed the wrong, much larger repo into
  the request), and — worse — **an agent writing its files into the parent
  repository** while its own worktree stays empty. The script sets `PWD`
  explicitly. If you ever invoke `opencode run` from a script yourself, do the
  same, and if a dispatch reports `transient` or `no-changes` across the board,
  check the *calling* repo for stray files before re-running.

- **A bad `--agent` name exits 0 with a normal-looking answer.** opencode prints
  `agent "X" not found. Falling back to default agent` and then runs its default
  agent to completion. Same for an agent whose `mode` is `subagent`:
  `agent "X" is a subagent, not a primary agent`. The run succeeds, the files get
  written, and nothing in the exit code says the wrong agent did it. The script
  detects both and reports `agent_mismatch` — never treat that status as a pass.

- **An invalid default model fails as a server error, not a config error.**
  `~/.config/opencode/opencode.jsonc` held `"model": "qweb/qwen3.5-9b"` (typo,
  and missing the provider prefix) until 2026-08-09; bare `opencode run` failed
  with "Unexpected server error" rather than naming the model. It is now
  `ham51-2/qwen/qwen3.5-9b` and works. `check` re-validates the default against
  `opencode models` every run, so pass `--model` if it ever reports this again.

- **Uncommitted agent files are invisible to the agents.** A worktree is checked
  out from `HEAD`. Editing `.opencode/agent/builder.md` and dispatching without
  committing gives you `agent_mismatch`, not your edit.

- **`--file` swallows the prompt.** It takes an array, so yargs keeps consuming
  positionals after it and the message becomes another filename. The symptom is
  `Error: File not found: <your entire prompt>` — with a zero-token exit, so it
  looks like an endpoint problem rather than an argument-order one. The script
  terminates the list with `--` on every run, attachments or not.

- **Close stdin.** `opencode run` inherits the parent's stdin; from a script with
  an open stdin it can block indefinitely. The script uses `DEVNULL`; by hand,
  redirect `</dev/null`.

- **The local endpoint blips.** A provider error with zero tokens and a sub-2s
  runtime is transient, not a task failure. The script retries twice with backoff
  (`--retries N`) and only marks `transient` if every attempt failed that way.

- **`--auto` is passed on every run** so the dispatcher does not depend on the
  ambient permission config. The global opencode config allows all permissions
  anyway, so **without `--sandbox` an agent can write anywhere you can** — the
  worktree alone is isolation by convention. Pass `--sandbox`, and keep prompts
  scoped to relative paths regardless.

- **A denied permission hangs the task instead of failing it.** `--auto`
  approves everything except explicit `deny` rules in the agent file, and those
  are genuinely enforced — but a denied tool call blocks until the timeout
  (exit 124) rather than erroring. That is why every task has a timeout.

- **Never set `patch: false` in an agent file.** It does not disable one tool —
  `write` and `edit` go with it, and the agent is left able to read and reason
  but not to produce a file. It looks like a bargain because it accounts for 77%
  of the restricted toolset's overhead saving, and the failure is quiet: the
  agent reports what it "wrote" and the exit code is clean. The template shipped
  with it from the start and it was removed on 2026-08-09.

- **`--format json` streams; `subprocess.run` does not.** opencode emits its
  NDJSON events incrementally as they happen, but
  `subprocess.run(capture_output=True)` buffers until the process exits — which
  is why the dispatcher used to sit silent for minutes. It now reads the pipe
  line by line in a thread. The event types are `step_start`, `tool_use`,
  `text`, `step_finish`; note the tool event's `type` is **`tool_use`** while
  its `part.type` is `"tool"`, and matching the wrong one silently yields an
  empty tool list rather than an error.

- **A repo-root `AGENTS.md` is loaded into every session**, as is `CLAUDE.md`.
  Confirmed by measurement — a two-line `AGENTS.md` moved the baseline from
  4,900 to 4,990 tokens. Useful for rules that must apply whichever agent runs,
  and a standing cost to keep short.

- **State lives in `.opencode-agents/`** inside the target project and is added
  to `.git/info/exclude`, not `.gitignore` — so it never shows up in
  `/projects-git-status` and never needs committing. Same mechanism `/build-loop`
  uses.

- **Agent branches are `opencode_*`, deliberately not `claude_*` or
  `worktree-*`.** `/projects-git-cleanup` only sweeps those two prefixes, so an
  in-flight agent branch can never be deleted out from under a run. Cleaning up
  is this skill's `cleanup` command.

## Parallelism: one at a time

**`--parallel` defaults to 1, and on this hardware it should stay there.** Each
agent finishes before the next starts. The endpoint will *accept* concurrent
sessions, but it is one local model on one machine — parallel agents contend for
the same GPU rather than using idle capacity, so nothing finishes sooner and
everything drifts toward its timeout, which at 1800s a task is where a run
starts losing work outright. Raising it warns.

Budget the wall clock as the *sum* of the tasks: three at the measured ~900s is
about 45 minutes. Background the dispatch and watch the log rather than blocking.

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| `check` exits 3 on the model | Config default model is invalid | Pass `--model`, or fix `opencode.jsonc` |
| Every task `transient` | Endpoint down, or `PWD` not set by a custom caller | Confirm the endpoint; use the script, not a hand-rolled spawn |
| `agent_mismatch` | Wrong name, `mode: subagent`, or uncommitted agent file | Fix the file, commit it, re-dispatch |
| `no-changes` | Prompt read as a question | Rewrite it as an imperative naming exact files |
| `contract_violation` | Agent edited a file it was given to conform to | Read the diff; re-dispatch with the contract stated inline instead of attached |
| Tests pass but the code is wrong | Agent wrote the tests it is judged by | Attach a suite it did not write, or split test authoring into its own task |
| `worktree already exists` | Previous run not cleaned up | `cleanup --task <id>` |
| `merge` exits 3 | Project tree dirty | Commit or set aside your own changes first |
| `dispatch --sandbox` exits 3 | No `bwrap`, or namespaces blocked (usual inside a container) | Dispatch from the host, or drop `--sandbox` knowing agents are then unconfined |
| Agent says it wrote a file you cannot find | Sandboxed write landed on the internal `/tmp` tmpfs | Have it write inside the worktree using a relative path |
| `context_warnings` non-empty | Task too big, or it read a document | Attach with `files`, inline the spec, split the task |
| Output drifts from the stated interface late in a task | Window filled; the agent no longer has the contract in view | Attach the interface file rather than describing where to find it |
| `File not found: <the whole prompt>` | `--file` consumed the message | Argument order — the script's `--` handles it; a hand-rolled call must too |

## Done condition

The run is finished when `status` shows every task as `done` or `no-changes`,
you have read each diff, `merge` reports no `conflicted` entries, and `cleanup`
leaves nothing behind. Anything in `agent_mismatch`, `contract_violation`,
`timeout`, `transient`, or `failed` is unfinished work — report it, do not
quietly drop it. A `done` task whose tests the agent wrote itself is not
verified either, whatever the suite says.

Merging agent branches into the project's main branch, and pushing, are separate
decisions. Invoking this skill authorizes neither; use `/commit2repo` when the
user asks.

## Bundled files

| File | Purpose |
| --- | --- |
| `scripts/opencode_agents.py` | The dispatcher — check, dispatch, diff, merge, cleanup |
| [assets/agent-template.md](assets/agent-template.md) | Starter opencode agent definition |
| [references/agent-files.md](references/agent-files.md) | Agent frontmatter fields: tools, temperature, model, permissions |
| [references/sandboxing.md](references/sandboxing.md) | What `--sandbox` confines, what it does not, and why it refuses |
| [references/context-budget.md](references/context-budget.md) | Measured window costs, attachment vs reading, compaction, sizing tasks |
