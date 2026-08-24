# Agent prompt template

Read this when writing the prompt for a build task or a re-prompt after a failure — step 4b and step 4e of
`SKILL.md`. It is separate only to keep the always-loaded body under budget; the rules in it are not optional.

`herdr agent prompt` types text into the opencode TUI. **There is no attachment
mechanism**, so anything the agent must conform to is in the prompt text — never
a path to a spec, a PRD, or a design document. Pointing at a document is the
most expensive habit there is: the agent reads it, re-reads it, and is charged
for each read out of the context window that was already the binding
constraint.

```
Write <the one thing>, in <project>/<file>. Touch no other file.

The interface it must match, exactly:

<paste the signatures, field names, and two examples — the real text, not a
path to it>

The test it must pass, already written and committed at <test_file>:

<paste the test file's contents verbatim>

Do not edit that test, and do not create or edit any other test.
Do not run git. Do not install packages.

Run this until it passes, then stop:
  <test command>
```

Four properties make that prompt work, and dropping any one is the usual cause
of a task coming back empty or wrong: **imperative, not interrogative** (a
question comes back as an answer with nothing written); **exact filenames plus
"Touch no other file"** (the worktree is isolation by convention only — these
agents are not sandboxed); **the test pasted in and forbidden to edit** (it is
both the specification and the grade); **no git, no installs** (you commit, and
the workspace never installs a dependency without the user's say-so).

For a re-prompt after a failure, keep the same shape and add the failure
verbatim:

```
That did not pass. Attempt <n> of 5.

I ran: <test command>
Output:
<paste the complete failure output, unedited>

Fix <project>/<file> so the test passes. Do NOT weaken, skip, xfail, or delete
the failing assertion, and do not edit the test file. If you believe the test
itself is wrong, say so and change nothing.
```

