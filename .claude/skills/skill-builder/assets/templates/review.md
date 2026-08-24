---
name: {{NAME}}
description: {{DESCRIPTION}}
{{EXTRA_FRONTMATTER}}---

# {{TITLE}}

<What is being reviewed, and what a useful review looks like here.>

## What to check

Work through these. For each, the point is *why* it matters — use judgement
about how it applies to the change in front of you.

1. **<Dimension>** — <what to look for, and why it bites when missed.>
2. **<Dimension>** — <what to look for and why.>
3. **<Dimension>** — <what to look for and why.>

## What not to flag

<Explicit non-goals. Review skills fail more often by producing noise than by
missing things — name the categories that are out of scope here.>

- <Style/preference item the team has already settled.>
- <Class of finding that belongs to a different review.>

## Severity

| Level | Means |
| --- | --- |
| Blocking | <definition — be concrete about the bar> |
| Should fix | <definition> |
| Note | <definition> |

## Output format

```markdown
## <Finding title>
**Severity:** <Blocking | Should fix | Note>
**Location:** `<file>:<line>`

<What is wrong, and the concrete scenario in which it fails.>

**Suggested fix:** <specific change>
```

If nothing meets the bar, say so plainly rather than manufacturing findings.

## Gotchas

- <Project-specific convention a reviewer would otherwise flag incorrectly.>
- <Another.>
