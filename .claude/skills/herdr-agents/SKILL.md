---
name: herdr-agents
version: 1.0.0
description: >-
  Mechanics for starting, stopping, checking on, and tearing down herdr-instantiated
  opencode agents. Each agent gets its own git worktree, workspace, and pane.
  Use when you need to start an agent, check its state, send it a prompt, detect
  hangs, read its output, or remove its worktree. Does not cover workflow, roles,
  loop orchestration, or developer levels — those are in /build-loop. Triggers on
  "start an agent", "check on", "hang", "tear down", "worktree create/remove",
  "herdr agent". Requires Herdr. Not for workflow design or task planning.
metadata:
  runtime: herdr-cli
  requires: herdr 0.8+, opencode CLI, git
---

# Herdr agents

Mechanics for `herdr agent` commands: create worktrees, start agents, send prompts,
check state, detect hangs, read output, commit, and tear down.

This skill is the mechanical reference. For workflow, roles, developer levels, and
loop orchestration, read `/build-loop`.

## Before you start

Four preconditions. Check them in this order and stop at the first failure.

**1. The Manager Agent must be configured.**

```bash
python3 ../opencode-agents/scripts/opencode_agents.py levels 2>/dev/null | grep -A1 '"manager"' | grep '"agent"' | grep -v 'null'
```

or:

```bash
python3 -c "
import json, re
with open('/home/ahill/.config/opencode/model-levels.json') as f:
    content = f.read()
lines = [l for l in content.split(chr(10)) if not l.strip().startswith('//')]
data = json.loads(chr(10).join(lines))
agent = data['manager'].get('agent')
model = data['manager'].get('model')
if agent and model:
    print('ok')
else:
    print('fail')
" 2>/dev/null
```

If the manager has `"agent": null` or is missing entirely, stop and tell the
user to configure it in `~/.config/opencode/model-levels.json`.

**2. This session must be inside a Herdr pane.**

```bash
test "${HERDR_ENV:-}" = 1 && printf '%s\n' "$HERDR_WORKSPACE_ID" "$HERDR_PANE_ID"
```

If `HERDR_ENV` is unset, stop and tell the user to relaunch Claude Code from
inside Herdr.

**3. The opencode integration must be installed.**

```bash
herdr integration status | grep '^opencode'
```

It must say `current`. That plugin — `~/.config/opencode/plugins/herdr-agent-state.js`
— makes `idle`/`working`/`blocked` authoritative. Install with
`herdr integration install opencode` if missing or outdated.

**4. The project tree must be clean.** Worktrees are cut from `HEAD`.

## Creating a worktree workspace

One command produces the worktree, a workspace, and a pane sitting in it:

```bash
herdr worktree create --workspace "$HERDR_WORKSPACE_ID" \
  --branch herdr_<id> --base HEAD --label <id> --no-focus
```

Read three values out of the JSON response:

| Value | Path in the response |
| --- | --- |
| workspace id | `.result.workspace.workspace_id` |
| pane id | `.result.root_pane.pane_id` |
| worktree path | `.result.worktree.path` |

The checkout lands at `~/.herdr/worktrees/<repo-name>/<branch-slug>` — **outside
the project**. Parse the path; do not construct it.

Use `--no-focus` so the user keeps their pane.

## Starting an agent

```bash
herdr agent start <id> --kind opencode --pane <pane-id> --timeout 60000
```

Returns once Herdr has confirmed opencode is present and ready — about 3
seconds — with `agent_status: idle` and `interactive_ready: true`. Anything
else means it did not start; read the error rather than prompting into the void.

Start with its level's `agent` name:

```bash
herdr agent start <id> --kind opencode --pane <pane-id> --timeout 60000 \
  -- --agent <the agent name from the developer ladder>
```

Add `--auto` to the trailing args when the user explicitly requests auto-approve
mode (the agent will auto-approve commands without prompting):

```bash
herdr agent start <id> --kind opencode --pane <pane-id> --timeout 60000 \
  -- --auto --agent <the agent name from the developer ladder>
```

Without `--auto`, the agent prompts the user before each command it runs.

**Confirm it took effect before prompting:**

```bash
herdr agent read <id> --source visible | grep -i 'Build ·'
```

If `--auto` was passed, verify it took effect:

```bash
herdr agent read <id> --source visible | grep -i 'auto.*approve'
```

Only `ham51/*` ids are the local endpoint; `opencode/*` is a hosted catalogue.

## Prompting and waiting

```bash
herdr agent prompt <id> "<the task text>" --wait --timeout 1800000
```

`--wait` returns on the first settled `idle`, `done`, or `blocked`.

**Always pass `--wait`.** Without it the command reports success whether or not
the text took effect.

**Timeouts:** `1800000` ms (30 min) for most tasks, `2400000` (40 min) for
tasks that run a test suite each iteration. Herdr's own documentation shows
`--timeout 120000`; that is for interactive questions, not for unattended work
against a local model.

### State meanings

| State | Meaning |
| --- | --- |
| `working` | Still running. Not a failure — extend the wait |
| `idle` / `done` | Settled and ready for input |
| `blocked` | Herdr recognized an approval or question UI. **Stop and ask the user** |
| `unknown` | An agent is present but unclassified. **Not proof of completion** |

If `agent prompt` returns `agent_prompt_stalled`, the prompt produced no observed
state change within five seconds — inspect with `agent get` and `agent read`.

### Polling instead of waiting

If you need to poll, send with `--wait --timeout 60000` first, confirm the agent
reached `working`, then poll from there.

```bash
herdr pane wait-output <pane-id> --regex '<pattern only a reply would match>' \
  --source visible --timeout 120000
```

## Detecting a hung agent

A stalled model endpoint is indistinguishable from a busy one at the lifecycle
layer. Herdr gives you the screen to check.

```bash
herdr agent read <id> --source visible | sed '$d' | md5sum
```

Same hash twice a minute apart, with `state_change_seq` unchanged, means hung —
not slow. Interrupt with `herdr agent send-keys <id> esc`.

`herdr agent read <id> --source visible` works while the agent is `working` and
returns the current viewport. `herdr agent read <id> --source recent-unwrapped --lines`
is refused while the agent is busy.

### `state_change_seq`

| Signal | During a hang | Useful? |
| --- | --- | --- |
| `agent_status` | `working`, forever | No |
| `state_change_seq` | frozen | **Yes** |
| md5 of viewport minus last line | stable | **Yes** |
| process CPU time | climbing ~0.45 of a core | No — busy-waits |

## Reading output

For a **settled** agent:

```bash
herdr agent get <id>
herdr agent read <id> --source recent-unwrapped --lines 200
```

For a **running** agent:

```bash
herdr agent read <id> --source visible
```

**Raising `--lines` often recovers nothing.** opencode runs on the terminal's
alternate screen. If a larger line count reveals no more, ask the agent to write
its summary to a file and read that.

## Committing and merging

Commit from **outside** the agent, so the agent never needs write access to git
metadata:

```bash
git -C <worktree-path> add -A
git -C <worktree-path> -c user.name=... commit -m "feat: ..."
```

**Check for contract violation** before merging:

```bash
git -C <worktree-path> diff --name-only HEAD~1
```

If the commit touches a file whose contents you pasted as the interface, the agent
changed what it was supposed to conform to. Never merge such a commit unread.

**Review the diff:**

```bash
git -C <worktree-path> diff HEAD~1
```

## Token accounting

herdr drives the opencode TUI, so there is no stream to parse for token data.
opencode records every session; `/opencode-agents` ships the reader:

```bash
python3 ../opencode-agents/scripts/opencode_agents.py tokens --agents-only --since 1
```

Both skills are side by side in every project's `.claude/skills/`, so that
relative path holds; from elsewhere, point at the ASST_BBMax copy.

Read `../opencode-agents/references/token-accounting.md` for the fields and
caveats — notably that the ledger is container-local, so a devcontainer rebuild
resets it.

## Teardown

```bash
herdr worktree remove --workspace <workspace-id>
```

Read `herdr worktree list` and `herdr agent list` to confirm cleanup.

## Session compaction

After a run is fully complete (all worktrees torn down, diffs reviewed, branches
merged), compact the session:

```
/compact
```

or for a different session:

```
/compact <sessionID>
```

Do not compact mid-run — you lose the ability to reference earlier agent output.

## Validation

Do not report a run complete until all four hold:

1. Every agent reached `idle`/`done` — never `blocked`, `unknown`, or still `working`.
2. Every diff has been read, and nothing sits in contract violation.
3. `herdr worktree list` shows none of the run's worktrees, and `herdr agent list`
   none of its agents.
4. No `herdr_*` branch is left holding unmerged work.

## Gotchas

- **Agents are not sandboxed.** `agent start` runs `opencode` with no wrapper
  hook. **The worktree is isolation by convention only**; keep every prompt
  scoped to relative paths.
- **The TUI rejects flags `opencode run` accepts.** `-- --variant low` makes
  opencode print its help and exit; `agent start` reports `timeout: timed out
  waiting for agent startup`. Pass only flags bare `opencode --help` lists.
- **Reasoning effort is stored per model, machine-wide.**
  `~/.local/state/opencode/model.json` holds the variant last picked in the TUI
  and silently outranks an agent's `variant` key. **Never select one in the
  TUI**, and never repoint a ladder agent at its plain twin.
- **Never start an agent with `pane run`.** Launching `opencode` yourself does
  not register an agent. `agent start` is the only supported path.
- **`agent start` needs an *available* shell pane.** A pane that already hosts
  an agent, or anything else in the foreground, returns `agent_pane_busy`.
- **`unknown` is not `done`.** It means an agent is present that Herdr could not
  classify. Treat it as unfinished.
- **CLI reads do not mark a tab seen.** Finished background work reports `done`
  rather than `idle`. Both are settled; neither needs action.
- **Worktrees live outside the repository**, under `~/.herdr/worktrees/`.
  `worktree remove` is this skill's job to clean them.
- **Branches are `herdr_*`, deliberately not `claude_*` or `worktree-*`.**
  `/projects-git-cleanup` sweeps only those two prefixes.
- **Uncommitted files are invisible to agents.** The worktree is cut from `HEAD`.

## Stop conditions

Stop and ask the user when:

- `HERDR_ENV` is unset, or the opencode integration is missing.
- Any agent reports `blocked`.
- The project tree is dirty at preflight. Offer `/commit2repo`; do not stash.
- A commit is in contract violation.
- Merging a `herdr_*` branch into main or pushing.

## Related

| Skill / File | Purpose |
| --- | --- |
| `/build-loop` | Workflow, roles, developer levels, loop orchestration |
| `/opencode-agents` | **Legacy.** Headless runner, supports `--sandbox`. Still ships the shared developer ladder (`levels`) and token reader (`tokens`) |
| `/commit2repo` | Merging and pushing a reviewed `herdr_*` branch |
| `/projects-git-cleanup` | Sweeps `claude_*` and `worktree-*` only — never `herdr_*` |