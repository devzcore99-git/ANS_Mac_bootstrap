---
name: prd-builder
description: Interview the user to produce a comprehensive Product Requirements Document that an LLM agent can build software from. Use when the user wants to write a PRD, plan a new project, spec out software, or turn a rough idea into a buildable plan.
---

# PRD Builder

The user brings a high-level idea. You interview them section by section and
produce a PRD complete enough that an implementing agent does not have to
guess. Drafts live in `plans/` at the root of whichever repository this skill is
installed in — `ASST_BBMax/plans/` when run from there. They are versioned whether or
not the target project exists yet.

## Process

### 1. Get the overview

If the user has not already given one, ask for a few sentences on what they
want to build and why. Do not start questioning until you have it — the
overview determines which sections matter.

### 2. Create the draft

Paths below use `$SKILL_DIR` — the base directory printed when this skill
loads. It is not a real environment variable: substitute the printed path, or
set it inline in the same command (`SKILL_DIR=... python3 "$SKILL_DIR/..."`),
because shell state does not persist between calls. This is what lets the
commands run from any project, whether the skill lives in a repository or is
symlinked into `~/.claude/skills/`.

```bash
python3 $SKILL_DIR/prd.py --new "<Project Name>"
```

Prints the path it created. Resuming instead? See *Resuming* below.

### 3. Interview, one section at a time

Work through the template in order. For each section:

1. Ask **2–5 related questions at once** — enough to settle the section, few
   enough to answer in one sitting.
2. Use `AskUserQuestion` when the answer space is enumerable (interface type,
   target platforms, language, packaging). Use open prose for anything
   descriptive — problem statements and feature behavior do not fit
   multiple choice.
3. **Write the section to the file immediately** once settled, then move on.
   Never hold several sections in your head — an interrupted session must
   lose nothing.
4. Summarize what you wrote in a line or two so the user can correct it before
   you move on.

Section 3 (Functional Requirements) is the largest. Expect several rounds —
one per feature — and do not compress it to save time. It is the section an
implementing agent leans on hardest.

### 4. Review

When every section is filled, show the completion table
(`prd.py --status <slug>`), then walk the user through anything in
§16 Open Questions. Offer to move the PRD into the target project.

## Rules

**Do not invent requirements.** The point of the document is to capture what
the user actually wants. When they say "you decide", make a recommendation
*with a one-line rationale*, mark it in §14.1 Assumptions, and move on — an
implementing agent must be able to tell a decision from a guess.

**Mark non-applicable sections `N/A` with a reason**, rather than leaving
placeholder text. A PRD for a single-file CLI does not need a data model, but
the reader needs to know that was a decision, not an omission.

**Push on vagueness in three places specifically**, because they are where
implementing agents most often go wrong:

- §2.3 Non-Goals — an empty non-goals list means unbounded scope
- §2.4 Success Metrics — "works well" is not verifiable
- §11 Edge Cases — ask what happens on empty input, network failure, and
  concurrent runs at minimum

**Anything unresolved goes to §16**, never into a plausible-sounding guess in
the body.

## Resuming

```bash
python3 $SKILL_DIR/prd.py --list             # all drafts + progress
python3 $SKILL_DIR/prd.py --status <slug>    # per-section table
python3 $SKILL_DIR/prd.py --next   <slug>    # first unfilled section
```

Read only the section you are resuming, not the whole file. Sections are
"unanswered" when they still contain `<angle bracket>` placeholders or bare
`- Label:` prompts, so progress is derived from the file itself and survives
any gap between sessions.

## Template

`prd-template.md` — 16 sections. Extends the original in
`CODE_Claude_Setup/PRD.md` (which is unmodified) with: Prior Art (1.5),
Success Metrics (2.4), Interface & UX (4), Target Platforms (6.1), External
Dependencies & Credentials (7), Data Lifecycle (9.2), Deployment &
Distribution (10), and Risks & Assumptions (14).

Edit the template to change the shape of future PRDs — do not special-case it
in this file.

## Notes

- Requires Python 3.7+, standard library only. Runs on all three platforms.
- The script never edits an existing PRD; you write sections with Edit. It
  only scaffolds and reports progress, so a partially-written PRD is never at
  risk of being overwritten.
- `--new` refuses to clobber an existing draft (exit 3).
