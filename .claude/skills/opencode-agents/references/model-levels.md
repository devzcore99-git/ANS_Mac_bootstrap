# The developer ladder

Read this when adding a model, when a level does not resolve, or when you need
to know exactly which of several model settings wins. For picking a rung on an
ordinary run, the table in SKILL.md is enough.

## Why a config file and not a model id

The endpoint serves several local models of different sizes. Naming them in a
`SKILL.md` or a task file makes every one of those files stale the moment a
model is added, replaced, or retired — and stale silently, because a wrong id
surfaces as a server error rather than as a config error (see the gotchas).

So the mapping from *developer level* to *model id* lives in one JSON file the
owner edits. Both `/opencode-agents` and `/herdr-agents` read it. Adding a model
is one edit there and nothing else.

## Where it lives

First file found wins:

1. `--levels-config PATH`
2. `$OPENCODE_MODEL_LEVELS`
3. `~/.config/opencode/model-levels.json`
4. `model-levels.json` bundled with this skill

(3) is the one to edit. It sits beside `opencode.jsonc`, where the provider and
the model ids already live, so the endpoint's facts stay in one place and one
edit reaches every project on the machine. (4) is the fallback that travels into
a devpod, a clone, or a container, where `~/.config` is not the host's — it is a
sane default, not the working copy.

An override that names a missing file is an error, not a reason to fall through
to (3) or (4): a typo'd path must not silently run the wrong model.

## The schema

```jsonc
{
  "default_level": "senior",

  "manager": {                                  // optional, and NOT a rung
    "model": "ham51/qwen3.8-27b-manager",
    "variant": "xhigh",
    "agent": null,                              // null: reached as opencode's default
    "summary": "27B dense, capped at 170K. ...",
    "context_limit": 170000
  },

  "levels": [
    {
      "level": "senior",                        // required, unique
      "aliases": ["sr"],                        // optional, also unique
      "model": "ham51/qwen3.8-27b",             // required, an id from `opencode models`
      "variant": "xhigh",                       // default reasoning effort; null = none offered
      "agent": "senior",                        // opencode agent carrying that default
      "agents": {                               // one agent per selectable effort
        "xhigh": "senior",
        "medium": "senior-medium",
        "low": "senior-low"
      },
      "summary": "27B dense. ...",              // shown by `levels`
      "use_for":   ["..."],
      "avoid_for": ["..."],
      "context_limit": 160000,                  // the task budget when nothing else sets one
      "timeout": 2400                           // per-task seconds, likewise
    }
  ]
}
```

`//` comments are stripped before parsing, as they are for `opencode.jsonc`.

**Array order is the ladder, most capable first.** There is no rank field to
keep in sync — insert a new model at its position and it is ranked. `levels`
reports a derived `rank` counting up from the junior end, for reading only.

A structural problem — no `levels` array, a level with no `model`, a duplicate
name, a `default_level` that resolves to nothing, a `manager` without a `model`
— fails immediately with exit 2, on any command that touches the file. A model
id that is not in `opencode models`, or an agent name opencode does not define,
does not: those are live-endpoint and live-config facts, so `levels` and `check`
report them in `problems` and exit 3 rather than blocking every other command.

## Why `manager` sits outside `levels`

It is the orchestrator seat, not a rung. On this endpoint the manager and the
senior rung resolve to the *same server-side model* (`coder-senior`); the only
difference is that the manager is capped shorter on purpose, so it stays quick
at prompt processing and is pushed to hand bulk reading to subagents. Promoting
a task from senior to manager would therefore buy no capability and cost 30K of
context — an escalation in name only.

Keeping it out of the array is what makes that structural rather than advisory.
Nothing in the script walks the ladder by position, so a fourth entry on top
would not break any code — it would mislead the *reader*, which is the thing
that actually decides to escalate, and it would make `--level manager` dispatch
task work to the narrowest window on the endpoint. `levels` reports it in its
own `manager` key, beside the ladder and never inside it.

## Reasoning effort: two mechanisms, because two runners

A level's `variant` is its default reasoning effort. How you *apply* it depends
entirely on which runner is dispatching, and the two do not share a mechanism:

| Runner | What it launches | How the effort is set |
|--------|------------------|-----------------------|
| `/opencode-agents` | `opencode run` | `--variant <name>`, a real flag; beats opencode's stored choice |
| `/herdr-agents` | the opencode TUI | `--agent <name>` from `agents`; the TUI has **no** `--variant` flag |

The asymmetry is not a style choice. The TUI rejects `--variant` outright: it
prints its help and exits, which surfaces through Herdr as `timeout: timed out
waiting for agent startup` and names neither the flag nor the cause.

There is a second trap behind the first. opencode persists the variant last
picked in its TUI to `~/.local/state/opencode/model.json`, keyed by model, and
**that stored choice beats an agent definition's `variant`** — silently. So an
agent whose definition says `low` runs at whatever is stored for its model, and
nothing on screen says so.

The ladder sidesteps it by pointing every agent at a `*-dispatch` model key —
identical to its twin, existing only so that no human ever selects it in the
TUI and it therefore never acquires a stored entry. Two rules follow:

- **Never select a `-dispatch` model in the TUI.** One interactive pick pins it
  and every dispatched agent on that rung silently changes effort.
- **Never repoint a ladder agent at the plain key** to remove a "duplicate".
  The duplication is the mechanism.

Note also that a model exposing exactly one variant does not default to it —
verified: a key whose only variant was `low` still ran with no variant at all.
An effort that is not named by an agent definition or a `--variant` flag is not
set, so `agents` must name every effort you intend to be reachable.

To verify what actually ran, read opencode's own record rather than the screen:

```bash
python3 - <<'EOF'
import sqlite3, json, pathlib
db = pathlib.Path.home() / ".local/share/opencode/opencode.db"
c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
for (data,) in c.execute("select data from message order by rowid desc limit 20"):
    d = json.loads(data)
    if d.get("role") == "assistant":
        print(d.get("agent"), d.get("modelID"), "variant=", d.get("variant"))
EOF
```

## Precedence

For the model actually used, most specific first:

1. per-task `"model"`
2. per-task `"level"`
3. `--model`
4. `--level`
5. the task file's top-level `"model"`
6. the task file's top-level `"level"`
7. the `"model"` key in `~/.config/opencode/opencode.jsonc`

A level also supplies `timeout` and `context_limit`, but only where nothing more
specific set them: an explicit `--timeout`, a task file default, or a per-task
`timeout` all still win. So `--level junior --model <a 27B id>` runs the 27B on
junior's budgets — legal, occasionally what you want, and worth saying out loud
if you do it.

## Mixed batches

Per-task `level` exists to mirror the per-task `model` key that already did, not
to encourage mixing. The endpoint keeps one model resident and loads others on
demand, so a batch naming two makes it unload and reload weights between tasks —
minutes of wall clock, not seconds. `dispatch` warns when it sees more than one
model in a batch. Split it into two runs.
