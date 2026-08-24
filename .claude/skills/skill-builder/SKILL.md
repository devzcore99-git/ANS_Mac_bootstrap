---
name: skill-builder
description: >-
  Create, scaffold, and validate Agent Skills in the standard SKILL.md format
  (agentskills.io) — choose an archetype, write frontmatter that triggers
  reliably, structure the body for progressive disclosure, bundle scripts and
  references, and check the result against the spec. Use when the user wants to
  build, write, generate, scaffold, refactor, review, or fix an agent skill, a
  SKILL.md, or a reusable capability for an AI agent — including when they
  describe packaging a procedure, runbook, convention set, or repeated workflow
  so an agent can reuse it, even if they never say the word "skill".
metadata:
  source: https://agentskills.io/specification
---

# Skill Builder

A framework for producing Agent Skills quickly without producing worthless
ones. The speed comes from the scaffolding and the validator; the quality comes
from refusing to draft before you have real, specific source material.

## The loop

1. **Ground** — gather real expertise (never draft from general knowledge)
2. **Scaffold** — pick an archetype, generate the directory
3. **Draft** — write the body under the context budget
4. **Validate** — run the checker until clean
5. **Prove** — test triggering and output quality

Steps 1–4 are the fast path and should take one pass. Step 5 is where a good
skill becomes a reliable one; do it for any skill that will be used repeatedly.

---

## Step 1 — Ground the skill in real expertise

**This is the step that determines whether the skill is worth anything.** A
skill generated from the model's general knowledge produces text like "handle
errors appropriately" — it costs context and changes no behaviour.

Before drafting, you must be able to answer all six:

- [ ] 2–3 **real trigger phrasings** the user would type
- [ ] 1–2 **near-misses** that should *not* activate the skill
- [ ] The **actual procedure** — steps with specific tools, commands, libraries
- [ ] At least one **gotcha** — something an agent gets wrong unaided
- [ ] The **done condition** — how correctness is verified
- [ ] **Scope edges** — what's out of scope, when to stop and ask

Sources, fastest first: mine the repo (code, configs, schemas, runbooks, review
comments, and especially fix-shaped commits), extract from a task the user just
completed (their corrections are your gotchas), or ask them five short
questions. Read [references/intake.md](references/intake.md) for the question
set, the source-material table, and how to judge whether the skill is worth
building at all.

If you cannot fill a box, either go find it or leave that section out of the
skill. Do not fill it with plausible-sounding generic text.

## Step 2 — Pick an archetype and scaffold

| The task is… | Archetype | Template |
| --- | --- | --- |
| A few facts plus a preferred approach | `minimal` | [assets/templates/minimal.md](assets/templates/minimal.md) |
| An ordered procedure with gates | `workflow` | [assets/templates/workflow.md](assets/templates/workflow.md) |
| Knowledge-heavy, mostly conditional | `reference` | [assets/templates/reference.md](assets/templates/reference.md) |
| Fragile, batch, or destructive operations | `script` | [assets/templates/script.md](assets/templates/script.md) |
| Judgement against a rubric | `review` | [assets/templates/review.md](assets/templates/review.md) |

The `reference` archetype also drops a `REFERENCE.md` stub into the new skill's
`references/` directory, from
[assets/templates/reference-doc.md](assets/templates/reference-doc.md).

Generate the skeleton:

Paths below use `$SKILL_DIR` — the base directory printed when this skill
loads. It is not a real environment variable: substitute the printed path, or
set it inline in the same command (`SKILL_DIR=... python3 "$SKILL_DIR/..."`),
because shell state does not persist between calls. This is what lets the
commands run from any project, whether the skill lives in a repository or is
symlinked into `~/.claude/skills/`.

```bash
python3 $SKILL_DIR/scripts/new_skill.py \
  --name <skill-name> \
  --description "<what it does. Use when <trigger>.>" \
  --template workflow \
  --out-dir .claude/skills
```

Paths are written from the repository root, which is where these commands are
run. `--out-dir .claude/skills` puts the new skill where Claude Code discovers
it, alongside this one.

Add `--with-evals` to also create `evals/evals.json` from
[assets/templates/evals.json](assets/templates/evals.json). Run
`python3 $SKILL_DIR/scripts/new_skill.py --help` for all
options.

The generated `SKILL.md` is a skeleton full of `<angle-bracket>` placeholders.
**Every one must be replaced or deleted** — a shipped skill containing
`<Another.>` is worse than no skill.

## Step 3 — Draft the body

Read [references/authoring.md](references/authoring.md) before writing the
first draft, and [references/spec.md](references/spec.md) if you are unsure
about any frontmatter constraint.

The rules that matter most, in order:

**Write only what the agent lacks.** For every line, ask: *would the agent get
this wrong without it?* If no, cut it. Don't explain what a PDF is, how HTTP
works, or what a migration does. Jump straight to the specific library, the
specific endpoint, the specific convention.

**Gotchas earn their space.** A section of concrete, environment-specific facts
that defy reasonable assumptions is usually the highest-value part of a skill:

```markdown
- The `users` table uses soft deletes. Queries must include
  `WHERE deleted_at IS NULL` or results include deactivated accounts.
- The `/health` endpoint returns 200 as long as the web server is running,
  even if the database is down. Use `/ready` for real service health.
```

Keep gotchas in `SKILL.md`, not a reference file — the agent must read them
before it hits the situation, and it won't know to go look.

**Provide defaults, not menus.** Pick one approach, mention alternatives in a
clause. "Use pdfplumber; for scanned PDFs use pdf2image with pytesseract"
beats listing four libraries as equals.

**Teach a method, not an answer.** "Join the `orders` table to `customers` on
`customer_id`" is useful once. "Read the schema, join on the `_id` foreign key
convention, apply the user's filters as WHERE clauses" is useful forever.

**Match specificity to fragility.** Be prescriptive where a sequence must be
exact ("run exactly this command; do not add flags"). Give latitude and explain
*why* where several approaches work — an agent that understands the purpose
makes better context-dependent calls.

**Stay under budget.** 500 lines and ~5,000 tokens for `SKILL.md`. Past that,
move detail into `references/` **with an explicit trigger** for each file:
"Read `references/<topic>.md` if the API returns a non-200 status" — never
"see the references directory for details."

**Write the description last.** By then you know what the skill actually does.
Shape: *what it does, specifically* + *"Use when …"* + *the keyword-free
phrasings that should still trigger it*. See
[references/descriptions.md](references/descriptions.md) for the full pattern
and the trigger-eval loop.

If the skill needs bundled code, read
[references/scripts.md](references/scripts.md) first — agent-facing scripts
have hard requirements (never prompt interactively, `--help` is the interface,
errors must enable the next attempt, structured output to stdout and
diagnostics to stderr).

## Step 4 — Validate

```bash
python3 $SKILL_DIR/scripts/validate_skill.py .claude/skills/<skill-name>
```

Fix every error and read every warning. Add `--json` for machine-readable
output, `--strict` to fail on warnings, and `--all .claude/skills` to check
every skill in this repository at once. Exit codes: `0` clean, `1` violations,
`2` usage error.

**Errors** (spec violations): missing or malformed frontmatter; `name` outside
`^[a-z0-9]+(-[a-z0-9]+)*$` or not matching the directory; `description`
missing, empty, or over 1024 chars; `compatibility` over 500 chars; non-scalar
`metadata` values; empty body; references to files that do not exist;
unreplaced `<angle-bracket>` placeholders left in prose.

**Warnings** (quality signals): thin descriptions; descriptions with no
explicit trigger clause; body over 500 lines or ~5,000 tokens; bundled files
never referenced from `SKILL.md`; misnamed directories; unknown frontmatter
fields; non-executable shell scripts.

Discovery under `--all` is case-sensitive: a directory whose file is named
`skill.md` rather than `SKILL.md` is skipped silently.

Warnings are not automatically wrong — an unreferenced asset may be
intentional — but each one should be a decision, not an oversight.

## Step 5 — Prove it works

Two independent things can be broken: the skill never fires, or it fires and
produces mediocre output. Test them separately.

**Triggering** — build ~20 labelled queries (8–10 positive, 8–10 near-miss
negatives), measure trigger rate over 3 runs each, and optimize the description
against a train/validation split. Full method in
[references/descriptions.md](references/descriptions.md).

**Output quality** — run each test case *with* and *without* the skill. The
baseline is the entire argument: if the unaided agent scores the same, the
skill is costing context for nothing. Write assertions after seeing the first
results, grade with evidence, and feed failed assertions plus execution
transcripts back into a revision. Full method in
[references/evaluation.md](references/evaluation.md).

---

## Hard rules

- **`name` must equal the directory name.** Lowercase, digits, single hyphens.
- **Never ship placeholder text.** No `<angle brackets>`, no "TODO", no
  "adjust as needed" left in the final file.
- **Never invent domain facts.** If you don't know the real endpoint, table
  name, or command, ask or go read the code. A confidently wrong gotcha is
  worse than a missing one.
- **One coherent unit per skill.** If describing it needs an "and also", split
  it. If it can only fire alongside another skill, merge them.
- **Don't build a skill the agent doesn't need.** If the unaided agent already
  does the task well, say so instead of shipping context bloat.

## Gotchas

- The frontmatter fence must be the **very first line** of the file — a blank
  line or BOM before `---` breaks parsing in most clients.
- `description` is the *only* thing loaded at startup. Everything you rely on
  for activation must be in it; nothing in the body affects triggering.
- Agents skip skills for tasks they can already handle in one step. A perfect
  description won't make "read this PDF" trigger a PDF skill — descriptions
  earn their keep on unfamiliar APIs, domain workflows, and uncommon formats.
- `metadata` values must be scalars. Nested maps and lists are not portable.
- `allowed-tools` is space-separated, not comma-separated, and support varies
  by client — treat it as advisory.
- Bundled files the body never mentions are invisible to the agent. The
  validator warns about these; it is usually a real bug.
- `assets/templates/*.md` here are templates, not skills — they intentionally
  contain placeholders and will fail validation if run through it directly.

## Bundled files

| File | Purpose |
| --- | --- |
| [references/intake.md](references/intake.md) | Question set and source-material checklist for step 1 |
| [references/spec.md](references/spec.md) | Normative format spec — frontmatter fields, limits, layout |
| [references/authoring.md](references/authoring.md) | How to write the body: context economy, control calibration, instruction patterns |
| [references/descriptions.md](references/descriptions.md) | Description shape and the trigger-eval optimization loop |
| [references/scripts.md](references/scripts.md) | When to bundle scripts and how to design them for agents |
| [references/evaluation.md](references/evaluation.md) | Test cases, assertions, grading, benchmarks, iteration |
| `scripts/new_skill.py` | Scaffold a skill directory from an archetype |
| `scripts/validate_skill.py` | Check a skill against the spec |
| `scripts/frontmatter.py` | Shared YAML frontmatter reader used by both scripts |

## Completion checklist

- [ ] Every `<placeholder>` replaced or removed
- [ ] `name` matches the directory; frontmatter passes validation
- [ ] `description` states what it does *and* when to use it, under 1024 chars
- [ ] At least one real gotcha, sourced from actual experience
- [ ] A worked example with realistic input and expected output
- [ ] A done condition the agent can check
- [ ] `SKILL.md` under 500 lines; overflow moved to `references/` with triggers
- [ ] Every bundled file referenced from `SKILL.md`
- [ ] `validate_skill.py` exits 0
