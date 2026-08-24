# Authoring playbook

How to write a skill body that actually changes agent behaviour. Condensed from
https://agentskills.io/skill-creation/best-practices.

## The failure mode to avoid

The most common way skills go wrong: someone asks an LLM to generate a skill
with no domain context, and gets generic procedure — "handle errors
appropriately", "follow authentication best practices". That content is worse
than nothing, because it occupies context without changing what the agent does.

Every skill needs a source of real expertise. See [intake.md](intake.md) for how
to extract it.

## Spending context wisely

Once a skill activates, its whole body sits in the context window competing
with the conversation, the system prompt, and every other active skill.

### Add what the agent lacks, omit what it knows

Focus on project-specific conventions, domain procedures, non-obvious edge
cases, and which particular tool or API to use. Do not explain what a PDF is,
how HTTP works, or what a database migration does.

````markdown
<!-- Too verbose — the agent already knows what PDFs are -->
## Extract PDF text

PDF (Portable Document Format) files are a common file format that contains
text, images, and other content. To extract text from a PDF, you'll need to
use a library. pdfplumber is recommended because it handles most cases well.

<!-- Better — jumps straight to what the agent wouldn't know on its own -->
## Extract PDF text

Use pdfplumber for text extraction. For scanned documents, fall back to
pdf2image with pytesseract.

```python
import pdfplumber

with pdfplumber.open("file.pdf") as pdf:
    text = pdf.pages[0].extract_text()
```
````

The test for every line: **would the agent get this wrong without it?** If no,
cut it. If the agent already does the whole task well unaided, the skill may
not be worth building — check with an eval, see [evaluation.md](evaluation.md).

### Design coherent units

Scoping a skill is like scoping a function. Too narrow and several skills must
load for one task, risking overhead and conflicting instructions. Too broad and
the description can't trigger precisely.

"Query the database and format the results" is probably one coherent unit.
"Query the database, format results, and administer the database" is two.

### Aim for moderate detail

Exhaustive skills hurt. The agent struggles to find what's relevant and may
chase instructions that don't apply to the current task. Concise stepwise
guidance plus one working example beats comprehensive documentation. When you
find yourself covering every edge case, ask whether most are better left to the
agent's own judgement.

### Structure large skills with progressive disclosure

When a skill legitimately needs more than 500 lines, move detail into
`references/`. The critical part is telling the agent **when** to load each
file:

```markdown
Read references/api-errors.md if the API returns a non-200 status code.
```

not:

```markdown
See references/ for details.
```

## Calibrating control

Match prescriptiveness to fragility. Most skills mix both; calibrate each
section independently.

**Give freedom** when several approaches are valid. Explaining *why* beats
rigid directives — an agent that understands the purpose makes better
context-dependent calls.

```markdown
## Code review process

1. Check all database queries for SQL injection (use parameterized queries)
2. Verify authentication checks on every endpoint
3. Look for race conditions in concurrent code paths
4. Confirm error messages don't leak internal details
```

**Be prescriptive** when operations are fragile, consistency matters, or a
sequence must be followed exactly.

````markdown
## Database migration

Run exactly this sequence:

```bash
python scripts/migrate.py --verify --backup
```

Do not modify the command or add additional flags.
````

### Provide defaults, not menus

````markdown
<!-- Too many options -->
You can use pypdf, pdfplumber, PyMuPDF, or pdf2image...

<!-- Clear default with escape hatch -->
Use pdfplumber for text extraction:

```python
import pdfplumber
```

For scanned PDFs requiring OCR, use pdf2image with pytesseract instead.
````

### Favour procedures over declarations

Teach *how to approach* a class of problems, not *what to produce* for one
instance.

```markdown
<!-- Specific answer — only useful for this exact task -->
Join the `orders` table to `customers` on `customer_id`, filter where
`region = 'EMEA'`, and sum the `amount` column.

<!-- Reusable method — works for any analytical query -->
1. Read the schema from references/schema.yaml to find relevant tables
2. Join tables using the `_id` foreign key convention
3. Apply any filters from the user's request as WHERE clauses
4. Aggregate numeric columns as needed and format as a markdown table
```

Specific details still belong in skills — output templates, constraints like
"never output PII", tool-specific instructions. The *approach* is what should
generalise.

## Patterns for effective instructions

Use the ones that fit. Not every skill needs all of them.

### Gotchas sections

Often the highest-value content in a skill: environment-specific facts that
defy reasonable assumptions. Not general advice — concrete corrections to
mistakes the agent will otherwise make.

```markdown
## Gotchas

- The `users` table uses soft deletes. Queries must include
  `WHERE deleted_at IS NULL` or results will include deactivated accounts.
- The user ID is `user_id` in the database, `uid` in the auth service,
  and `accountId` in the billing API. All three refer to the same value.
- The `/health` endpoint returns 200 as long as the web server is running,
  even if the database connection is down. Use `/ready` to check full
  service health.
```

Keep gotchas in `SKILL.md`, not a reference file — the agent must read them
*before* hitting the situation, and for non-obvious issues it won't recognise
the trigger to go load them.

**Every time you correct an agent, that correction is a gotcha.** This is the
single most direct way to improve a skill over time.

### Templates for output format

Agents pattern-match against concrete structures far better than prose
descriptions. Short templates go inline; longer or conditional ones go in
`assets/` and get referenced.

````markdown
## Report structure

Use this template, adapting sections as needed for the specific analysis:

```markdown
# [Analysis Title]

## Executive summary
[One-paragraph overview of key findings]

## Key findings
- Finding 1 with supporting data
- Finding 2 with supporting data

## Recommendations
1. Specific actionable recommendation
2. Specific actionable recommendation
```
````

### Checklists for multi-step workflows

Helps the agent track progress and not skip steps, especially with dependencies
or validation gates.

```markdown
## Form processing workflow

Progress:
- [ ] Step 1: Analyze the form (run scripts/analyze_form.py)
- [ ] Step 2: Create field mapping (edit fields.json)
- [ ] Step 3: Validate mapping (run scripts/validate_fields.py)
- [ ] Step 4: Fill the form (run scripts/fill_form.py)
- [ ] Step 5: Verify output (run scripts/verify_output.py)
```

### Validation loops

Do the work, run a validator, fix what it reports, repeat until clean.

```markdown
## Editing workflow

1. Make your edits
2. Run validation: `python scripts/validate.py output/`
3. If validation fails:
   - Review the error message
   - Fix the issues
   - Run validation again
4. Only proceed when validation passes
```

A reference document can serve as the validator — instruct the agent to check
its work against the reference before finalising.

### Plan-validate-execute

For batch or destructive operations: have the agent write an intermediate plan
in a structured format, validate that plan against a source of truth, and only
then execute.

```markdown
## PDF form filling

1. Extract form fields: `python scripts/analyze_form.py input.pdf` → form_fields.json
   (lists every field name, type, and whether it's required)
2. Create field_values.json mapping each field name to its intended value
3. Validate: `python scripts/validate_fields.py form_fields.json field_values.json`
   (checks that every field name exists in the form, types are compatible, and
   required fields aren't missing)
4. If validation fails, revise field_values.json and re-validate
5. Fill the form: `python scripts/fill_form.py input.pdf field_values.json output.pdf`
```

Step 3 is the whole point. The validator's error message must carry enough
information to self-correct: `Field 'signature_date' not found — available
fields: customer_name, order_total, signature_date_signed`.

### Bundling reusable scripts

When execution traces show the agent reinventing the same logic every run —
building charts, parsing a format, validating output — write it once, test it,
and bundle it in `scripts/`. See [scripts.md](scripts.md).

## Refining with real execution

First drafts need refinement. Run the skill on real tasks and feed **all**
results back — not just failures. Ask: what triggered false positives? What was
missed? What could be cut?

Read execution traces, not just final outputs. When an agent wastes time, the
usual causes are:

- Instructions too vague — the agent tries several approaches before one works.
- Instructions that don't apply to this task — the agent follows them anyway.
- Too many options with no clear default.

Even a single execute-then-revise pass noticeably improves quality. Complex
domains benefit from several. For the structured version, see
[evaluation.md](evaluation.md).
