# opencode agent definition files

Read this when an agent needs more than a system prompt — tool restrictions, a
different model, or per-agent permissions.

Field list from the official docs (<https://opencode.ai/docs/agents/>); the
behavioural notes are from testing on this machine.

## Location

| Path | Scope |
| --- | --- |
| `.opencode/agent/<name>.md` | The project, and every worktree cut from a commit containing it |
| `~/.config/opencode/agent/<name>.md` | Every project on the machine |

The directory is `agent`, singular — verified working. The published docs write
`.opencode/agents/` in one place; the singular form is what this opencode
build (1.18.15) actually reads.

The file stem is the agent name: `.opencode/agent/builder.md` is `--agent builder`.

## Frontmatter

| Field | Values | Default |
| --- | --- | --- |
| `description` | string | required |
| `mode` | `primary`, `subagent`, `all` | `all` |
| `model` | `provider/model-id` | the global config's model |
| `temperature` | 0.0–1.0 | model default |
| `permission` | map of tool → `allow` \| `ask` \| `deny` | inherits global config |
| `disable` | boolean | `false` |
| `steps` | integer | unlimited |
| `top_p` | 0.0–1.0 | — |
| `hidden` | boolean | `false` |
| `color` | hex or theme colour | — |

Body after the frontmatter is the system prompt.

### `mode` decides whether `opencode run` can use it

`opencode run --agent X` only accepts `primary` or `all`. Given
`mode: subagent` it prints `agent "X" is a subagent, not a primary agent.
Falling back to default agent`, runs its **default** agent instead, and exits
**0**. Omitting `mode` entirely is safe — the default is `all`.

The dispatcher reports this as `agent_mismatch`. Nothing else will.

### `permission` is enforced, but a denial blocks rather than fails

`--auto` auto-approves everything *except* what is explicitly denied, so this
works:

```yaml
permission:
  bash: deny
  edit: allow
```

Verified: with `bash: deny`, an agent instructed to `touch /tmp/pwned.txt` did
not create the file.

**But the run did not fail — it hung until the task timeout (exit 124).** A
denied tool call waits rather than erroring out. So:

- Always dispatch with a `--timeout` you are willing to wait (the default is
  1800s per task).
- Prefer shaping behaviour in the system prompt, and use `permission: deny` only
  for capabilities the agent genuinely must never have — expect a hung task, not
  a clean error, if it tries.

### `model` for a per-agent override

Setting `model:` in the agent file pins that agent regardless of the task file's
model. Leave it out unless you specifically want one agent on a different model
— the dispatcher's `--model` and the task file are the normal controls, and a
pinned agent silently ignores both.

## Useful agent shapes

**Builder** — the default; see `assets/agent-template.md`.

**Reviewer** — reads and reports, writes nothing:

```yaml
---
description: Reviews a change and reports findings without editing
mode: primary
temperature: 0.1
permission:
  edit: deny
---
```

Give a reviewer a task whose prompt asks for a written report to a named file,
and grant `edit` — otherwise it has no way to return anything the dispatcher can
commit, and the task lands as `no-changes`.

**Test-writer** — same as builder, but its prompt should state the test command
and the framework, since a small model will otherwise guess `pytest` in a repo
that uses something else.

## Checking what opencode sees

```bash
python3 scripts/opencode_agents.py --project PATH agents
```

Lists every definition with its scope, mode, and a `usable_with_run` flag.
`opencode agent list` also works but prints the whole resolved permission set
and is much noisier.
