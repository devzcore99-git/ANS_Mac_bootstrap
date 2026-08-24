---
name: eli5
description: >-
  Re-explain what was just printed at a lower technical altitude — plainer words, same
  facts, shorter. Not baby talk: it drops a level or two of jargon, it does not rewrite
  for a literal five-year-old. Use when the user asks to explain it like they are five,
  wants something dumbed down, simplified, put in plain English or layman's terms, or
  pitched at a higher level — including bare phrasings like 'eli5', 'in English?', 'what
  does that actually mean', or 'I didn't follow any of that'. The target is whatever the
  last output was: Claude's own answer, a skill's report, or a command's stdout. Not for
  writing documentation, and not for a first explanation of code the user points at — that
  is ordinary work, not a re-explanation.
---

# ELI5

Say the last thing again, one or two levels less technical. Same facts, plainer
words, fewer of them. The name is the internet idiom, not a literal
instruction — the audience is an intelligent adult who does not work in this
particular corner, not a child.

## The calibration

This is the whole skill. Get the dial wrong and the answer is useless in one of
two directions.

| Drop | Keep |
| --- | --- |
| Jargon, tool names, and internal mechanism | What happened, and what it means for the user |
| Precise-but-irrelevant detail (exit codes, flags, class names) | Every name, number, path, and command the user needs to act |
| Hedges and caveats that do not change the decision | The decision, stated as a decision |
| Sequencing the user never has to perform | Sequencing they do — "commit first, then push" |

Aim one level down, not five:

- **Too far:** "Think of your project like a toy box, and Git is the helper who
  remembers where all the toys go!"
- **About right:** "Your changes are saved on this machine but never sent to
  GitHub, so the other computer can't see them yet."
- **Not far enough:** "The local ref is ahead of its upstream tracking branch."

Analogies are allowed when they carry real weight, one at most, and never
about something the user obviously already understands.

## How to do it

1. **Pick the target.** Normally the last substantive output — the report, the
   answer, the command's stdout. Not the closing "let me know if you'd like…"
   line. If the user quotes or points at one part, that part is the target.
2. **Work from what is already in context.** Do not re-run the command, re-read
   the files, or re-do the analysis. Nothing new is being computed; this is a
   restatement.
3. **Lead with the bottom line** in one sentence — what it means or what to do.
   Details after, and only if there is more than one.
4. **Keep the real term when the user will need to say it back**, and gloss it
   once in parentheses: "a rebase (replaying your commits on top of theirs)".
   Renaming it to something friendlier leaves them unable to search for it or
   ask about it.
5. **Stop when it is shorter than the original.** If the plain version is
   longer, it is not a plain version.

Asked again on an answer that already went through this, go one level lower
still and rewrite from scratch — do not repeat the same sentences louder.

## Example

Original output:

```
CODE_StockGenIndicators: 3 ahead of origin/master, tree dirty (4 modified).
  claude_add-rsi merged, not deleted.
ASST_BBMax: diverged — 2 local / 1 remote. Fast-forward refused.
```

ELI5:

```
Two projects need a minute of your time.

CODE_StockGenIndicators has work saved on this machine that never made it
to GitHub, plus four files edited and not saved at all. Save those, then
send everything up. It also has a finished branch, claude_add-rsi, whose
work is already folded in — safe to delete.

ASST_BBMax is the awkward one. It changed here and it also changed
somewhere else, probably your other machine, so Git won't pick a winner on
its own. Save what's here first, then reconcile the two.
```

Note what survived: both project names, the branch name, the file count, and
the order of operations. What went: "ahead of origin/master", "dirty",
"diverged", "fast-forward".

## Gotchas

- **Do not fix the original while simplifying it.** If a claim in it was wrong,
  the plain-language version quietly becoming right hides a correction the user
  needs to see. Say what changed, in a sentence, then give the simple version.
- **Do not add new findings.** Reaching for a fresh detail means re-doing the
  work, and the user is now reading two different answers to the same question.
  If something genuinely important was left out, say so separately.
- **A wall of text is not simpler than a table.** Prose is usually right for
  this, but if the original was a table because it held parallel rows of facts,
  keep the table and simplify the cells.
- **Code blocks rarely belong here.** The exception is a single command the
  user should run — that is the actionable part, so it stays verbatim.
- **The output may have come from a script, not from Claude.** A skill's report
  or a command's stdout is a perfectly normal target; explain what it says
  without re-running it.

## Availability in other projects

Installed by copy, not by symlink. `eli5` is listed in `bundled_skills` in
`skills_config.json`, so `/project-bootstrap` writes a real directory into
every project's own `.claude/skills/`:

```bash
# whole workspace
python3 .claude/skills/project-bootstrap/bootstrap.py --deploy-skills
# one project
python3 .claude/skills/project-bootstrap/bootstrap.py NAME --skills-only
```

A symlink into `~/.claude/skills/` was the earlier mechanism and was wrong for
the way these projects are actually run: most of them open in a devpod, where
`~/AI_Projects` does not exist and the link resolves to nothing. The same holds
in a fresh clone, in CI, and on Windows. A copy travels inside the repository,
which is the only thing a devpod is guaranteed to have.

Its `exclude_prefixes` is empty, unlike the coding-agent skills: a `KBX_`
knowledge base or a `PRJ_` directory benefits from plainer explanations exactly
as much as a code repository does.

The cost of copying is drift. `--audit-skills` reports any project whose copy
no longer matches this one, and `--update-skills` refreshes it.
