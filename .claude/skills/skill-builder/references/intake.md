# Intake: extracting real expertise

The difference between a skill worth having and generic filler is entirely in
the input. This file is the checklist for getting that input fast.

## The rule

**Never write a skill body from the model's general knowledge alone.** If you
have no source of project-specific truth, you will produce "handle errors
appropriately" and "follow best practices" — content that costs context and
changes nothing.

If the requester hasn't supplied grounding material, get it before drafting.

## Fastest paths to real expertise

Ranked by speed and yield.

### 1. Mine what's already in the repo

Usually the fastest — no waiting on a human. Look for:

| Source | What it yields |
| --- | --- |
| Existing code in the target area | Actual conventions, naming, idioms |
| Config files, schemas, API specs | Concrete field names, types, required values |
| Internal docs, runbooks, style guides | Documented procedure and rationale |
| Code review comments, issue threads | Recurring reviewer concerns |
| Git history — especially fixes and patches | What actually goes wrong, revealed by what changed |
| Test files | Edge cases someone already thought about |
| CI config | The real gate a change must pass |

Fix-shaped commits are disproportionately valuable: each one is a mistake
somebody made, which is a gotcha waiting to be written down.

### 2. Extract from a hands-on task

If the requester just completed this task in conversation, harvest it:

- **Steps that worked** — the sequence that led to success.
- **Corrections made** — every "no, use X instead of Y" or "check for Z first".
  These become gotchas, and they are the highest-value content in the skill.
- **Input and output formats** — what the data looked like going in and out.
- **Context supplied by the human** — project facts, conventions and
  constraints the agent didn't already have.

### 3. Ask the requester

When the repo is silent, ask — but ask a short, high-yield set rather than an
interview. Five questions, answerable in a couple of minutes:

1. **Trigger** — "What would you have typed to make this skill fire? Give me
   two or three real phrasings."
2. **Correction** — "Last time an agent did this, what did you have to correct?"
3. **Non-obvious facts** — "What's true about this system that a competent
   person would guess wrong?"
4. **Definition of done** — "How do you know the output is right? Is there a
   command that checks it?"
5. **Boundaries** — "What should the agent *not* do here, and when should it
   stop and ask?"

Question 2 and 3 produce the gotchas section. Question 4 produces the validation
loop. Question 1 produces the description.

## Minimum viable context

Before drafting, you should be able to answer all of these. If any is blank,
that section of the skill will be filler — go get it or leave the section out.

- [ ] **Trigger phrasings** — 2–3 real user messages that should activate this.
- [ ] **Near-misses** — 1–2 adjacent tasks that should *not* activate it.
- [ ] **The procedure** — the actual steps, with the specific tools/commands.
- [ ] **At least one gotcha** — something the agent would get wrong unaided.
- [ ] **Done condition** — how correctness is verified.
- [ ] **Scope edges** — what's out of scope, when to stop and ask.

## Deciding whether the skill is worth building

Two questions worth asking before you write anything:

**Does the agent already do this well?** If yes, the skill adds context cost
for no gain. Test it: run the task unaided and look at the output. This is the
`without_skill` baseline from [evaluation.md](evaluation.md), and it's cheap to
run before committing to a skill.

**Is this one coherent unit?** If the answer to "what does this skill do"
requires an "and also", consider two skills. If it can only fire alongside
another skill, consider merging them.

## Choosing an archetype

| If the task is… | Archetype | Shape |
| --- | --- | --- |
| A few facts and a preferred approach | `minimal` | Instructions + example + gotchas |
| An ordered procedure with gates | `workflow` | Checklist + validation loop |
| Knowledge-heavy, most of it conditional | `reference` | Core rules + load-on-demand table |
| Fragile or batch operations | `script` | Plan → validate → execute |
| Judgement against a rubric | `review` | Dimensions + severity + output format |

Mixing is fine — these are starting shapes, not categories. A `workflow` skill
that grows a large lookup table should move it into `references/`.
