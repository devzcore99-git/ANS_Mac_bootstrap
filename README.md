# ANS_Mac_bootstrap

Declarative macOS setup for a fresh Apple Silicon Mac: system preferences, CLI
tools, GUI apps, and shell config, applied from one command.

Despite the `ANS_` prefix — which means Ansible everywhere else in this
workspace — there is no Ansible here. This is a [nix-darwin](https://github.com/nix-darwin/nix-darwin)
+ [home-manager](https://github.com/nix-community/home-manager) flake driven by
a `bootstrap.sh` wrapper; the directory name predates the convention.

## Status

Working and in use on one machine (`Austins-MacBook-Air`). No `flake.lock` is
committed yet — see [Caveats](#caveats).

## Setup

Prerequisites on a fresh machine:

- **Apple Silicon.** `flake.nix` hardcodes `system = "aarch64-darwin"`. On an
  Intel Mac the script installs Nix and Homebrew before failing at the build.
- **An admin account.** The script prompts for `sudo` immediately and holds the
  credential for its duration.
- **Network access**, and an **interactive terminal** — the Xcode Command Line
  Tools step waits on a keypress.
- **Signed into the App Store** if you want the `masApps` entries to install.
  `mas` cannot sign in on macOS 10.15+, so unsigned machines silently skip them.
- Nothing else. `git` arrives with the Command Line Tools; running `git clone`
  on a bare macOS install triggers that installer itself.

Then:

```sh
git clone https://github.com/devzcore99-git/ANS_Mac_bootstrap.git
cd ANS_Mac_bootstrap
./bootstrap.sh
```

`bootstrap.sh` installs Xcode CLT, Nix (Determinate installer), and Homebrew,
then builds `darwinConfigurations.<hostname>` and activates it as root. It must
be run from inside a git clone — flakes only read git-tracked files, so a copied
or downloaded directory will not evaluate.

**Before the first run on a new machine, edit `user.nix`.** It is committed with
this machine's identity (`username = "ahill"`, `hostname =
"Austins-MacBook-Air"`), and `hosts/macbook.nix` applies the hostname to the
machine — so an unedited run renames your Mac. `bootstrap.sh` and the `rebuild`
function both select the configuration by the hostname in `user.nix`, so it need
not match `scutil --get LocalHostName` beforehand — but a bare
`darwin-rebuild switch --flake <path>` does default to the live hostname and
will fail until the two agree. `home/git.nix` also still carries a placeholder `userEmail =
"you@example.com"`, which becomes the author of every commit until changed.

## Usage

After bootstrap, edit the `.nix` files and re-apply from a new shell:

```sh
cd /wherever/ANS_Mac_bootstrap
rebuild        # runs: darwin-rebuild switch --flake <resolved-dir>#<hostname>
```

`rebuild` is a zsh function (`home/zsh.nix`) that resolves the flake path when
you call it, so the clone can live anywhere — an external volume included. It
takes the first of:

1. `$FLAKE_DIR`, if set — `FLAKE_DIR=/Volumes/SSD/ANS_Mac_bootstrap rebuild`
2. the nearest ancestor of the current directory holding both `flake.nix` and
   `user.nix` — so `cd`ing into the clone is enough
3. `flakeDir` from `user.nix`, if you set it to an absolute path

With none of the three it prints what to do and exits 1 rather than guessing.
Any extra arguments go through to `darwin-rebuild` (`rebuild --show-trace`).
The hostname from `user.nix` is passed explicitly, so the build no longer
depends on the live hostname matching it.

`bootstrap.sh` itself is only for prerequisites; the `.nix` files are the single
source of truth. Nothing is generated — edit them directly.

To see what a machine actually has installed and how (Homebrew casks, formulae,
App Store apps, manual installs, Nix, language package managers, loose
binaries):

```sh
./Utilities/software-audit.sh            # user-installed software
./Utilities/software-audit.sh --origins  # plus download URLs for manual installs
./Utilities/software-audit.sh --all      # plus Apple/system apps
```

It is standalone, read-only, and safe to copy to any Mac.

## What it configures

| Area | File | Contents |
|------|------|----------|
| macOS defaults | `modules/system.nix` | Dock, Finder, key repeat, trackpad, Touch ID for `sudo` |
| CLI via Nix | `modules/packages.nix` | `git`, `gh`, `ripgrep` |
| Apps via Homebrew | `modules/homebrew.nix` | taps, formulae (`mas`, `opencode`, `btop`, `docker`, `nmap`, …), casks (browsers, VS Code, Docker Desktop, KeePassXC, …), App Store apps |
| Shell | `modules/shell.nix`, `home/zsh.nix` | zsh as login shell, autosuggestions, syntax highlighting, starship, zoxide, fzf, eza/bat aliases |
| Git | `home/git.nix` | identity, delta diffs, aliases, `pull.rebase`, `zdiff3` |
| Host wiring | `hosts/macbook.nix` | hostname, primary user, `allowUnfree`, `nix.enable = false` (Determinate manages Nix) |

`home/default.nix` also installs Claude Code by curling `claude.ai/install.sh`
during home-manager activation, guarded so it only installs once.

## Caveats

**No committed `flake.lock`.** All three inputs float — `nixpkgs-unstable`,
`nix-darwin` master, `home-manager` master — so each bootstrap resolves to
whatever those branches are that day. Two runs a year apart produce different
systems, with no known-good revision to roll back to. `bootstrap.sh` runs
`git add -A`, which stages the lock file `nix build` generates, but nothing
commits it. Fix with `nix flake lock` and commit the result.

**Re-running is guarded but not inert.** Every install step checks first
(`xcode-select -p`, Nix, `brew`, `user.nix`), so re-running skips what is already
there, and the nix-darwin activation is declarative — the same config converges
to the same state. But `modules/homebrew.nix` sets `autoUpdate`, `upgrade`, and
`cleanup = "zap"` on activation, so *every* run does a full `brew update`,
upgrades all casks and formulae, and uninstalls anything not declared in that
file. A one-line Finder tweak is therefore a multi-minute, potentially
destructive operation. `little-snitch` is a system extension that needs
re-approval if it gets zapped. And `git add -A` stages your entire working tree
into the index on each run, without showing what it staged.

**Machine identity is committed.** `user.nix` is tracked and must stay tracked
(untracked files are invisible to flake evaluation), which means a second user's
edits are a permanent local diff that conflicts on every pull.

## Notes

- Nix owns CLI tools, Homebrew owns GUI apps and App Store installs. A few
  formulae are deliberate exceptions, annotated in `modules/homebrew.nix`;
  `curl` and `jq` are deliberately omitted because macOS ships both.
- `nix.enable = false` is intentional — the Determinate installer manages the
  Nix daemon, so nix-darwin must not fight it for control.
- Both scripts target the bash 3.2 that macOS ships, so the `#!/bin/bash`
  shebangs are accurate — no associative arrays or `mapfile`.
- `recommendations.md` holds a fuller review, including items not covered here.
