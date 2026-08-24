# Prompt Patterns Reference

Extends the four-pillar framework in
`KBX_AI_Prompts/Prompt_Engineering/Prompt_Engineering_Framework.md`
(Persona · Problem Definition · Delivery · Strategy) with the elements that
framework does not yet cover.

## Assembly order

Order matters. Put the ask early so the model knows what it is reading for,
and long reference material last.

1. **Role / persona** — only when it changes the answer. "You are a helpful
   assistant" is noise; "You are a tax attorney reviewing for filing risk" is
   a lens.
2. **Task** — the specific action, stated in one or two sentences, up front.
3. **Context** — background needed to do the task well.
4. **Constraints** — hard requirements, soft preferences, and explicit
   prohibitions.
5. **Examples** — one to three, showing input → desired output.
6. **Output format** — structure, length, medium.
7. **Uncertainty handling** — what to do when information is missing.
8. **Input data** — the material to operate on, last, inside delimiters.

## What the base framework covers

- **Persona**: role and audience calibration
- **Problem Definition**: problem, background, hard/soft constraints,
  examples, success criteria, edge cases
- **Delivery**: tone, length, priority areas, reasoning approach, format
- **Strategy**: clarifying questions first, alternatives, iterative refinement

## Additions

### Negative constraints

State what *not* to do, not only what to do. Models over-produce by default:
preambles, summaries of what they just said, caveats, offers to help further.

> Do not restate the question. Do not add a closing summary. If a section has
> no findings, omit it rather than writing "none found".

### Uncertainty handling

The single highest-value addition for factual work. Without it, a model fills
gaps plausibly.

> If the provided material does not contain the answer, say so explicitly
> rather than inferring. Mark any assumption you make as an assumption.

### Input data placement and delimiting

Put long reference material at the end, wrapped in delimiters, and say what
the delimiters mean. XML-style tags work well across models.

> Analyze the transcript below. Quote only from inside the tags.
> `<transcript>...</transcript>`

### Grounding

When the model must not use its own knowledge:

> Answer only from the provided sources. If they conflict, say so and quote
> both. Do not supplement with outside knowledge.

### Structured output

Give the exact shape, not a description of it. A literal skeleton beats prose
every time. State what happens to fields with no value, or you get invented
ones.

### Examples (few-shot)

The highest-leverage element for tone, format, and edge-case handling — often
worth more than several paragraphs of instruction. Two or three contrasting
examples beat one. Include a hard case, not only the easy one.

### Reasoning guidance

- Analysis, math, multi-step logic → ask for reasoning before the answer.
- Simple extraction, classification, formatting → do **not**; it adds latency
  and can talk the model out of a correct first instinct.
- When reasoning is wanted but should not clutter output, ask for it in a
  separate section that the reader can skip.

### Success criteria

Give the model the bar it will be judged against. It measurably steers output.

> A good answer identifies the specific clause, not the general topic, and
> cites the section number.

### Target-model tailoring

- **Long context** → material at the end, question at both start and end.
- **Reasoning models** → state the goal and constraints; do not micro-manage
  the steps.
- **Embedded in code** (API, agent, tool) → deterministic and format-strict;
  no conversational framing, since no human reads the reply.

## When one prompt is the wrong tool

Some tasks do not get better with a better prompt. Recognizing this early
saves more time than any wording change.

**Split into chained prompts when:**

- The task has **distinct phases needing different modes** — research, then
  design, then critique. One prompt averages them and does all three
  adequately rather than any of them well.
- Output from step one **changes what step two should ask**. A single prompt
  cannot branch.
- The input **exceeds what the model can attend to reliably**. Chunk, process
  each, then synthesize.
- You need **independent judgment** — a critique of a draft produced in the
  same response is anchored by having just written it. Fresh context is a
  genuinely different reviewer.
- The output is **long and structured** — a report, a codebase. Section by
  section beats one attempt at everything.

**Keep it as one prompt when:** the phases are genuinely interdependent, the
task fits comfortably in context, or chaining adds handoff overhead that
exceeds the quality gain.

**Chaining shapes:** *pipeline* (each output feeds the next) · *fan-out then
synthesize* (independent passes, then merge) · *generate then critique*
(separate call, so the critic is not defending its own work).

Say so plainly when a request needs decomposition, and describe the chain —
do not quietly deliver one overloaded prompt that will underperform.

## Failure → fix

When a prompt underperforms, the fix is usually specific. Diagnose from the
symptom rather than rewording and hoping.

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| Too long, padded | No length constraint; models default to thorough | Give a hard limit *and* name what to cut: "no preamble, no closing summary" |
| Ignored the format | Format described in prose, or stated before a long input | Show a literal skeleton; restate the format requirement at the end |
| Invented facts | No failure path | Add explicit uncertainty handling and, if applicable, ground it: "only from the provided sources" |
| Generic, could apply to anything | Missing audience and success criteria | Name the reader and what a good answer does that a mediocre one does not |
| Right content, wrong tone | Tone described abstractly | Supply one example in the target register — worth more than any adjective |
| Hedges everything | No stance requested; caveats are the safe default | "Commit to a recommendation. State the strongest objection once, then move on." |
| Good start, drifts by the end | Long prompt, key constraint stated only once and early | Repeat the critical constraint at the end; late instructions carry weight |
| Inconsistent across runs | Ambiguity the model resolves differently each time | Find the underspecified decision and make it explicit — that is the real bug |
| Refuses or over-qualifies | Request reads riskier than intended | State the legitimate context and the actual use |
| Followed instructions, missed the point | Prompt specified process, not goal | State the outcome wanted, not only the steps |

Two rules when iterating: **change one thing at a time**, or you will not know
what worked. And **fix the prompt, not the output** — patching a specific
answer leaves the same failure waiting next run.

## Anti-patterns

| Pattern | Why it fails |
|---------|--------------|
| "Act as an expert…" with nothing else | Persona without task or constraints changes little |
| Politeness padding ("please", "thank you") | Consumes tokens, changes nothing |
| Stacked superlatives ("VERY IMPORTANT!!!") | Emphasis on everything is emphasis on nothing |
| Contradictory instructions | "Be thorough but brief" — pick one, or state the tradeoff |
| Describing format instead of showing it | Show a literal skeleton |
| No failure path | Guarantees confident invention when data is missing |
| Everything in one paragraph | Structure the prompt; models attend to structure |
