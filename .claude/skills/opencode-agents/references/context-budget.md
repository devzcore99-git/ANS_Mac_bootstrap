# Context budget

The local models are small. The context window, not the model's coding ability,
is usually what decides whether a task comes back right — a task that fills its
window does not fail, it gets vague, forgets the interface it was handed, and
re-reads files it already has. None of that shows up in an exit code, which is
why `dispatch` reports a `context` block per task.

Every number here was measured on 2026-08-09 against `ham51-2/qwen/qwen3.5-9b`:
ten real `CODE_GitTracker` runs, plus controlled single-prompt runs.

## What the window actually costs

| Item | Tokens |
| --- | --- |
| Fixed overhead, full default toolset | 5,501 |
| Fixed overhead, toolset restricted as in `assets/agent-template.md` | ~4,900 |
| A committed `AGENTS.md` (auto-loaded, 2 lines) | +90 |
| Unsafe extra saving from `patch: false` (disables `write`/`edit`) | ~2,100 |
| Growth per step, real runs | ~1,900 (worst 2,768) |
| Reading a 30 KB file | ~10,000 |
| Worst real task (`classify`, 27 steps) | peak 55,842 |

Two consequences. Overhead is paid **on every step**, because the whole
conversation is resent each time — so even the ~600 tokens the safe toolset
restriction saves is worth more than it looks. And at ~1,900 per step, a 128,000
budget buys roughly **60 tool calls**. Ordinary tasks are nowhere near that;
`classify` used 27 steps and 44% of the budget.

The endpoint reports `max_context_length` of 262,144 for this model, so 128,000
is not a hard ceiling — it is a working budget, chosen because a 9B Q4 model's
useful reasoning span is far shorter than its architectural maximum. Change it
with `--context-limit` if you move to a different model.

## The one habit that costs the most

In the `CODE_GitTracker` run, three tasks were told to consult
`plans/gittracker-PRD.md`. It is 55,909 characters — about 14,000 tokens — and
each of them read it. `classify` read it **three times**, 94,000 characters in
total, roughly 24,000 tokens, before writing a line of code.

That single instruction cost more than everything else in the run combined.

**Never point an agent at a spec, PRD, or design document.** Read it yourself
and put the part that matters — the signature, the field names, the two
examples — into the task prompt. The prompt is counted once. A document the
agent reads is counted once per read, and small models re-read.

## Attach files instead of letting the agent find them

`"files": ["src/model.py"]` on a task attaches that file to the prompt. Measured
against making the agent read the same content: identical token cost, one fewer
step, and — the real win — the content lands exactly once and **cannot** be
re-read.

It also deletes the search phase. An agent told "match the interface in
model.py" spends `glob`, `list`, and `read` calls finding it first; an agent
handed the file starts on step one already knowing it. In the end-to-end test
of this change the agent made zero `read` calls and got the dataclass right.

Attach the interface the task must match, not the module the task is writing.
Paths are relative to the project root and must be **committed** — the agent
works in a worktree checked out from `HEAD`, so an uncommitted file is not
there.

## Restrict the toolset

The `tools:` block in the agent file is a cheap win, but a smaller one than it
first appeared. Disabling `webfetch`, `task`, `todowrite`, and `todoread` takes
fixed overhead from 5,501 to about 4,900 tokens on every step — 23% of the
2,701-token saving originally measured.

The missing 77% came from `patch: false`, which is **not safe to set**. It
disables `write` and `edit` along with `patch`, leaving an agent that can read
and reason but cannot produce a file, and it fails quietly — the agent describes
what it wrote and exits clean. It was in the template from the start and was
removed on 2026-08-09. A cheaper step is worth nothing if no step writes code.

`webfetch` and `task` are the two worth disabling on principle — both can pull
unbounded content into the window, and neither has any business in a scoped
code change. `todowrite`/`todoread` are simply unused by this workflow. Keep
`glob` and `list` only if the agent genuinely has to discover files; when you
attach what it needs, it does not.

## Give opencode the limit

opencode compacts a session only if it knows the model's window. For a custom
openai-compatible provider it does not, unless the model entry says so:

```jsonc
"models": {
  "qwen/qwen3.5-9b": {
    "name": "qwen/qwen3.5-9b",
    "limit": { "context": 128000, "output": 8192 }
  }
}
```

Verified honored: with `limit.context` set to 6,000 as a test, a run's input
tokens went 12,758 → 10,356 → 3,252 and stayed under the cap for the remaining
nine steps. Without it there is no backstop at all — the ten `CODE_GitTracker`
runs grew monotonically to their peak with no compaction at any point.

Treat this as a safety net, not a strategy. That same test showed what
compaction costs: the run went from 1 step to 12, the agent lost the attached
file and had to go re-read it. Compaction near the end of a long task is
insurance; a task that relies on it is a task that should have been split.

## Sizing a task

Aim for a task that finishes in **under 20 steps** and peaks under a third of
the budget. In practice that means:

- One module. Not a subsystem — and not a module bundled with the test that
  grades it; an agent that writes both converges on a test asserting what its
  code already does. Attach a suite it did not write.
- The interface it must match stated inline or attached — never "look at how X
  does it".
- No exploration. If the task starts with "find where…", it is the wrong shape;
  find it yourself and name the file.

## The clock is the other budget

Staying inside the window does not mean staying inside the timeout. The same
three `CODE_GitTracker` tasks, run three times on 2026-08-09:

| task | original | round 1 | round 2 |
|------|----------|---------|---------|
| `gitcmd` | 950s / 25 steps | 874s / 20 | 872s / 22 |
| `discovery` | 993s / 14 | 796s / 11 | 865s / 33 |
| `classify` | 1008s / 27 | 877s / 52 | 787s / 23 |

All nine sit far inside the 60-call context budget. All nine exceed the 900s
that used to be `DEFAULT_TIMEOUT`, which is why the first dispatches committed
nothing — killed just short of finishing, with the whole run's wall clock spent.
The default is now 1800; use 2400 when a task runs an attached suite each iteration.

Steps are a poor proxy for seconds. The median step is 15–24s but individual
steps reach 200–335s, so `discovery` finished 11 steps in 796s while `classify`
took 52 steps in 877s. Size the context budget by step count; size the timeout
by task shape.

## Reading the report

`dispatch` emits a `context` block per task and a `context_warnings` list at the
top level:

```json
"context": { "peak_tokens": 4441, "limit": 128000, "pct": 3,
             "steps": 5, "tokens_per_step": 888 }
```

`peak_tokens` is the largest single-step input — the high-water mark of the
conversation. The summed `tokens.input` next to it is not the same thing and
does not tell you anything about headroom; it grows with step count even when
every step stayed small.

Anything at or above 75% of the budget is flagged in `context_warnings` and
printed during the run. A flagged task is not a failed task — it is a task
whose diff deserves a much closer read, and whose next run should be split.
