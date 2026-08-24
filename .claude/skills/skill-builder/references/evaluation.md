# Evaluating skill output quality

A skill that "seemed to work once" is untested. Evals answer whether it works
reliably, across varied prompts, in edge cases, and **better than no skill at
all**. Condensed from https://agentskills.io/skill-creation/evaluating-skills.

## Test cases

Three parts: a realistic **prompt**, a human-readable **expected output**, and
optional **input files**. Store them in `evals/evals.json` inside the skill.

```json
{
  "skill_name": "csv-analyzer",
  "evals": [
    {
      "id": 1,
      "prompt": "I have a CSV of monthly sales data in data/sales_2025.csv. Can you find the top 3 months by revenue and make a bar chart?",
      "expected_output": "A bar chart image showing the top 3 months by revenue, with labeled axes and values.",
      "files": ["evals/files/sales_2025.csv"]
    },
    {
      "id": 2,
      "prompt": "there's a csv in my downloads called customers.csv, some rows have missing emails — can you clean it up and tell me how many were missing?",
      "expected_output": "A cleaned CSV with missing emails handled, plus a count of how many were missing.",
      "files": ["evals/files/customers.csv"]
    }
  ]
}
```

Guidance:

- **Start with 2–3 cases.** Don't over-invest before the first round of results.
- **Vary phrasing and formality** — casual ("hey can you clean up this csv")
  alongside precise ("Parse the CSV at data/input.csv, drop rows where column B
  is null, write to data/output.csv").
- **Cover an edge case** — malformed input, unusual request, or a spot where
  the instructions are ambiguous.
- **Use realistic context** — file paths, column names, personal framing.
  "Process this data" tests nothing.

Don't write assertions yet. You usually don't know what "good" looks like until
the skill has run.

## Running evals

Run each case twice: **with the skill** and **without it** (or against the
previous version). The baseline is what tells you the skill is adding value.

### Workspace layout

Each pass gets its own `iteration-N/`:

```
csv-analyzer/
├── SKILL.md
└── evals/evals.json
csv-analyzer-workspace/
└── iteration-1/
    ├── eval-top-months-chart/
    │   ├── with_skill/
    │   │   ├── outputs/       # Files produced by the run
    │   │   ├── timing.json    # Tokens and duration
    │   │   └── grading.json   # Assertion results
    │   └── without_skill/
    │       ├── outputs/
    │       ├── timing.json
    │       └── grading.json
    ├── eval-clean-missing-emails/
    │   └── ...
    └── benchmark.json         # Aggregated statistics
```

You author `evals/evals.json` by hand. Everything else is produced during runs.

### Spawning runs

**Each run needs a clean context** — no leftover state from previous runs or
from developing the skill, so the agent follows only what `SKILL.md` says. In
Claude Code, subagents give this isolation naturally; otherwise use a separate
session per run.

Instructions for one with-skill run:

```
Execute this task:
- Skill path: /path/to/csv-analyzer
- Task: I have a CSV of monthly sales data in data/sales_2025.csv.
  Can you find the top 3 months by revenue and make a bar chart?
- Input files: evals/files/sales_2025.csv
- Save outputs to: csv-analyzer-workspace/iteration-1/eval-top-months-chart/with_skill/outputs/
```

Same prompt without the skill path for the baseline, saving to
`without_skill/outputs/`.

When improving an existing skill, snapshot the current version first
(`cp -r <skill-path> <workspace>/skill-snapshot/`), point the baseline at the
snapshot, and save to `old_skill/outputs/`.

### Timing

Record tokens and duration per run — a skill that triples token usage for a
small quality gain is a different trade than one that's better and cheaper.

```json
{ "total_tokens": 84852, "duration_ms": 23332 }
```

In Claude Code, subagent task-completion notifications carry `total_tokens` and
`duration_ms`. Save them immediately; they aren't persisted elsewhere.

## Assertions

Verifiable statements about the output. Write them **after** seeing the first
round of results.

Good:
- `"The output file is valid JSON"` — programmatically verifiable.
- `"The bar chart has labeled axes"` — specific and observable.
- `"The report includes at least 3 recommendations"` — countable.

Weak:
- `"The output is good"` — ungradeable.
- `"The output uses exactly the phrase 'Total Revenue: $X'"` — brittle; correct
  output with different wording fails.

Not everything needs an assertion. Writing style, visual design, whether the
output "feels right" — those belong to human review. Reserve assertions for
objective checks.

```json
{
  "id": 1,
  "prompt": "...",
  "expected_output": "...",
  "files": ["evals/files/sales_2025.csv"],
  "assertions": [
    "The output includes a bar chart image file",
    "The chart shows exactly 3 months",
    "Both axes are labeled",
    "The chart title or caption mentions revenue"
  ]
}
```

## Grading

Evaluate each assertion against the actual outputs, recording PASS/FAIL with
**evidence that quotes or references the output** — not an opinion.

```json
{
  "assertion_results": [
    { "text": "The output includes a bar chart image file", "passed": true,
      "evidence": "Found chart.png (45KB) in outputs directory" },
    { "text": "Both axes are labeled", "passed": false,
      "evidence": "Y-axis is labeled 'Revenue ($)' but X-axis has no label" }
  ],
  "summary": { "passed": 3, "failed": 1, "total": 4, "pass_rate": 0.75 }
}
```

Use a script for mechanical checks (valid JSON, row counts, file exists with
expected dimensions) — more reliable than LLM judgement and reusable across
iterations. Use an LLM for the rest.

Principles:

- **Require concrete evidence for a PASS.** No benefit of the doubt. A section
  titled "Summary" containing one vague sentence fails an assertion asking for
  a summary — the label is there, the substance isn't.
- **Review the assertions themselves.** Notice which are too easy (always
  pass), too hard (always fail), or unverifiable from the output. Fix them
  before the next iteration.

For comparing two versions, try **blind comparison**: give an LLM judge both
outputs without saying which is which, and have it score holistic qualities —
organization, formatting, usability, polish. Two outputs can pass identical
assertions and still differ a lot.

## Aggregating

```json
{
  "run_summary": {
    "with_skill":    { "pass_rate": {"mean": 0.83, "stddev": 0.06},
                       "time_seconds": {"mean": 45.0, "stddev": 12.0},
                       "tokens": {"mean": 3800, "stddev": 400} },
    "without_skill": { "pass_rate": {"mean": 0.33, "stddev": 0.10},
                       "time_seconds": {"mean": 32.0, "stddev": 8.0},
                       "tokens": {"mean": 2100, "stddev": 300} },
    "delta": { "pass_rate": 0.50, "time_seconds": 13.0, "tokens": 1700 }
  }
}
```

The delta is the whole argument for the skill: what it costs versus what it
buys. +13 seconds for +50 points of pass rate is worth it. Double the tokens
for +2 points is not.

`stddev` only means something with multiple runs per eval. In early iterations,
focus on raw pass counts and the delta.

## Analyzing patterns

Aggregates hide things. After computing benchmarks:

- **Remove assertions that always pass in both configs.** The model handles
  them unaided; they inflate the with-skill rate without reflecting value.
- **Investigate assertions that always fail in both.** Either the assertion is
  broken, the case is too hard, or it's checking the wrong thing.
- **Study assertions that pass with the skill and fail without.** This is where
  the skill earns its place — understand *which* instruction made the
  difference.
- **Tighten instructions when results are inconsistent** (high stddev). Either
  the eval is flaky or the instructions are ambiguous enough to be read
  differently each run. Add examples or specificity.
- **Check time and token outliers.** If one eval takes 3× the others, read its
  transcript for the bottleneck.

## Human review

Assertions only check what you thought to check. A human catches outputs that
are technically correct but miss the point. Record specific, actionable notes:

```json
{
  "eval-top-months-chart": "The chart is missing axis labels and the months are in alphabetical order instead of chronological.",
  "eval-clean-missing-emails": ""
}
```

Empty means it looked fine. "Looks bad" is not feedback.

## The iteration loop

Three signals feed improvements:

- **Failed assertions** → specific gaps: a missing step, an unclear
  instruction, an unhandled case.
- **Human feedback** → broader quality issues: wrong approach, poor structure,
  technically-correct-but-unhelpful output.
- **Execution transcripts** → *why*. Instruction ignored ⇒ probably ambiguous.
  Time spent on unproductive steps ⇒ those instructions need simplifying or
  removing.

Give all three plus the current `SKILL.md` to an LLM and ask for proposed
changes, with these constraints:

- **Generalize.** Fix the underlying issue, don't patch the specific example.
- **Keep it lean.** If transcripts show wasted work, remove those instructions.
  If pass rates plateau as you add rules, the skill may be over-constrained —
  try removing some and see whether results hold.
- **Explain the why.** "Do X because Y tends to cause Z" outperforms "ALWAYS do
  X, NEVER do Y".
- **Bundle repeated work.** If every run wrote a similar helper, bundle it.

Then: review and apply, rerun all cases in `iteration-<N+1>/`, grade, aggregate,
review with a human, repeat. Stop when you're satisfied, feedback is
consistently empty, or improvements stop being meaningful.
