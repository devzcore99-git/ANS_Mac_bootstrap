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
  "levels": [
    {
      "level": "senior",                        // required, unique
      "aliases": ["sr"],                        // optional, also unique
      "model": "ham51-2/qwen/qwen3.8-27b",      // required, an id from `opencode models`
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
name, a `default_level` that resolves to nothing — fails immediately with exit
2, on any command that touches the file. A model id that is not in `opencode
models` does not: that is a live-endpoint fact, so `levels` and `check` report
it in `problems` and exit 3 rather than blocking every other command.

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
