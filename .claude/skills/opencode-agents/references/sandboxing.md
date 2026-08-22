# Confining agents with `--sandbox`

Read this before relying on `--sandbox` for anything that matters, and when it
refuses to start.

Without it, the worktree is a *convention*: nothing stops an agent from writing
elsewhere, and one has already been observed writing its output file into the
calling repository. `--sandbox` makes the boundary a kernel one.

## What it does

Each agent runs under [bubblewrap](https://github.com/containers/bubblewrap):

```
bwrap --ro-bind / /                        # whole filesystem, read-only
      --dev /dev --proc /proc --tmpfs /tmp
      --bind   <worktree>   <worktree>     # the ONLY writable project path
      --bind   <state>      <state>        # private HOME for this task
      --ro-bind ~/.config/opencode <state>/.config/opencode
      --setenv HOME <state>  --setenv PWD <worktree>
      --chdir  <worktree> --die-with-parent --unshare-pid
      opencode run …
```

No root required. Ubuntu ships an AppArmor profile permitting bwrap's user
namespaces even with `kernel.apparmor_restrict_unprivileged_userns=1`.

Verified: an agent told to write
`/home/ahill/AI_Projects/ASST_BBMax/build_report.txt` got
`Read-only file system`, reported the error, and the file was never created.

## Why `.git` stays read-only

Only the worktree is writable — the project's `.git` is not, which prevents an
agent corrupting git metadata. Tested both ways; opencode runs fine with `.git`
read-only, and the dispatcher commits from **outside** the sandbox after the
agent exits, so nothing needs write access to git during the run.

## Why `$HOME` is replaced

Each task gets a private `HOME` at `.opencode-agents/sandbox/<id>/`, so agents
cannot read your SSH keys, shell history, or credentials, and each gets a fresh
opencode database. The real `~/.config/opencode` is bind-mounted **read-only**
into that HOME so the provider definition, API key, the `@ai-sdk/*` npm provider
package, and any global agent files still resolve.

`cleanup` deletes these directories along with the worktrees.

## Limits — read these before trusting it

- **The network is not isolated.** The agent needs to reach the model endpoint,
  so it keeps full outbound access. `--unshare-net` would cut off the model
  too. A confined agent can still make arbitrary network requests; closing that
  needs a proxy or a netns with a pinhole, which this flag does not attempt.

- **Writes to a sandbox-internal tmpfs silently succeed and vanish.** `/tmp` is
  a fresh tmpfs inside the sandbox. An agent writing `/tmp/foo` gets no error,
  and the file disappears when the run ends. Paths under the read-only bind
  error properly; `/tmp` is the exception. If an agent claims it wrote
  something you cannot find, check whether the path was under `/tmp`.

- **It is not a security boundary against hostile code.** It is a guardrail
  against a confused model, which is the actual threat here. Treat a
  deliberately malicious payload as out of scope.

- **Linux only.** `sandbox_status()` reports `available: false` with a reason on
  macOS, and `dispatch --sandbox` exits 3 rather than silently running
  unconfined. The workspace is used from a Mac, so scripts and task files stay
  portable — only the flag is unavailable there.

## When it refuses

```
Error: --sandbox requested but unavailable. bwrap is not installed.
       On Debian/Ubuntu: apt install bubblewrap.
```

`check` reports the same thing under `sandbox`, without needing a dispatch:

```json
"sandbox": { "available": true, "path": "/usr/bin/bwrap" }
```

If bwrap is present but namespace creation fails, the reason carries bwrap's own
stderr — usually a hardened `kernel.unprivileged_userns_clone=0` or an AppArmor
policy, both of which are host configuration rather than anything this skill can
work around.
