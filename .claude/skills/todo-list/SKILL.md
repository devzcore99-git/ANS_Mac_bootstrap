---
name: todo-list
description: List the current project's TODOs from its TODOs.md as a table, filtered by section or status. Use when the user asks to see the TODO list, project TODOs, backlog, or what is outstanding.
---

# TODO List

Renders the TODO list of the project this skill is installed in — `TODOs.md` at the repository root, resolved relative to the skill's own
location, so a copy inside a project reads that project's file. The script parses, filters, counts, and formats —
**print its output directly**. Do not read `TODOs.md` to answer a list request,
and do not retype the items into your own table; that doubles the token cost
for no gain.

## Run

Paths below use `$SKILL_DIR` — the base directory printed when this skill
loads. It is not a real environment variable: substitute the printed path, or
set it inline in the same command (`SKILL_DIR=... python3 "$SKILL_DIR/..."`),
because shell state does not persist between calls. This is what lets the
commands run from any project, whether the skill lives in a repository or is
symlinked into `~/.claude/skills/`.

```bash
# macOS / Linux
python3 $SKILL_DIR/list-todos.py

# Windows
python $SKILL_DIR/list-todos.py
```

| Option | Effect |
|--------|--------|
| *(none)* | Open items, grouped by section |
| `--all` | Include completed (shown struck through) |
| `--done` | Completed only |
| `--section <text>` | Sections matching a substring, case-insensitive |
| `--counts` | Per-section open/done totals, no item text |
| `--detail` | Add the Detail column (the text after `Name - `) |
| `--json` | Machine-readable, for further processing |
| `--file <path>` | Point at a different TODO file |

Reach for `--counts` when the user wants a status check rather than the list,
and `--section` when they name one area — both avoid pulling every item into
context.

## Editing

This skill is **read-only**. To add, complete, or reorganize items, edit
`TODOs.md` directly with Edit — it is a small file and the structure is
hand-maintained. Keep the existing conventions:

- Sections are `## Heading`; items are `- [ ]` / `- [x]`
- Write items as `Name - detail` so the Detail column works
- Completed items move to the `## Completed` section rather than being
  struck through in place

## Notes

- Requires Python 3.7+ and nothing outside the standard library.
- The parser keys on `##` headings and `- [ ]` checkboxes, so new sections are
  picked up automatically with no change here.
- Numbers in the table are display positions for the current filter, not
  stable IDs. Do not use them to refer to items across runs.
- "TODOs" here means this project's `TODOs.md`. Personal tasks live in Google
  Calendar and TickTick — see `.claude/rules/calendars-tasks.md`.
