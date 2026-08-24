---
name: {{NAME}}
description: {{DESCRIPTION}}
{{EXTRA_FRONTMATTER}}---

# {{TITLE}}

<What the bundled scripts do and what the agent is producing.>

## Available scripts

- **`scripts/<analyze>.py`** — <what it inspects; what it writes>
- **`scripts/<validate>.py`** — <what it checks the plan against>
- **`scripts/<apply>.py`** — <what it changes; whether it is idempotent>

Run `python3 scripts/<analyze>.py --help` for the full interface.

## Workflow

Plan first, validate the plan, then execute. Never skip step 3.

1. **Inspect the input**

   ```bash
   python3 scripts/<analyze>.py <input> > plan_source.json
   ```

2. **Write the plan** — create `<plan>.json` mapping <what> to <what>.

3. **Validate the plan against the source of truth**

   ```bash
   python3 scripts/<validate>.py plan_source.json <plan>.json
   ```

   If validation fails, the error names the offending field and the valid
   options. Fix `<plan>.json` and re-run until it passes.

4. **Execute**

   ```bash
   python3 scripts/<apply>.py <input> <plan>.json <output>
   ```

5. **Verify the output** — <how to confirm the result is correct.>

## Gotchas

- <Non-obvious fact about the input format, the tool, or the environment.>
- <Another.>
