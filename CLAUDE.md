# CLAUDE.md - ANS_Mac_bootstrap

Guidance for Claude Code when working in this project.

## Project Overview

Declarative macOS setup for a fresh Apple Silicon Mac: system preferences, CLI
tools, GUI apps, and shell config, applied from one command. The `ANS_` prefix
is misleading — there is no Ansible here. It is a nix-darwin + home-manager
flake (`flake.nix`) with a `bootstrap.sh` wrapper that installs prerequisites
and activates it.

## Conventions

- **The `.nix` files are the source of truth.** Nothing is generated; edit them
  directly. `bootstrap.sh` only installs Xcode CLT, Nix, and Homebrew, then
  builds and activates — it never writes configuration (its `user.nix`
  generation block is unreachable because `user.nix` is tracked).
- **Layout**: `flake.nix` (entry) → `hosts/macbook.nix` → `modules/` (system
  defaults, Nix packages, Homebrew, shell) and `home/` (home-manager: git, zsh).
  `Utilities/software-audit.sh` is a standalone read-only inventory tool,
  unrelated to the flake.
- **Everything must be git-tracked.** Flakes evaluate against the git tree;
  untracked files are invisible even when present on disk. This is why
  `user.nix` is committed rather than gitignored.
- **File modes**: `.nix` files are `644`, the three `.sh` files are `755`, and
  directories are `755`. Git only tracks the executable bit, so the read bits
  and every directory mode come from each machine's umask and never travel
  through a clone — a checkout made under a restrictive umask yields `700`
  directories, and a `700` directory denies traversal to anything inside it no
  matter how open the file itself looks. That is invisible locally and breaks
  the moment the tree is read as another identity: a VM or devcontainer
  mounting this directory, or a build not running as the owner. Re-check with
  `ls -la` after any bulk copy; git will not fix it.
- **Machine-specific**: `user.nix` (`username`, `hostname` — the hostname keys
  the flake output *and* gets applied to the machine — plus optional `flakeDir`,
  threaded to `home/zsh.nix` via `home-manager.extraSpecialArgs` as the last
  fallback for the `rebuild` function, which otherwise resolves the clone from
  `$FLAKE_DIR` or the cwd), and the git identity in `home/git.nix`
  (`settings.user.name` / `settings.user.email`). `flake.nix` hardcodes
  `aarch64-darwin`.
- **Re-run safety**: install steps are guarded and the activation is
  declarative, so re-running converges rather than duplicating. But
  `modules/homebrew.nix` uses `autoUpdate` + `upgrade` + `cleanup = "zap"`, so
  every activation updates and upgrades all of Homebrew and uninstalls anything
  not declared there — never assume a rebuild is cheap or non-destructive.
  `bootstrap.sh` also runs `git add -A` on every run.
- Do not run `bootstrap.sh`, `darwin-rebuild`, or `rebuild` to test a change —
  they modify the live machine.
- Keep scripts inside macOS bash 3.2 features (no associative arrays,
  `mapfile`, or `${var^^}`); the shebangs are `#!/bin/bash`.

## Dependencies

Inputs are **unpinned** — `nixpkgs-unstable`, `nix-darwin` master,
`home-manager` master, with no committed `flake.lock`. Rebuilds are not
reproducible; committing a lock is the top open item in `recommendations.md`.
Homebrew casks and `masApps` are likewise unversioned and track upstream.
