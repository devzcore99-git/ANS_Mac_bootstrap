---
name: {{NAME}}
description: {{DESCRIPTION}}
{{EXTRA_FRONTMATTER}}---

# {{TITLE}}

<What this workflow accomplishes and what a finished run looks like.>

## Before you start

<Preconditions: files that must exist, credentials that must be set, state to
check. Say how to check each one, not just that it matters.>

## Workflow

Track progress against this checklist:

- [ ] Step 1: <action> — <how to verify it worked>
- [ ] Step 2: <action> — <how to verify it worked>
- [ ] Step 3: <action> — <how to verify it worked>
- [ ] Step 4: Validate the result (see [Validation](#validation))

### Step 1: <name>

<Concrete instructions. Be prescriptive where the operation is fragile; give
the agent room and explain *why* where several approaches are valid.>

### Step 2: <name>

<Instructions.>

### Step 3: <name>

<Instructions.>

## Validation

Do not report the task complete until this passes:

1. <Check — a command to run, or a property of the output to confirm.>
2. If it fails: <what to inspect, what to change, then re-run this section.>

## Gotchas

- <Non-obvious failure mode and how to avoid it.>
- <Another.>

## Stop conditions

Stop and ask the user when:

- <Ambiguity that no default resolves safely.>
- <Destructive or irreversible action outside the requested scope.>
