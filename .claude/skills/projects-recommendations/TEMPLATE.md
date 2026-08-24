# Recommendations — <PROJECT_NAME>

<!-- generated-by: /projects-recommendations -->
<!-- analyzed-commit: <FULL_40_CHAR_SHA> -->
<!-- analyzed-at: <ISO_8601_TIMESTAMP> -->
<!-- stack: <COMMA_SEPARATED_STACKS> -->

## Summary

<Two to four sentences: what this project is, what shape the code is in, and
the single most valuable thing to do next. Written for someone who has not
opened the repo in six months. On a re-run, say what moved since the last
analysis — how many items were resolved, and whether the project is trending
better or worse.>

## Fixes

<Bugs, correctness problems, security exposure, crash paths. Highest-value
first. Omit the whole section if there are none — do not pad it.>

### [High] <Short imperative title>

**Where**: `path/to/file.py:120-138`
**Why**: <What breaks, under what input or condition. Be concrete.>
**How**: <The change to make, specific enough to act on without re-reading
the file.>
**Effort**: <S | M | L>
**Raised**: <YYYY-MM-DD — the date this finding was FIRST made. On a re-run,
carry the original date forward unchanged. Only new findings get today's.>

## Enhancements

<Improvements to code that already works: error handling, logging, structure,
testability, dependency hygiene, docs that are wrong or missing.>

### [Medium] <Short imperative title>

**Where**: `path/to/file.py`
**Why**: <...>
**How**: <...>
**Effort**: <S | M | L>
**Raised**: <YYYY-MM-DD>

## Features

<Capabilities the project does not have yet but plausibly wants, judged from
its own README, TODOs, and evident purpose. Not generic wishlist items.>

### [Low] <Short imperative title>

**Where**: `<area of the codebase, or "new module">`
**Why**: <...>
**How**: <...>
**Effort**: <S | M | L>
**Raised**: <YYYY-MM-DD>

## Optimizations

<Performance, resource use, startup time, API call volume, redundant work.
Only where there is evidence it matters — say what makes it worth doing.>

### [Low] <Short imperative title>

**Where**: `path/to/file.py:44`
**Why**: <...>
**How**: <...>
**Effort**: <S | M | L>
**Raised**: <YYYY-MM-DD>

## Completed

<Resolved history. Items move here from the sections above when a later run
verifies they are done. Newest first. This section is the record of what the
project has actually fixed, so nothing is ever deleted from it — an item that
leaves the open sections lands here, it does not vanish.

On a first run this section is omitted entirely.>

### [High] <The original title, unchanged>

**Where**: `path/to/file.py:120-138`
**Raised**: <the ORIGINAL date, carried forward untouched>
**Completed**: <YYYY-MM-DD — the date the re-run verified it done>
**Resolution**: <What actually changed, in one or two sentences, pointing at
the code that now handles it. If the item went away because the code was
deleted or the project changed direction rather than because it was fixed,
say that plainly — "no longer applicable: module removed" is honest history
and "fixed" would not be.>

<Completed items keep only these four fields. Drop Why, How, and Effort — the
finding is settled and the detail is in git history.>

---

## Format rules

The `view` and `scan` modes parse this file, so the structure is load-bearing:

- The four `<!-- key: value -->` comments must stay, and `generated-by` must
  read exactly `/projects-recommendations` — its absence is how the skill
  recognizes a `recommendations.md` it did not write and refuses to overwrite.
- Open category headings are exactly `## Fixes`, `## Enhancements`,
  `## Features`, `## Optimizations`. Drop any that came back empty.
- The resolved section heading is exactly `## Completed`. Everything under it
  is counted as done and is reported separately from outstanding work.
- Every item heading is `### [High] Title`, `### [Medium] Title`, or
  `### [Low] Title` — in the Completed section too.
- Field lines are `**Where**:`, `**Why**:`, `**How**:`, `**Effort**:`,
  `**Raised**:`, `**Completed**:`, `**Resolution**:` — the colon sits outside
  the asterisks, and each starts its own line.
- `**Raised**` is required on every item. A missing one can be backfilled with
  `recommendations.py stamp`, but that only knows the report's analysis date,
  so getting it right when writing is better than repairing it later.
- Delete this "Format rules" section from the file you write.
