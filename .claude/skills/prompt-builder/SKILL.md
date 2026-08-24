---
name: prompt-builder
description: Turn a one-line idea into a well-engineered prompt for an LLM, by interviewing the user about audience, format, and constraints. Use when the user wants help writing a prompt, improving a prompt, or getting better results from an AI.
---

# Prompt Builder

The user gives a sentence or two about what they want an AI to do. You ask the
questions that separate a vague prompt from a precise one, then produce a
finished prompt they can paste into another LLM.

## Output format — the hard requirement

The user copies the prompt into a different chat window. It must be cleanly
liftable.

- The prompt goes **inside a fenced code block, alone**. Nothing else in that
  block — no commentary, no headings, no "here's your prompt".
- **"Why it works" goes after the block**, never inside it and never
  interleaved.
- Do not wrap the prompt in quotes or prefix each line.
- If the prompt itself contains fenced code, use more backticks on the outer
  fence so the inner block survives.

## Process

### 1. Read the request

Judge complexity from what they gave you, and scale the interview:

| Complexity | Looks like | Rounds |
|-----------|-----------|--------|
| Simple | Summarize, rewrite, draft, brainstorm | One round, 3–4 questions |
| Moderate | Analysis, structured output, specific audience | One round, 4–5 questions |
| Complex | Agent/system instructions, multi-step reasoning, grounded on supplied sources, strict schema | Two rounds |

Do not pad a simple request into a long interview. Do not compress a system
prompt into three questions.

### 2. Ask what you cannot infer

Use `AskUserQuestion`. Prioritize the gaps that most change the output:

1. **Audience and purpose** — who reads the result, and what do they do with it
2. **Output format and length** — the most common cause of a disappointing answer
3. **Constraints and prohibitions** — including what the model should *not* do
4. **Uncertainty handling** — what happens when the model lacks the facts
5. **Where it runs** — one-off chat, reusable template, or embedded in code

Never ask what they already told you. If the overview names the audience,
skip that question and spend it elsewhere.

### 3. Build the prompt

Follow the assembly order and element checklist in `prompt-patterns.md`.
Load it before writing — it carries the framework this skill is built on plus
the anti-patterns to avoid.

Include only elements that earn their place. A prompt with a pointless persona
and empty ceremony is worse than a short direct one. Every line should change
the output.

### 4. Deliver

The fenced prompt, then a **short** rationale — three to five bullets on the
decisions that matter and what to adjust if the result misses. Not a
line-by-line explanation.

Then offer to save it.

### 5. If they come back unhappy

Diagnose from the symptom using the *Failure → fix* table in
`prompt-patterns.md`. Ask what the output actually did wrong — too long, wrong
format, invented facts, too generic — rather than rewriting blind.

Change one thing at a time, and fix the prompt rather than the output. A
patched answer leaves the same failure waiting for the next run.

## When a single prompt is the wrong answer

Some requests do not improve with better wording — they need to be split
across several prompts. `prompt-patterns.md` covers the signals and the
chaining shapes.

Say so plainly when you see it, and sketch the chain. Do not quietly hand back
one overloaded prompt that will underperform.

## Saving

Paths below use `$SKILL_DIR` — the base directory printed when this skill
loads. It is not a real environment variable: substitute the printed path, or
set it inline in the same command (`SKILL_DIR=... python3 "$SKILL_DIR/..."`),
because shell state does not persist between calls. This is what lets the
commands run from any project, whether the skill lives in a repository or is
symlinked into `~/.claude/skills/`.

```bash
python3 $SKILL_DIR/prompt.py --save "<Name>" --why "<rationale>" < <(cat)
python3 $SKILL_DIR/prompt.py --save "<Name>" --force < <(cat)   # overwrite
python3 $SKILL_DIR/prompt.py --list
python3 $SKILL_DIR/prompt.py --show <slug>          # body only
python3 $SKILL_DIR/prompt.py --show <slug> --full   # with rationale
```

Pipe the prompt body on stdin — a heredoc is usually easiest. Saved prompts
land in `prompts/` at the root of whichever repository this skill is installed in. `--show <slug>` prints the body alone, so
retrieving a stored prompt to reuse costs nothing extra.

`--save` refuses to clobber an existing prompt (exit `3`). Names differing only
in case or punctuation slugify to one file, so "Weekly Report" and
"weekly-report" are the same destination; save under a different name, or pass
`--force` when overwriting is the intent. Other exit codes: `0` success, `2` no
prompt body on stdin.

## Rules

**Write for the model, not the user.** The output is an instruction to an LLM.
Skip pleasantries, motivation, and explanation of why the user wants it.

**Prefer showing over describing.** A literal output skeleton beats a
paragraph describing the format.

**Always include a failure path** for anything factual — what to do when the
information is not available. Its absence is the most common cause of
confident invention.

**Do not invent domain facts.** If the task needs specifics you do not have —
a schema, a house style, real examples — leave a clearly marked
`[FILL IN: ...]` placeholder rather than fabricating something plausible the
user might not notice.

## Notes

- Requires Python 3.7+, standard library only, all three platforms.
- `prompt-patterns.md` extends
  `KBX_AI_Prompts/Prompt_Engineering/Prompt_Engineering_Framework.md`, which is
  unmodified. Update the reference file to change how prompts get built — do
  not special-case guidance here.
