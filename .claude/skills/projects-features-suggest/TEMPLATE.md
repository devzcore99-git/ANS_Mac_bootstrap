# Features — <PROJECT_NAME>

<!-- generated-by: /projects-features-suggest -->
<!-- analyzed-commit: <FULL_40_CHAR_SHA> -->
<!-- analyzed-at: <ISO_8601_TIMESTAMP> -->
<!-- stack: <COMMA_SEPARATED_STACKS> -->

## Summary

<Two to four sentences: what this project does today, where its natural next
step lies, and the single idea worth starting with. Written for someone who has
not opened the repo in six months. On a re-run, say what moved — what got
built, what was retired, and whether the project is converging on something or
sprawling.>

## Core

<Capabilities that deepen what the project already does. The highest-value
section for a tool that works but does one thing narrowly. Omit the whole
section if there is nothing to say — do not pad it.>

### [High] <Short imperative title>

**Where**: `path/to/module.py`, or `new module`
**Why**: <What this unlocks for the person using it. Concrete: the task they
cannot do today, or the manual step it removes.>
**How**: <A sketch specific enough to start from — where it hooks in, what it
reads or writes, what changes shape.>
**Effort**: <S | M | L>
**Needs**: <A new third-party dependency the idea requires, with the reason it
cannot be done with the standard library or what is already installed. Write
`none` when nothing new is needed — most ideas should say `none`.>
**Raised**: <YYYY-MM-DD — the date this idea was FIRST proposed. On a re-run,
carry the original date forward unchanged. Only new ideas get today's.>

## Adjacent

<Capabilities next to the current purpose rather than inside it — the natural
second thing this project could do, given what it already knows how to do.>

### [Medium] <Short imperative title>

**Where**: `<area, or "new module">`
**Why**: <...>
**How**: <...>
**Effort**: <S | M | L>
**Needs**: <dependency, or `none`>
**Raised**: <YYYY-MM-DD>

## Integration

<Connections to other projects in this workspace, or to services already in
use. Name the specific sibling repository and the specific data or event that
would cross between them. These are the ideas a single-project review cannot
see, which is what makes them worth the section.>

### [Medium] <Short imperative title>

**Where**: `<the seam — the file that would read or write the other side>`
**Why**: <...>
**How**: <...>
**Effort**: <S | M | L>
**Needs**: <dependency, or `none`>
**Raised**: <YYYY-MM-DD>

## Experience

<How the project is to use: output legibility, error messages, defaults,
startup time, discoverability, documentation that would change what someone
can do. Not cosmetic polish for its own sake.>

### [Low] <Short imperative title>

**Where**: `path/to/cli.py`
**Why**: <...>
**How**: <...>
**Effort**: <S | M | L>
**Needs**: <dependency, or `none`>
**Raised**: <YYYY-MM-DD>

## Built

<Ideas that have shipped. Items move here from the sections above when a later
run verifies them in the code. Newest first. Nothing is ever deleted from this
section — it is the record of what the project actually gained.

On a first run this section is omitted entirely.>

### [High] <The original title, unchanged>

**Where**: `path/to/module.py`
**Raised**: <the ORIGINAL date, carried forward untouched>
**Built**: <YYYY-MM-DD — the date a run verified it in the code>
**Evidence**: <The code that now does it, with a path and where possible a line
number. Verify it in the source: a commit message that claims the feature is
not evidence that the feature works.>

## Declined

<Ideas that will not be built, and why. Two things land here: decisions the
user made, added with `features.py decline`, and ideas a later run found had
become impossible or meaningless.

**Nothing in this section is ever proposed again.** That is the entire point of
keeping it — without it, every run re-raises ideas that were already
considered and turned down.>

### [Low] <The original title, unchanged>

**Where**: `<unchanged>`
**Raised**: <the ORIGINAL date>
**Declined**: <YYYY-MM-DD>
**Reason**: <Why it will not be built. "Overkill for a 400-line tool", "the
module it extended was removed", "deliberately out of scope per CLAUDE.md".
Honest and specific — a future run reads this to understand the boundary, not
just to skip the title.>

<Built and Declined items keep only these fields. Drop Why, How, Effort, and
Needs — the decision is settled and the reasoning is in this file's history.>

---

## Format rules

The `view` and `scan` modes parse this file, so the structure is load-bearing:

- The four `<!-- key: value -->` comments must stay, and `generated-by` must
  read exactly `/projects-features-suggest` — its absence is how the skill
  recognizes a `features.md` it did not write and refuses to overwrite.
- Open section headings are exactly `## Core`, `## Adjacent`,
  `## Integration`, `## Experience`. Drop any that came back empty.
- The settled section headings are exactly `## Built` and `## Declined`.
  Everything under them is counted as closed and reported separately from
  open ideas.
- Every item heading is `### [High] Title`, `### [Medium] Title`, or
  `### [Low] Title` — in Built and Declined too.
- Field lines are `**Where**:`, `**Why**:`, `**How**:`, `**Effort**:`,
  `**Needs**:`, `**Raised**:`, `**Built**:`, `**Declined**:`, `**Evidence**:`,
  `**Reason**:` — the colon sits outside the asterisks, and each starts its
  own line.
- `**Raised**` and `**Needs**` are required on every open idea. `**Needs**`
  is how the reader sees at a glance which ideas carry a new dependency, so
  `none` must be written out rather than left off.
- Delete this "Format rules" section from the file you write.
