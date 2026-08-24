"""Shared git invocation for the skills in this directory.

What is shared here is the *invocation* — the environment, the encoding, the
timeout, and the promise never to raise. Each caller keeps its own thin `git()`
wrapper, because their contracts genuinely differ and collapsing them would be
a rewrite rather than a deduplication:

  * `commit2repo.py` returns a 3-tuple and *dies* on a failed command.
  * the sweep/scan scripts return `(ok, text)` and never die.
  * `bootstrap.py` wants stdout and stderr combined.
  * `opencode_agents.py` hands back a whole `CompletedProcess`.

Two scripts deliberately do NOT import this module:

  * `opencode-agents` is in `bundled_skills`, so `/project-bootstrap` copies it
    into other projects, where this directory does not exist. It must stay
    self-contained or every bootstrapped copy breaks on import.
  * `commit2repo` is the one skill symlinked into `~/.claude/skills/`. It also
    dies rather than returning on failure, so it shares no contract with the
    rest. Leaving it alone keeps the globally-reachable script dependency-free.

Callers resolve this directory through `os.path.realpath(__file__)`, not
`abspath`: a skill reached through a symlink must find the real tree.
"""

import os
import subprocess

# Non-interactive by construction. Without this a repo needing credentials
# blocks a whole parallel scan on a prompt no one can see, until the timeout.
GIT_ENV = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "",
           "SSH_ASKPASS": ""}


def git_run(repo, args, timeout=15, stdin=None, quotepath=False):
    """Run one git command in `repo`. Returns (ok, stdout, stderr).

    Never raises: a timeout or a missing binary comes back as
    ``(False, "", reason)``. Output is returned unstripped so the caller can
    decide — `status --porcelain` encodes staged-vs-unstaged in the first two
    columns, so a leading space is significant and `.strip()` corrupts it.

    quotepath=True adds ``-c core.quotepath=false``, which keeps non-ASCII
    paths readable instead of octal-escaped. Decoding is pinned to UTF-8
    because the Windows console default (cp1252) chokes on git's output.
    """
    cmd = ["git"]
    if quotepath:
        cmd += ["-c", "core.quotepath=false"]
    cmd += ["-C", repo, *args]
    try:
        proc = subprocess.run(
            cmd, input=stdin, capture_output=True, timeout=timeout,
            env=GIT_ENV, encoding="utf-8", errors="replace",
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        return False, "", str(exc) or "git invocation failed"
    return proc.returncode == 0, proc.stdout, proc.stderr


def skills_dir():
    """Absolute path of the .claude/skills directory holding this file."""
    return os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
