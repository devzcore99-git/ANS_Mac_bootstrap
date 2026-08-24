# Agent Skills format specification

Condensed from https://agentskills.io/specification. This is the normative
reference — when drafting frontmatter, follow it exactly.

## Directory structure

A skill is a directory containing, at minimum, a `SKILL.md`:

```
skill-name/
├── SKILL.md          # Required: frontmatter + instructions
├── scripts/          # Optional: executable code
├── references/       # Optional: documentation loaded on demand
├── assets/           # Optional: templates, images, data files
└── ...               # Any additional files or directories
```

The directory name **must** equal the `name` field.

## Frontmatter fields

`SKILL.md` opens with a YAML frontmatter block fenced by `---` on the first
line and a matching `---` after the last field.

| Field | Required | Constraints |
| --- | --- | --- |
| `name` | Yes | 1–64 chars. Lowercase `a-z`, digits `0-9`, hyphens. No leading/trailing hyphen, no `--`. Must match the parent directory name. |
| `description` | Yes | 1–1024 chars, non-empty. Describes what the skill does *and* when to use it. |
| `license` | No | License name, or the filename of a bundled license. Keep short. |
| `compatibility` | No | 1–500 chars. Environment requirements only — intended product, system packages, network access. Most skills do not need this. |
| `metadata` | No | Map of string keys to string values. Client-specific extras. Use reasonably unique key names to avoid collisions. |
| `allowed-tools` | No | Space-separated string of pre-approved tools, e.g. `Bash(git:*) Bash(jq:*) Read`. Experimental; support varies by client. |

No other top-level fields are defined. Anything else is ignored by clients —
put custom data under `metadata:`.

### Valid and invalid names

```yaml
name: pdf-processing     # valid
name: data-analysis      # valid
name: code-review        # valid

name: PDF-Processing     # invalid — uppercase
name: -pdf               # invalid — leading hyphen
name: pdf--processing    # invalid — consecutive hyphens
name: pdf_processing     # invalid — underscore
```

### Example frontmatter

Minimal:

```yaml
---
name: skill-name
description: A description of what this skill does and when to use it.
---
```

With optional fields:

```yaml
---
name: pdf-processing
description: Extract PDF text, fill forms, merge files. Use when handling PDFs.
license: Apache-2.0
compatibility: Requires Python 3.14+ and uv
metadata:
  author: example-org
  version: "1.0"
---
```

## Body content

Everything after the frontmatter is the skill's instructions. There are no
format restrictions. Recommended sections: step-by-step instructions, examples
of inputs and outputs, common edge cases.

The whole body loads into context the moment the skill activates, so size is a
real cost. See [authoring.md](authoring.md) for how to spend it.

## Optional directories

**`scripts/`** — executable code the agent can run. Scripts should be
self-contained or clearly document dependencies, include helpful error
messages, and handle edge cases gracefully. Supported languages depend on the
client; Python, Bash and JavaScript are the common choices. See
[scripts.md](scripts.md).

**`references/`** — documentation loaded on demand. Conventional filenames:
`REFERENCE.md` (detailed technical reference), `FORMS.md` (form templates or
structured data formats), or domain-specific names (`finance.md`, `legal.md`).
Keep each file focused — smaller files mean less context burned when loaded.

**`assets/`** — static resources: document and configuration templates, images
and diagrams, data files such as lookup tables and schemas.

## Progressive disclosure

Agents load skills in three stages:

1. **Discovery** (~100 tokens) — `name` and `description` for every installed
   skill are loaded at startup. This is all the agent knows when deciding
   whether the skill is relevant.
2. **Activation** (< 5,000 tokens recommended) — the full `SKILL.md` body loads
   once the agent decides the skill applies.
3. **Execution** (as needed) — files under `scripts/`, `references/` and
   `assets/` load only when the instructions call for them.

Budgets: keep `SKILL.md` under **500 lines** and **5,000 tokens**. Move
detailed reference material into separate files.

## File references

Reference bundled files with paths relative to the skill root:

```markdown
See [the reference guide](references/REFERENCE.md) for details.

Run the extraction script:
scripts/extract.py
```

Keep references one level deep from `SKILL.md`. Avoid chains where one
reference file sends the agent to another, which sends it to a third.

The same relative-path convention applies inside `references/*.md` — the agent
runs commands from the skill directory root.

## Validation

Validate with the bundled checker:

```bash
python3 .claude/skills/skill-builder/scripts/validate_skill.py path/to/skill
```

The upstream reference implementation is
[`skills-ref`](https://github.com/agentskills/agentskills/tree/main/skills-ref)
(`skills-ref validate ./my-skill`), which checks frontmatter validity and
naming conventions.
