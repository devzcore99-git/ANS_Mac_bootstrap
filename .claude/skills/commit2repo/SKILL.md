---
name: commit2repo
description: Commit everything in the current repository to a claude_ branch, merge it into main/master, and push to origin, in two script calls. Use when the user wants to commit and push the repo they are working in, save and publish their changes, or ship what is in the working tree without a multi-project sweep.
---

# Commit to Repo

One repository, one cycle: branch, commit, merge, push. The script does all the
git work; the only thing that costs tokens is reading a capped diff and writing
the commit message.

**Two calls, always.** `gather` then `run`. Do not run `git status`, `git
diff`, `git log`, or `git branch` alongside them — `gather` already returns
everything those would tell you, and the extra round trips are precisely the
cost this skill exists to avoid.

For committing across several projects at once, use `/projects-git-commit`
instead. This skill deliberately handles only the repo you are standing in.

## Available scripts

- **`commit2repo.py gather`** — read-only. Emits JSON: branch state, changed
  files, `git diff --stat`, and a line-capped diff.
- **`commit2repo.py run`** — branches, commits, merges, pushes. Destructive.
- **`commit2repo.py merge`** — merges the current branch and pushes, committing
  nothing. Destructive. For work that is *already* committed.

Paths below use `$SKILL_DIR` — the base directory printed when this skill
loads. It is not a real environment variable: substitute the printed path, or
set it inline in the same command (`SKILL_DIR=... python3 "$SKILL_DIR/..."`),
because shell state does not persist between calls. This is what lets the
commands run from any project, whether the skill lives in a repository or is
symlinked into `~/.claude/skills/`.

Run `python3 $SKILL_DIR/commit2repo.py --help` for the full
interface. Exit codes: `0` success, `1` a git command failed, `2` usage or
environment error, `3` nothing to commit.

## Workflow

1. **Gather.**

   ```bash
   python3 $SKILL_DIR/commit2repo.py gather
   ```

   Exit `3` means the tree is clean. **Before saying so and stopping, check
   whether the branch has unmerged commits** — that is the "already committed
   earlier, now merge it" case, and `merge` is the command for it:

   ```bash
   python3 $SKILL_DIR/commit2repo.py merge
   ```

   It refuses on `main`/`master`, refuses a dirty tree (pointing at `run`), and
   exits `3` when the branch has nothing the default branch lacks. Otherwise it
   merges and pushes exactly as `run` does — same code path — and skips to the
   reporting step below. Never invent a commit just to reach the merge.

   Read `warnings` before anything else. Then read `stat` for shape and `diff`
   for substance.

2. **Write the commit message.** Conventional commits: `feat:`, `fix:`,
   `docs:`, `refactor:`, `test:`, `chore:`. A subject line under ~72
   characters, and a body only when the *why* is not obvious from the subject.

   Ground it in the diff you were given. If `diff_truncated` is true you are
   seeing part of the change — write to the `stat` and the visible hunks rather
   than guessing at the rest, or re-gather with `--diff-lines 800` when the
   change is genuinely unclear. Re-gathering costs a round trip, so only do it
   when the message would otherwise be wrong.

   Per the workspace convention, end the message with:

   ```
   Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
   ```

3. **Run.**

   ```bash
   python3 $SKILL_DIR/commit2repo.py run -m "fix: ..."
   ```

   The branch name is derived from the message — `fix: correct ref pattern`
   becomes `claude_correct-ref-pattern`. Pass `--branch NAME` to override.

4. **Report** using the two-section structure below. A non-zero exit is a
   failure: name the step that failed and quote git's own error. Never
   summarize a failed run as done.

   If the result carries `"cwd_removed": true`, the worktree you were standing
   in was removed as part of the run — run everything after this from
   `next_dir`. See **Worktree teardown** below.

## Reporting

Report in exactly two top-level sections, **Actionable** first, then
**Non-Actionable**, separated by two horizontal rules with blank lines around
and between them:

```markdown
...last line of the Actionable section.

---

---

## Non-Actionable
```

**Actionable** — anything still needing the user: a failed push and what to do
about it, a conflicted merge, files swept in by `git add -A` that look
unrelated to the change.

**Non-Actionable** — the commit sha, branch name, what merged where, the pushed
ref range, and the teardown: the branch deletion and, in a worktree, the
worktree removal. On a clean run this is the whole report and Actionable is one
line saying nothing needs attention.

A `worktree_remove_error` is **Actionable** — the push landed, but a directory
and a branch are still on disk and the user has to clear them.

## Gotchas

- **Only the remote named `origin` is ever pushed.** `CODE_TournamentWebsite`
  and `CODE_WWW-TournamentWebsite` carry a second remote named `gitlab` that
  feeds the production server build; it is pushed only when a release is cut.
  The script always pushes an explicit `origin <branch>` refspec and never
  enumerates remotes, so a bare `git push`, `git push --all`, or a push to a
  differently-named remote must never be substituted for it.
- **`git add -A` stages the entire working tree**, including edits unrelated to
  the change you have in mind. `gather` returns the full file list precisely so
  you can see that before committing. If the tree is mixed, say so and let the
  user decide rather than sweeping it all into one commit.
- **The branch is deleted only after a successful push.** If the push fails the
  merge is already committed locally and the branch is kept, so nothing is
  lost. Recover by fetching and reconciling — never force-push.
- **A conflicted merge is aborted and the original branch restored.** The
  repository is never left mid-merge, but the conflict is yours to resolve by
  hand; the script will not attempt it.
- **A clean tree is not the same as nothing to do.** `run` requires a message
  and refuses a clean tree, so a branch whose work was committed in an earlier
  turn had no path through this script at all until `merge` existed. If
  `gather` exits 3, check `git log <default>..HEAD` before concluding there is
  nothing to ship.
- **Already on a `claude_` branch?** It is reused rather than nested. This is
  the only path that can conflict, since a fresh branch is always a descendant
  of the default branch.
- **Inside a git worktree the merge runs somewhere else.** Git refuses to check
  out, fetch into, or delete a branch that another worktree holds, so when
  `main`/`master` is checked out in the repo directory the script issues the
  merge *there* and this worktree never leaves its own branch. `gather` reports
  `in_linked_worktree` and `merge_dir`; `run` records `merge_dir` on the merge
  step. Three things follow:
  - **That tree has to be clean.** If it is not, `run` refuses *after*
    committing — the work is safe on the branch and the run is resumable once
    the tree is clean. Use `--no-merge` to stop at the commit instead.
  - **The worktree is removed and its branch deleted, after a successful
    push.** A worktree holds its branch, so the branch cannot go while the
    worktree stays — the two are one step, and leaving it half-done is what
    strands `worktree-*` branches across the workspace. See the section below.
  - **The worktree's own branch is reused, whatever it is called.** The reuse
    rule normally keys off the `claude_` prefix, but `EnterWorktree` names its
    branch `worktree-<name>`, so a prefix check would miss it and cut a second
    branch inside the worktree — exactly the nesting the rule prevents.
- **`.claude/worktrees/` must be gitignored.** It sits inside the repository,
  so an un-ignored worktree leaves the repo permanently dirty and blocks every
  merge. `run` and `gather` name this specifically when it is the only thing
  making the tree dirty.
- Untracked files are diffed against `/dev/null` rather than staged, so
  `gather` leaves the index untouched and is safe to run repeatedly.

## Worktree teardown

When `run` or `merge` is invoked **from inside a linked worktree**, a
successful push is followed by two more steps: the worktree is removed, then
the branch it held is deleted. That is the whole cycle, not a courtesy — git
will not delete a branch any worktree holds, so stopping at the push is what
leaves `worktree-*` branches and their directories behind.

The JSON records `removed_worktree`, `deleted_branch`, and:

```json
"cwd_removed": true,
"next_dir": "/Users/ahill/AI_Projects/<project>"
```

**`cwd_removed` means the directory you were standing in no longer exists.**
Every command after that one must run from `next_dir` — pass it to `git -C`,
or `cd` there. A `Read`, `Edit`, or `Bash` call against the old worktree path
will fail, and the failure will look like the file vanished rather than like a
stale directory.

If the session entered the worktree with `EnterWorktree`, follow up with
`ExitWorktree` using `keep` — the directory is already gone, and `remove`
would only ask git to delete what git has deleted.

Preconditions, all of them required:

| Condition | Why |
|---|---|
| Running inside a linked worktree | Nothing to tear down otherwise |
| The merge succeeded | Cleanup never precedes integration |
| The push succeeded | The same rule that governs branch deletion |
| Neither `--keep-worktree` nor `--keep-branch` | Explicit opt-out |

Opt out with `--keep-worktree` when the work continues in that worktree after
the push. `--keep-branch` implies it, since a branch kept without its worktree
is the orphan this exists to prevent.

**Failure here is never fatal.** The merge and the push have already
succeeded, so the work is on the default branch and on the remote. If git
refuses the removal — it does when the tree holds modified or untracked files,
which is the last guard against deleting work the commit missed — the script
keeps the worktree, reports `worktree_remove_error`, and still exits `0`.
It never passes `--force`.

A lock *is* released first: Claude Code locks the worktrees it creates, and
git refuses to remove a locked one. Unlocking is safe only because the script
is running inside the very worktree the lock names — so it unlocks nothing
else. Point `--repo` at a worktree you are *not* in and the lock stands, the
removal is refused, and the result says `worktree_locked_elsewhere`. The commit,
merge, and push still happen; another session's claim is never broken.

## Authorization

The workspace rules require asking before merging and before pushing. Invoking
this skill *is* that authorization — merging and pushing are its whole point,
and it is invoked per run.

That authorization does not extend past the current run. If the user asks to
"commit" without invoking this skill, use `--no-merge` or `/projects-git-commit`
and stop at the commit.

Use `--dry-run` when the working tree is mixed or the repo is unfamiliar. It
prints the plan and changes nothing.

## Related

- `/projects-git-commit` — the multi-project equivalent, merge and push opt-in
- `/projects-git-status` — what is uncommitted across the whole workspace
- `/projects-git-cleanup` — delete merged `claude_*` and `worktree-*` branches
  left by `--keep-branch`, `--keep-worktree`, or a run predating the teardown
