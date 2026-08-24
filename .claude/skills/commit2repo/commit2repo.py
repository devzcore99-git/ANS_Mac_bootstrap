#!/usr/bin/env python3
"""commit2repo - gather repo changes, then branch/commit/merge/push in one shot.

Subcommands, so a full cycle costs exactly two tool calls:
  gather  read-only; emits JSON describing what would be committed
  run     performs branch -> add -> commit -> merge -> push
  merge   integrates an already-committed branch: merge -> push, no commit

Standard library only. Requires git on PATH.
"""

import argparse
import json
import os
import re
import subprocess
import sys

DEFAULT_DIFF_LINES = 300
DEFAULT_REMOTE = "origin"
BRANCH_PREFIX = "claude_"
FALLBACK_SLUG = "commit2repo"
MAX_SLUG = 40

# Conventional-commit prefixes stripped when deriving a branch slug.
CC_PREFIX = re.compile(
    r"^(feat|fix|docs|refactor|test|chore|perf|build|ci|style|revert)"
    r"(\([^)]*\))?!?:\s*",
    re.IGNORECASE,
)

EXIT_OK = 0
EXIT_GIT_FAILED = 1
EXIT_USAGE = 2
EXIT_NOTHING = 3


def die(msg, code=EXIT_USAGE, **extra):
    """Emit a JSON error to stdout and exit. Errors must enable the next attempt."""
    payload = {"ok": False, "error": msg}
    payload.update(extra)
    print(json.dumps(payload, indent=2))
    sys.exit(code)


def git(repo, *args, check=True, raw=False):
    """Run a git command. Returns (rc, stdout, stderr).

    stdout is stripped unless raw=True. Porcelain output must use raw: a
    status line for an unstaged-only change begins with a space (" M path"),
    and stripping it shifts the first entry by one character, corrupting both
    the path and the staged/unstaged classification.
    """
    proc = subprocess.run(
        ["git", "-C", repo, *args],
        capture_output=True,
        text=True,
    )
    if check and proc.returncode != 0:
        die(
            "git %s failed: %s" % (" ".join(args), proc.stderr.strip() or "no output"),
            EXIT_GIT_FAILED,
            git_args=list(args),
            git_stderr=proc.stderr.strip(),
        )
    return proc.returncode, proc.stdout if raw else proc.stdout.strip(), proc.stderr.strip()


def repo_root(start):
    proc = subprocess.run(
        ["git", "-C", start, "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        die(
            "not inside a git repository: %s. cd into a repo, or pass --repo PATH." % start,
            EXIT_USAGE,
        )
    return proc.stdout.strip()


def current_branch(repo):
    rc, out, _ = git(repo, "symbolic-ref", "--short", "-q", "HEAD", check=False)
    return out if rc == 0 and out else None  # None means detached HEAD


def default_branch(repo):
    """main if the ref exists, else master. Matches the other workspace skills."""
    for name in ("main", "master"):
        rc, _, _ = git(repo, "show-ref", "--verify", "--quiet",
                       "refs/heads/%s" % name, check=False)
        if rc == 0:
            return name
    return None


def worktrees(repo):
    """Every worktree of this repository, main first, as parsed porcelain records.

    Refs are shared across worktrees but HEADs are not, and git refuses to
    check out, fetch into, or delete a branch that *any* worktree holds. This
    listing is the only view of that, so every branch-level decision below is
    made from it rather than from the current HEAD alone.
    """
    _, out, _ = git(repo, "worktree", "list", "--porcelain", raw=True)
    entries, cur = [], None
    for line in out.splitlines():
        if line.startswith("worktree "):
            cur = {"path": line[len("worktree "):], "branch": None,
                   "bare": False, "detached": False, "locked": None}
            entries.append(cur)
        elif cur is None:
            continue
        elif line == "bare":
            cur["bare"] = True
        elif line == "detached":
            cur["detached"] = True
        elif line == "locked" or line.startswith("locked "):
            # Claude Code locks the worktrees it creates, and git refuses to
            # remove a locked one. A bare `locked` line means locked with no
            # reason, which still blocks - so "" must stay distinct from None.
            cur["locked"] = line[len("locked "):] if line != "locked" else ""
        elif line.startswith("branch "):
            ref = line[len("branch "):]
            prefix = "refs/heads/"
            cur["branch"] = ref[len(prefix):] if ref.startswith(prefix) else ref
    return entries


def lock_reason(repo, path, entries=None):
    """Lock reason for the worktree at `path`, or None when it is not locked."""
    target = os.path.realpath(path)
    for wt in entries if entries is not None else worktrees(repo):
        if os.path.realpath(wt["path"]) == target:
            return wt["locked"]
    return None


def merge_location(repo, branch, entries=None):
    """Where a merge into `branch` has to run: (path, is_self).

    is_self is the ordinary single-worktree case - nobody else holds the
    branch, so `repo` checks it out itself exactly as before. Otherwise the
    holder is a different directory (the main worktree, when Claude Code has
    put this session in `.claude/worktrees/<name>`), the merge is issued there,
    and this tree never leaves the branch it is working on.
    """
    if entries is None:
        entries = worktrees(repo)
    here = os.path.realpath(repo)
    for wt in entries:
        if wt["branch"] == branch:
            return (repo, True) if os.path.realpath(wt["path"]) == here \
                else (wt["path"], False)
    return repo, True


def dirty_paths(path):
    """Paths making `path` dirty; empty when the tree is clean.

    raw=True for the same reason porcelain() needs it: an unstaged-only change
    begins with a space, and stripping shifts every path two characters left.
    """
    _, out, _ = git(path, "status", "--porcelain=v1", "-uall", raw=True)
    return [line[3:] for line in out.splitlines() if len(line) > 3]


def worktree_context(repo, default):
    """(in_linked_worktree, main_worktree, merge_dir, merge_here) in one pass.

    Being in a linked worktree and needing the merge elsewhere are separate
    facts - a worktree whose default branch is checked out nowhere merges in
    place - so both are derived here rather than inferred from each other.
    """
    entries = worktrees(repo)
    main_wt = entries[0]["path"] if entries else repo
    in_worktree = os.path.realpath(main_wt) != os.path.realpath(repo)
    merge_dir, merge_here = (merge_location(repo, default, entries) if default
                             else (repo, True))
    return in_worktree, main_wt, merge_dir, merge_here


def teardown_worktree(worktree, main_wt, branch, default, result, steps):
    """Remove the linked worktree we are standing in, then delete its branch.

    Runs only after a successful merge *and* push, so everything here is
    cleanup of state that exists nowhere else. Failure is therefore never
    fatal: the work is already on the default branch and on the remote, and
    leaving the worktree in place costs the user one command, not any commits.

    `git worktree remove` does not delete the branch - it only releases it -
    so the explicit deletion afterwards is what actually finishes the cycle.
    """
    # Whether this process is *inside* the worktree decides whether its lock is
    # ours to release. Normally it is - the user runs this from the worktree -
    # but `--repo` can name someone else's, and that lock is not ours to break.
    target = os.path.realpath(worktree)
    try:
        here = os.path.realpath(os.getcwd())
    except OSError:
        here = None
    standing_in = here is not None and (
        here == target or here.startswith(target + os.sep))

    # Stand somewhere that will still exist. Every later subprocess inherits
    # this process's cwd, and it is about to be deleted out from under us.
    try:
        os.chdir(main_wt)
    except OSError:
        pass

    reason = lock_reason(main_wt, worktree)
    if reason is not None and standing_in:
        # Claude Code locks the worktrees it creates and git will not remove a
        # locked one. This lock names the worktree we are running inside, so
        # releasing it is not overriding another live session.
        git(main_wt, "worktree", "unlock", worktree, check=False)
        result["unlocked_worktree"] = reason or True
    elif reason is not None:
        # Locked, and we are not in it. Leave the lock alone: the removal below
        # will fail, and reporting that beats breaking another session's claim.
        result["worktree_locked_elsewhere"] = reason or True

    rc, _, err = git(main_wt, "worktree", "remove", worktree, check=False)
    if rc != 0:
        # Never --force. git refuses when the tree holds modified or untracked
        # files, and that refusal is the last guard against deleting work the
        # commit did not sweep up.
        result["kept_branch"] = branch
        result["kept_worktree"] = worktree
        result["worktree_remove_error"] = err
        result["note"] = (
            "Merged and pushed, but the worktree at %s could not be removed, so "
            "%s stays too. git said: %s" % (worktree, branch, err))
        steps.append({"step": "remove_worktree", "path": worktree,
                      "skipped": err})
        return

    result["removed_worktree"] = worktree
    result["cwd_removed"] = True
    result["next_dir"] = main_wt
    steps.append({"step": "remove_worktree", "path": worktree})

    # `git branch -d` measures "merged" against the HEAD of whichever tree
    # issues it, and after a worktree run that tree can be on any branch at
    # all - so -d refuses a branch that *is* fully merged into the default one.
    # Ask the question we actually mean, then -D on a verified answer.
    rc, unmerged, _ = git(main_wt, "rev-list", "--count",
                          "%s..%s" % (default, branch), check=False)
    if rc != 0 or unmerged.strip() != "0":
        result["kept_branch"] = branch
        result["branch_delete_error"] = (
            "%s has %s commit(s) %s does not contain; kept rather than deleted."
            % (branch, unmerged.strip() or "?", default))
        steps.append({"step": "delete_branch", "name": branch,
                      "skipped": "not contained in %s" % default})
        return

    rc, _, err = git(main_wt, "branch", "-D", branch, check=False)
    if rc != 0:
        result["kept_branch"] = branch
        result["branch_delete_error"] = err
        steps.append({"step": "delete_branch", "name": branch, "skipped": err})
        return
    result["deleted_branch"] = branch
    steps.append({"step": "delete_branch", "name": branch})


def plan_teardown(repo, branch, in_worktree, merge_here, args):
    """The branch/worktree teardown `merge_and_push` would do, as dry-run steps.

    Shared with the real path's decision order so `--dry-run` cannot claim one
    thing and `run` do another.
    """
    if args.keep_branch:
        return [{"step": "delete_branch", "name": branch,
                 "skipped": "--keep-branch"}]
    if in_worktree and not args.keep_worktree:
        return [{"step": "remove_worktree", "path": repo},
                {"step": "delete_branch", "name": branch}]
    if merge_here:
        return [{"step": "delete_branch", "name": branch}]
    return [{"step": "delete_branch", "name": branch,
             "skipped": "held by this worktree (--keep-worktree)"}]


def dirty_hint(paths):
    """Extra guidance when the dirt is only the worktree directory itself.

    Claude Code puts worktrees in `.claude/worktrees/`, which is inside the
    repository - so an un-ignored one makes the main worktree permanently
    dirty and blocks every merge. Naming the cause beats leaving the user to
    stare at a tree they believe is clean.
    """
    if paths and all(p.startswith(".claude/") for p in paths):
        return (" The only untracked path is %s - that is the worktree "
                "directory itself. Add `.claude/worktrees/` to .gitignore and "
                "this stops recurring." % ", ".join(sorted(set(paths))[:3]))
    return ""


def porcelain(repo):
    """Parse git status --porcelain into per-file records and counts.

    -uall is load-bearing: without it git collapses a new directory into a
    single `path/` entry, and the diff of everything inside it is invisible.
    """
    _, out, _ = git(repo, "status", "--porcelain=v1", "-uall", "-z", raw=True)
    files, counts = [], {"staged": 0, "unstaged": 0, "untracked": 0}
    fields = out.split("\0") if out else []
    i = 0
    while i < len(fields):
        entry = fields[i]
        i += 1
        if len(entry) < 3:
            continue
        x, y, path = entry[0], entry[1], entry[3:]
        # Renames consume the following NUL-separated original path.
        if x in ("R", "C"):
            i += 1
        if x == "?" and y == "?":
            counts["untracked"] += 1
            state = "untracked"
        else:
            if x != " ":
                counts["staged"] += 1
            if y != " ":
                counts["unstaged"] += 1
            state = (x + y).strip()
        files.append({"status": state, "path": path})
    return files, counts


def untracked_diff(repo, files, budget):
    """Diff untracked files against /dev/null without touching the index.

    git diff HEAD cannot see untracked files, and `git add -N` would mutate the
    index during what must stay a read-only gather.
    """
    chunks, total = [], 0
    for rec in files:
        if rec["status"] != "untracked":
            continue
        full = os.path.join(repo, rec["path"])
        if os.path.isdir(full):
            continue
        rc, out, _ = git(repo, "diff", "--no-index", "--no-color",
                         "--", os.devnull, rec["path"], check=False)
        # --no-index exits 1 when files differ, which is the normal case here.
        if rc not in (0, 1) or not out:
            continue
        lines = out.splitlines()
        # Count every line even once the budget is spent, or the truncation
        # warning reports a total as small as the cap and reads as complete.
        total += len(lines)
        if budget > 0:
            chunks.extend(lines[:budget])
            budget -= min(len(lines), budget)
    return chunks, total


def cmd_gather(args):
    repo = repo_root(args.repo or os.getcwd())
    branch = current_branch(repo)
    default = default_branch(repo)

    files, counts = porcelain(repo)
    clean = not files

    in_worktree, main_wt, merge_dir, merge_here = worktree_context(repo, default)

    remotes = dict(
        line.split("\t", 1)
        for line in git(repo, "remote", "-v")[1].splitlines()
        if "\t" in line and line.endswith("(fetch)")
    )
    remotes = {k: v.rsplit(" ", 1)[0] for k, v in remotes.items()}

    result = {
        "ok": True,
        "repo_root": repo,
        "project": os.path.basename(repo),
        "current_branch": branch,
        "detached_head": branch is None,
        "default_branch": default,
        "on_claude_branch": bool(branch and branch.startswith(BRANCH_PREFIX)),
        "in_linked_worktree": in_worktree,
        "main_worktree": main_wt,
        "merge_dir": merge_dir,
        "clean": clean,
        "counts": counts,
        "files": files,
        "target_remote": args.remote,
        "target_remote_url": remotes.get(args.remote),
        "other_remotes": sorted(k for k in remotes if k != args.remote),
        "warnings": [],
    }

    if clean:
        result["stat"] = ""
        result["diff"] = ""
        result["warnings"].append("Working tree is clean - nothing to commit.")
        print(json.dumps(result, indent=2))
        return EXIT_NOTHING

    if branch is None:
        result["warnings"].append(
            "Detached HEAD. Check out a branch before running `run`.")
    if default is None:
        result["warnings"].append("No main or master branch found.")
    if args.remote not in remotes:
        result["warnings"].append(
            "No remote named '%s'. Push will be skipped or must be redirected "
            "with --remote." % args.remote)
    if result["other_remotes"]:
        result["warnings"].append(
            "Other remotes present (%s); only '%s' is ever pushed."
            % (", ".join(result["other_remotes"]), args.remote))
    if not merge_here:
        blockers = dirty_paths(merge_dir)
        if blockers:
            result["warnings"].append(
                "%s is checked out at %s and that tree is dirty, so `run` will "
                "refuse to merge. Clean it first, or use --no-merge.%s"
                % (default, merge_dir, dirty_hint(blockers)))
        else:
            result["warnings"].append(
                "In a linked worktree; the merge into %s will run at %s. The "
                "current branch (%s) is reused rather than nested, and after a "
                "successful push `run` removes this worktree (%s) and deletes "
                "the branch. This directory will no longer exist - work from "
                "%s afterwards, or pass --keep-worktree."
                % (default, merge_dir, branch, repo, merge_dir))

    _, stat, _ = git(repo, "diff", "HEAD", "--stat", "--no-color")
    result["stat"] = stat

    _, tracked, _ = git(repo, "diff", "HEAD", "--no-color",
                        "--diff-algorithm=histogram")
    tracked_lines = tracked.splitlines() if tracked else []

    shown = tracked_lines[: args.diff_lines]
    extra, untracked_total = untracked_diff(
        repo, files, args.diff_lines - len(shown))
    shown.extend(extra)

    total = len(tracked_lines) + untracked_total
    result["diff"] = "\n".join(shown)
    result["diff_lines_shown"] = len(shown)
    result["diff_lines_total"] = total
    result["diff_truncated"] = total > len(shown)
    if result["diff_truncated"]:
        result["warnings"].append(
            "Diff truncated at %d of %d lines. Write the message from the stat "
            "and the visible hunks; raise --diff-lines only if the change is "
            "genuinely unclear." % (len(shown), total))

    print(json.dumps(result, indent=2))
    return EXIT_OK


def slugify(message):
    """Derive a branch slug from a commit message subject."""
    subject = message.strip().splitlines()[0] if message.strip() else ""
    subject = CC_PREFIX.sub("", subject)
    slug = re.sub(r"[^a-z0-9]+", "-", subject.lower()).strip("-")
    if len(slug) > MAX_SLUG:
        slug = slug[:MAX_SLUG].rstrip("-")
    return slug or FALLBACK_SLUG


def unique_branch(repo, name):
    """Return name, or name-2/name-3/... if refs already exist."""
    candidate, n = name, 1
    while True:
        rc, _, _ = git(repo, "show-ref", "--verify", "--quiet",
                       "refs/heads/%s" % candidate, check=False)
        if rc != 0:
            return candidate
        n += 1
        candidate = "%s-%d" % (name, n)


def cmd_run(args):
    repo = repo_root(args.repo or os.getcwd())
    steps = []
    result = {"ok": True, "repo_root": repo, "project": os.path.basename(repo),
              "dry_run": args.dry_run, "steps": steps}

    files, _ = porcelain(repo)
    if not files:
        die("nothing to commit; working tree is clean.", EXIT_NOTHING,
            repo_root=repo)

    start = current_branch(repo)
    if start is None:
        die("detached HEAD; check out a branch first.", EXIT_GIT_FAILED,
            repo_root=repo)

    default = default_branch(repo)
    if default is None:
        die("no main or master branch found.", EXIT_GIT_FAILED, repo_root=repo)

    in_worktree, main_wt, merge_dir, merge_here = worktree_context(repo, default)

    # Reuse the branch we are on; never nest one inside another. A linked
    # worktree always qualifies: EnterWorktree names its branch
    # `worktree-<name>`, which no claude_ check can match, and cutting a
    # second branch inside the worktree is precisely the nesting this rule
    # exists to prevent.
    if start.startswith(BRANCH_PREFIX) or in_worktree:
        branch, reused = start, True
    else:
        branch = args.branch or (BRANCH_PREFIX + slugify(args.message))
        branch = unique_branch(repo, branch)
        reused = False
    result["branch"] = branch
    result["reused_branch"] = reused
    result["merged_from"] = start

    result["merge_dir"] = merge_dir
    result["in_linked_worktree"] = in_worktree

    if args.dry_run:
        steps.append({"step": "branch", "action":
                      "reuse" if reused else "create", "name": branch})
        steps.append({"step": "commit", "message": args.message,
                      "files": len(files)})
        if args.merge:
            steps.append({"step": "merge", "into": default, "in": merge_dir})
            blockers = [] if merge_here else dirty_paths(merge_dir)
            if blockers:
                result["blocked"] = (
                    "%s is checked out at %s and that tree is dirty; the merge "
                    "would be refused.%s"
                    % (default, merge_dir, dirty_hint(blockers)))
            if args.push:
                steps.append({"step": "push", "remote": args.remote,
                              "ref": default})
                # Teardown is gated on a successful push in the real path, so
                # the plan has to nest it the same way.
                steps.extend(plan_teardown(repo, branch, in_worktree,
                                           merge_here, args))
        print(json.dumps(result, indent=2))
        return EXIT_OK

    if not reused:
        git(repo, "checkout", "-b", branch)
        steps.append({"step": "branch", "action": "create", "name": branch})
    else:
        steps.append({"step": "branch", "action": "reuse", "name": branch})

    git(repo, "add", "-A")
    rc, _, _ = git(repo, "diff", "--cached", "--quiet", check=False)
    if rc == 0:
        die("nothing staged after `git add -A`; refusing to create an empty "
            "commit.", EXIT_NOTHING, repo_root=repo, branch=branch)

    git(repo, "commit", "-m", args.message)
    _, sha, _ = git(repo, "rev-parse", "HEAD")
    result["commit"] = sha
    steps.append({"step": "commit", "sha": sha, "files": len(files)})

    if not args.merge:
        result["note"] = "Committed on %s; not merged (--no-merge)." % branch
        print(json.dumps(result, indent=2))
        return EXIT_OK

    return merge_and_push(repo, branch, default, merge_dir, merge_here,
                          in_worktree, main_wt, args, result, steps)


def merge_and_push(repo, branch, default, merge_dir, merge_here,
                   in_worktree, main_wt, args, result, steps):
    """Merge `branch` into `default`, push, then tear down branch and worktree.

    Shared by `run` and `merge` so the two cannot drift on the things that are
    easy to get wrong: aborting a conflict cleanly, pushing an explicit refspec
    to one named remote, and removing a linked worktree before its branch.
    """
    if merge_here:
        git(repo, "checkout", default)
    else:
        blockers = dirty_paths(merge_dir)
        if blockers:
            # Refusing here costs nothing: the work is already committed on the
            # branch, so the run is resumable once that tree is clean.
            die("%s is checked out at %s, so the merge has to run there, and "
                "that tree is dirty. Your work is committed on %s. Commit or "
                "stash in %s and re-run.%s"
                % (default, merge_dir, branch, merge_dir, dirty_hint(blockers)),
                EXIT_GIT_FAILED, repo_root=repo, branch=branch,
                merge_dir=merge_dir, dirty=blockers[:10], committed=True)

    rc, _, err = git(merge_dir, "merge", "--no-ff", branch,
                     "-m", "Merge branch '%s'" % branch, check=False)
    if rc != 0:
        # Leave no repository mid-merge: abort and return to where we started.
        # Only the self case moved HEAD, so only it has a checkout to undo.
        git(merge_dir, "merge", "--abort", check=False)
        if merge_here:
            git(repo, "checkout", branch, check=False)
        die("merge of %s into %s conflicted at %s and was aborted; you are "
            "still on %s. Resolve by hand."
            % (branch, default, merge_dir, branch),
            EXIT_GIT_FAILED, repo_root=repo, branch=branch,
            merge_dir=merge_dir, merge_stderr=err)
    result["merged_into"] = default
    steps.append({"step": "merge", "into": default, "in": merge_dir})

    if args.push:
        if args.remote not in _remote_names(repo):
            die("no remote named '%s'; merge succeeded but nothing was pushed."
                % args.remote, EXIT_GIT_FAILED, repo_root=repo,
                branch=branch, merged_into=default)
        # Always an explicit remote and refspec. Never `git push --all`, never
        # a bare `git push`, which could reach a non-origin production remote.
        rc, _, err = git(repo, "push", args.remote, default, check=False)
        if rc != 0:
            die("push to %s/%s failed; the merge is committed locally. Never "
                "force-push to recover - fetch and reconcile first. git said: %s"
                % (args.remote, default, err),
                EXIT_GIT_FAILED, repo_root=repo, branch=branch,
                merged_into=default, pushed=False)
        result["pushed"] = "%s/%s" % (args.remote, default)
        steps.append({"step": "push", "remote": args.remote, "ref": default})

        if args.keep_branch:
            result["kept_branch"] = branch
            steps.append({"step": "delete_branch", "name": branch,
                          "skipped": "--keep-branch"})
        elif in_worktree and not args.keep_worktree:
            # A worktree holds its branch, so the branch cannot be deleted
            # while the worktree exists. Removing the worktree is the only
            # thing that finishes the cycle - do it here rather than leaving
            # it as manual cleanup nobody remembers.
            teardown_worktree(repo, main_wt, branch, default, result, steps)
        elif merge_here:
            git(repo, "branch", "-d", branch)
            result["deleted_branch"] = branch
            steps.append({"step": "delete_branch", "name": branch})
        else:
            # --keep-worktree: the worktree still holds the branch, and git
            # will not delete a branch any worktree holds, so both survive.
            result["kept_branch"] = branch
            result["kept_worktree"] = repo
            result["note"] = (
                "%s stays: --keep-worktree left %s in place and a worktree "
                "holds its branch. `git worktree remove %s` drops both."
                % (branch, repo, repo))
            steps.append({"step": "delete_branch", "name": branch,
                          "skipped": "held by this worktree (--keep-worktree)"})
    else:
        result["pushed"] = False

    print(json.dumps(result, indent=2))
    return EXIT_OK


def cmd_merge(args):
    """Merge the current branch into main/master without committing anything.

    The gap this fills: `run` requires a message and refuses a clean tree, so a
    branch whose work is already committed - the normal state after working in
    a worktree across turns - had no path through this script at all.
    """
    repo = repo_root(args.repo or os.getcwd())
    steps = []
    result = {"ok": True, "repo_root": repo, "project": os.path.basename(repo),
              "dry_run": args.dry_run, "steps": steps}

    branch = current_branch(repo)
    if branch is None:
        die("detached HEAD; check out the branch you want to merge.",
            EXIT_GIT_FAILED, repo_root=repo)

    default = default_branch(repo)
    if default is None:
        die("no main or master branch found.", EXIT_GIT_FAILED, repo_root=repo)

    if branch == default:
        die("already on %s, so there is no branch to merge. Check out the "
            "branch you want merged first." % default,
            EXIT_USAGE, repo_root=repo, branch=branch)

    # `merge` integrates only what is already committed. Silently leaving
    # uncommitted work behind on the branch is the one surprise worth refusing.
    blockers = dirty_paths(repo)
    if blockers:
        die("working tree at %s has uncommitted changes and `merge` only "
            "integrates commits, so that work would be left behind. Use "
            "`run -m \"...\"` to commit and merge in one step, or commit by "
            "hand first.%s" % (repo, dirty_hint(blockers)),
            EXIT_USAGE, repo_root=repo, branch=branch, dirty=blockers[:10])

    _, ahead, _ = git(repo, "rev-list", "--count", "%s..%s" % (default, branch))
    ahead = int(ahead or 0)
    if ahead == 0:
        die("%s has no commits that %s lacks; nothing to merge."
            % (branch, default), EXIT_NOTHING, repo_root=repo,
            branch=branch, merged_into=default)

    in_worktree, main_wt, merge_dir, merge_here = worktree_context(repo, default)
    result["branch"] = branch
    result["merged_from"] = branch
    result["commits"] = ahead
    result["merge_dir"] = merge_dir
    result["in_linked_worktree"] = in_worktree

    if args.dry_run:
        steps.append({"step": "merge", "into": default, "in": merge_dir,
                      "commits": ahead})
        pending = [] if merge_here else dirty_paths(merge_dir)
        if pending:
            result["blocked"] = (
                "%s is checked out at %s and that tree is dirty; the merge "
                "would be refused.%s"
                % (default, merge_dir, dirty_hint(pending)))
        if args.push:
            steps.append({"step": "push", "remote": args.remote, "ref": default})
            steps.extend(plan_teardown(repo, branch, in_worktree,
                                       merge_here, args))
        print(json.dumps(result, indent=2))
        return EXIT_OK

    return merge_and_push(repo, branch, default, merge_dir, merge_here,
                          in_worktree, main_wt, args, result, steps)


def _remote_names(repo):
    _, out, _ = git(repo, "remote")
    return set(out.splitlines())


def build_parser():
    p = argparse.ArgumentParser(
        prog="commit2repo.py",
        description="Gather repo changes, then branch/commit/merge/push in one shot.",
        epilog="""exit codes:
  0  success
  1  a git command failed
  2  usage or environment error
  3  nothing to commit, or nothing left to merge

examples:
  commit2repo.py gather
  commit2repo.py gather --diff-lines 600
  commit2repo.py run -m "fix: correct ref pattern"
  commit2repo.py run -m "docs: update readme" --dry-run
  commit2repo.py run -m "chore: tidy" --no-push
  commit2repo.py run -m "feat: x" --keep-worktree   # keep working in it
  commit2repo.py merge                     # already committed; just integrate
  commit2repo.py merge --dry-run

in a linked worktree a successful push also removes the worktree and deletes
its branch, so the working directory is gone when the command returns; the
JSON reports cwd_removed and next_dir.
""",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--repo", metavar="PATH",
                        help="repository path (default: current directory)")
    common.add_argument("--remote", default=DEFAULT_REMOTE, metavar="NAME",
                        help="remote to push (default: %s). Only this remote "
                             "is ever pushed." % DEFAULT_REMOTE)

    g = sub.add_parser("gather", parents=[common],
                       help="read-only; emit JSON describing pending changes")
    g.add_argument("--diff-lines", type=int, default=DEFAULT_DIFF_LINES,
                   metavar="N",
                   help="cap the embedded diff at N lines (default: %d)"
                        % DEFAULT_DIFF_LINES)

    r = sub.add_parser("run", parents=[common],
                       help="branch, commit, merge, and push")
    r.add_argument("-m", "--message", required=True,
                   help="commit message (required)")
    r.add_argument("--branch", metavar="NAME",
                   help="branch name (default: claude_<slug of message>)")
    r.add_argument("--no-merge", dest="merge", action="store_false",
                   help="commit on the branch only; do not merge")
    r.add_argument("--no-push", dest="push", action="store_false",
                   help="merge but do not push")
    r.add_argument("--keep-branch", action="store_true",
                   help="keep the claude_ branch after a successful push; "
                        "implies --keep-worktree")
    r.add_argument("--keep-worktree", action="store_true",
                   help="in a linked worktree, leave it (and its branch) on "
                        "disk instead of removing both after the push")
    r.add_argument("--dry-run", action="store_true",
                   help="print the plan; change nothing")

    m = sub.add_parser("merge", parents=[common],
                       help="merge the current branch into main/master and "
                            "push; commits nothing")
    m.add_argument("--no-push", dest="push", action="store_false",
                   help="merge but do not push")
    m.add_argument("--keep-branch", action="store_true",
                   help="keep the branch after a successful push; implies "
                        "--keep-worktree")
    m.add_argument("--keep-worktree", action="store_true",
                   help="in a linked worktree, leave it (and its branch) on "
                        "disk instead of removing both after the push")
    m.add_argument("--dry-run", action="store_true",
                   help="print the plan; change nothing")
    return p


def main():
    args = build_parser().parse_args()
    if args.cmd == "gather":
        return cmd_gather(args)
    if args.cmd == "merge":
        return cmd_merge(args)
    return cmd_run(args)


if __name__ == "__main__":
    sys.exit(main())
