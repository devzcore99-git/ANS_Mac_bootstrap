# Token accounting

How to find out what an agent run actually cost, after the fact.

`opencode_agents.py tokens` reads opencode's own session ledger. It covers
**both** agent skills, which is the point: `/opencode-agents` parses its own
`--format json` stream and already reports peak context per task while it runs,
but `/herdr-agents` drives the opencode TUI and has no stream to parse. The
ledger is written either way.

## The command

```bash
python3 $SKILL_DIR/scripts/opencode_agents.py tokens [options]
```

| Flag | Effect |
|------|--------|
| `--since DAYS` | Only sessions started in the last N days (default: all history) |
| `--here` | Only sessions under the target project directory |
| `--agents-only` | Drop interactive sessions; keep only herdr/opencode agent worktrees |
| `--summary` | Omit the per-session detail, keep the totals |
| `--limit N` | Cap the detail list (default 50) |

Output is the usual JSON on stdout: `totals`, `by_model`, `by_runner`, and
unless `--summary`, a `detail` array of sessions newest first.

`by_runner` splits into `herdr-agents`, `opencode-agents`, and `interactive`.
Each detail row carries `task` — the worktree's last path segment, which is the
task id, because both skills give every task its own worktree:

```
RUNNER           TASK            MODEL                          TOTAL
herdr-agents     herdr-hello     ham51-2/qwen/qwen3.6-35b-a3b     11940
opencode-agents  plain           ham51-2/qwen/qwen3.5-9b          15029
```

## Reading it

**`input` dwarfs `output`, and that is correct.** Every step resends the whole
conversation, so input accumulates quadratically across a long run while output
is just the reply. A task showing 250K input and 2.7K output is not broken; it
is a normal multi-step agent. Use `input` to judge whether a task is straining
the window and needs splitting — the same judgement
[context-budget.md](context-budget.md) covers for a live run.

**A zero-token session is a real signal.** It means the agent started and never
got a reply: a stalled endpoint, a prompt that never landed, or a model still
loading. `/herdr-agents` calls this out at the lifecycle level; here it shows up
as a session row with `total: 0`.

## Three caveats

- **`cost` is not money here.** The `ham51-2` provider has no pricing configured,
  so every local row is `0.0`. The command emits a `cost_note` saying so rather
  than printing a total that would read as free when it is merely unpriced. Only
  a hosted provider produces a real figure.

- **Inside a devcontainer the ledger is ephemeral.** opencode deliberately gets
  no host mount — its database holds credentials alongside sessions — so the
  container has its own copy and a rebuild resets it to nothing. History
  survives on the host. With no database at all the command exits `3` and says
  which of the two situations it is.

- **The database is opened read-only.** It is opencode's live WAL database and
  holds credentials; nothing here writes to it. Do not add a write path.

## If you need more than this exposes

`opencode stats` is opencode's own view of the same data, with `--days`,
`--models`, and `--project` filters and a cost table. It prints a formatted
table with no JSON option, so it is for reading rather than scripting — which is
why this command exists alongside it.
