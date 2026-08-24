# Bundling and designing scripts

Condensed from https://agentskills.io/skill-creation/using-scripts.

## When to bundle a script

Bundle one when the logic is **reused across runs and easy to get wrong**. The
signal to watch for: run the skill on several tasks and compare traces — if the
agent independently reinvents the same helper each time (a chart builder, a
format parser, an output validator), write it once and test it.

Do **not** bundle a script when a one-off command already does the job.

## One-off commands

Reference existing packages directly in `SKILL.md` — no `scripts/` directory
needed. Runtimes that resolve dependencies on demand:

| Runtime | Example | Notes |
| --- | --- | --- |
| `uvx` | `uvx ruff@0.8.0 check .` | Ships with `uv`. Fast, caches aggressively. Separate install. |
| `pipx` | `pipx run 'black==24.10.0' .` | Mature alternative; broader OS package-manager availability. |
| `npx` | `npx eslint@9 --fix .` | Ships with npm/Node. Downloads and caches on demand. |
| `bunx` | `bunx eslint@9 --fix .` | Drop-in `npx` replacement in Bun environments. |
| `deno run` | `deno run --allow-read npm:eslint@9 -- --fix .` | Permission flags required. Use `--` to separate Deno flags. |
| `go run` | `go run golang.org/x/tools/cmd/goimports@v0.28.0 .` | Built into Go. |

Rules for one-off commands in skills:

- **Pin versions** (`npx eslint@9.0.0`) so behaviour is stable over time.
- **State prerequisites** in `SKILL.md` ("Requires Node.js 18+") rather than
  assuming. For runtime-level requirements use the `compatibility` frontmatter
  field.
- **Promote complex commands to scripts.** A one-off command is fine for a tool
  with a few flags. Once it's hard to get right first try, a tested script is
  more reliable.

## Referencing bundled files

Use paths relative to the skill directory root — the agent resolves them and
runs commands from there. Absolute paths are never needed.

List what exists so the agent knows to reach for it:

```markdown
## Available scripts

- **`scripts/validate.sh`** — Validates configuration files
- **`scripts/process.py`** — Processes input data
```

Then instruct:

````markdown
## Workflow

1. Run the validation script:
   ```bash
   bash scripts/validate.sh "$INPUT_FILE"
   ```

2. Process the results:
   ```bash
   python3 scripts/process.py --input results.json
   ```
````

The same convention applies inside `references/*.md`.

## Self-contained scripts

Declare dependencies inline so the agent can run the script with one command —
no manifest, no install step.

**Python (PEP 723):**

```python
# /// script
# dependencies = [
#   "beautifulsoup4>=4.12,<5",
# ]
# ///

from bs4 import BeautifulSoup
...
```

Run with `uv run scripts/extract.py` (creates an isolated environment, installs
declared dependencies, runs). `pipx run scripts/extract.py` also supports
PEP 723. Constrain the interpreter with `requires-python`; `uv lock --script`
produces a lockfile for full reproducibility.

**Deno** — `npm:` / `jsr:` specifiers make scripts self-contained by default:

```typescript
#!/usr/bin/env -S deno run
import * as cheerio from "npm:cheerio@1.0.0";
```

Cached globally; `--reload` forces re-fetch. Packages needing native addons
(node-gyp) may fail — prefer ones shipping pre-built binaries.

**Bun** — auto-installs missing packages at runtime when no `node_modules` is
found; pin in the import path (`import * as cheerio from "cheerio@1.0.0"`).
TypeScript works natively. If a `node_modules` exists anywhere up the tree,
auto-install is disabled.

**Ruby** — `bundler/inline`:

```ruby
require 'bundler/inline'
gemfile do
  source 'https://rubygems.org'
  gem 'nokogiri', '~> 1.16'
end
```

No lockfile, so pin explicitly. An existing `Gemfile` or `BUNDLE_GEMFILE` in
the working directory can interfere.

If the skill must run without any package manager, write it against the
standard library only and say so in `compatibility`.

## Designing scripts for agentic use

The agent reads stdout and stderr to decide what to do next. These choices
matter more than they would for a human-facing CLI.

### Never prompt interactively

A hard requirement. Agents run in non-interactive shells — a script that blocks
on a TTY prompt hangs indefinitely. Take all input via flags, environment
variables, or stdin.

```
# Bad: hangs waiting for input
$ python scripts/deploy.py
Target environment: _

# Good: clear error with guidance
$ python scripts/deploy.py
Error: --env is required. Options: development, staging, production.
Usage: python scripts/deploy.py --env staging --tag v1.2.3
```

### Document usage with `--help`

`--help` is how the agent learns the interface. Include a brief description,
the flags, and examples. Keep it concise — it lands in the context window.

```
Usage: scripts/process.py [OPTIONS] INPUT_FILE

Process input data and produce a summary report.

Options:
  --format FORMAT    Output format: json, csv, table (default: json)
  --output FILE      Write output to FILE instead of stdout
  --verbose          Print progress to stderr

Examples:
  scripts/process.py data.csv
  scripts/process.py --format csv --output report.csv data.csv
```

### Write errors that enable the next attempt

The error message directly shapes what the agent tries next. "Error: invalid
input" wastes a turn. Say what went wrong, what was expected, and what to try.

```
Error: --format must be one of: json, csv, table.
       Received: "xml"
```

### Use structured output

Prefer JSON, CSV or TSV over free-form text — both the agent and standard tools
(`jq`, `cut`, `awk`) can consume it.

```
# Whitespace-aligned — hard to parse programmatically
NAME          STATUS    CREATED
my-service    running   2025-01-15

# Delimited — unambiguous field boundaries
{"name": "my-service", "status": "running", "created": "2025-01-15"}
```

**Separate data from diagnostics:** structured data to stdout, progress and
warnings to stderr.

### Further considerations

- **Idempotency.** Agents retry. "Create if not exists" beats "create and fail
  on duplicate."
- **Input constraints.** Reject ambiguous input with a clear error rather than
  guessing. Use enums and closed sets.
- **Dry-run support.** A `--dry-run` flag lets the agent preview destructive or
  stateful operations.
- **Meaningful exit codes.** Distinct codes per failure class (not found,
  invalid arguments, auth failure), documented in `--help`.
- **Safe defaults.** Consider requiring `--confirm` / `--force` for destructive
  operations.
- **Predictable output size.** Harnesses truncate tool output past a threshold
  (often 10–30K characters), silently losing information. Default to a summary
  or a sane limit, support `--offset` for more, or require an explicit
  `--output FILE` (with `-` meaning stdout) when output is inherently large.
