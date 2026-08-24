# Writing and optimizing descriptions

The `description` field carries the entire burden of triggering. At startup the
agent sees only `name` and `description` for every installed skill — nothing
else about the skill exists until it decides to activate. An under-specified
description means the skill never fires; an over-broad one means it fires on
tasks it can't help with.

Condensed from https://agentskills.io/skill-creation/optimizing-descriptions.

## Principles

- **Use imperative phrasing.** "Use this skill when…" rather than "This skill
  does…". The agent is deciding whether to act — tell it when to act.
- **Focus on user intent, not implementation.** The agent matches against what
  the user asked for, not your internal mechanics.
- **Err on the side of pushy.** Explicitly list contexts where the skill
  applies, including ones where the user won't name the domain: "even if they
  don't explicitly mention 'CSV' or 'analysis.'"
- **Keep it concise.** A few sentences to a short paragraph. Hard limit is 1024
  characters, but descriptions from every installed skill sit in context at all
  times.

One nuance worth knowing: agents generally only reach for skills on tasks that
exceed what they can do unaided. "Read this PDF" may not trigger a PDF skill no
matter how good the description, because basic tools suffice. Descriptions earn
their keep on tasks involving unfamiliar APIs, domain workflows, or uncommon
formats.

## The shape that works

```
<What it does — the concrete capabilities, named specifically.>
Use when <situations, phrased as the user would experience them>,
even if they don't explicitly mention <the obvious keyword>.
```

Before and after:

```yaml
# Before
description: Process CSV files.

# After
description: >
  Analyze CSV and tabular data files — compute summary statistics,
  add derived columns, generate charts, and clean messy data. Use this
  skill when the user has a CSV, TSV, or Excel file and wants to
  explore, transform, or visualize the data, even if they don't
  explicitly mention "CSV" or "analysis."
```

More specific about *what* (summary stats, derived columns, charts, cleaning),
broader about *when* (CSV, TSV, Excel; keyword-free phrasings included).

Spec-level example of good versus poor:

```yaml
# Good
description: Extracts text and tables from PDF files, fills PDF forms, and merges multiple PDFs. Use when working with PDF documents or when the user mentions PDFs, forms, or document extraction.

# Poor
description: Helps with PDFs.
```

## Designing trigger eval queries

To test triggering, build ~20 realistic prompts labelled with whether they
should activate the skill: 8–10 positive, 8–10 negative.

```json
[
  { "query": "I've got a spreadsheet in ~/data/q4_results.xlsx with revenue in col C and expenses in col D — can you add a profit margin column and highlight anything under 10%?", "should_trigger": true },
  { "query": "whats the quickest way to convert this json file to yaml", "should_trigger": false }
]
```

**Should-trigger queries** — vary along four axes:

- *Phrasing*: formal, casual, with typos and abbreviations.
- *Explicitness*: some name the domain ("analyze this CSV"), others don't ("my
  boss wants a chart from this data file").
- *Detail*: terse prompts alongside context-heavy ones with paths and column
  names.
- *Complexity*: single-step tasks alongside multi-step workflows where the
  relevant task is buried in a larger chain.

The valuable positives are the ones where the skill helps but the connection
isn't obvious from the query. If the query already asks for exactly what the
skill does, any description triggers.

**Should-not-trigger queries** — the valuable ones are **near-misses** that
share keywords but need something else.

Weak (tests nothing):
- `"Write a fibonacci function"` — obviously irrelevant.
- `"What's the weather today?"` — no overlap at all.

Strong (tests precision):
- `"I need to update the formulas in my Excel budget spreadsheet"` — shares
  "spreadsheet", but needs Excel editing, not CSV analysis.
- `"can you write a python script that reads a csv and uploads each row to our
  postgres database"` — involves CSV, but the task is ETL, not analysis.

**Realism matters.** Include file paths (`~/Downloads/report_final_v2.xlsx`),
personal context ("my manager asked me to…"), specific column and company
names, casual language and occasional typos.

## Measuring trigger rate

Model behaviour is nondeterministic, so run each query ~3 times and compute a
trigger rate. A positive query passes if its rate exceeds a threshold (0.5 is a
reasonable default); a negative passes if it falls below.

Detecting whether the skill fired depends on the client — most expose execution
logs, tool-call histories, or verbose output. In Claude Code, look for a `Skill`
tool call naming your skill:

```bash
#!/bin/bash
QUERIES_FILE="${1:?Usage: $0 <queries.json>}"
SKILL_NAME="my-skill"
RUNS=3

check_triggered() {
  local query="$1"
  claude -p "$query" --output-format json 2>/dev/null \
    | jq -e --arg skill "$SKILL_NAME" \
      'any(.messages[].content[]; .type == "tool_use" and .name == "Skill" and .input.skill == $skill)' \
      > /dev/null 2>&1
}

count=$(jq length "$QUERIES_FILE")
for i in $(seq 0 $((count - 1))); do
  query=$(jq -r ".[$i].query" "$QUERIES_FILE")
  should_trigger=$(jq -r ".[$i].should_trigger" "$QUERIES_FILE")
  triggers=0
  for run in $(seq 1 $RUNS); do
    check_triggered "$query" && triggers=$((triggers + 1))
  done
  jq -n --arg query "$query" --argjson should_trigger "$should_trigger" \
        --argjson triggers "$triggers" --argjson runs "$RUNS" \
    '{query: $query, should_trigger: $should_trigger, triggers: $triggers, runs: $runs, trigger_rate: ($triggers / $runs)}'
done | jq -s '.'
```

## Avoiding overfitting

Split the query set and keep the split fixed across iterations:

- **Train (~60%)** — the queries you look at to guide changes.
- **Validation (~40%)** — held out; only used to check whether changes
  generalise.

Both sets need a proportional mix of positives and negatives.

## The optimization loop

1. **Evaluate** on both sets. Train results guide changes; validation results
   tell you whether they generalise.
2. **Identify failures in the train set only.** Keep validation results out of
   the revision process entirely.
3. **Revise:**
   - Positives failing → description too narrow. Broaden scope, add context
     about when the skill helps.
   - Negatives firing → too broad. Add specificity about what the skill does
     *not* do, or clarify the boundary against adjacent capabilities.
   - **Don't paste keywords from failed queries** — that's overfitting. Find
     the general category those queries represent and address that.
   - Stuck after several rounds? Try a structurally different description
     rather than more incremental tweaks.
   - Re-check the 1024-character limit; descriptions grow during optimization.
4. **Repeat** until the train set passes or improvement stalls.
5. **Select by validation pass rate.** The best description is often not the
   last one — an earlier iteration may generalise better than later ones that
   overfit.

Five iterations is usually enough. If nothing improves, suspect the queries
(too easy, too hard, mislabelled) before the description.

## Final check

After applying the winner: confirm it's under 1024 characters, then write 5–10
**fresh** queries never used in optimization and run them. That's the honest
test of whether it generalises.
