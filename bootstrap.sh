#!/bin/bash
set -euo pipefail

# macOS bootstrap.
#
# This script ONLY installs prerequisites and activates the flake. It does not
# generate configuration. The .nix files in this repository are the single
# source of truth — edit them directly and re-run `rebuild`.
#
# Must be run from inside a clone of the configuration repo:
#   git clone https://github.com/devzcore99-git/ANS_Mac_bootstrap.git
#   cd ANS_Mac_bootstrap && ./bootstrap.sh

echo "==> macOS Bootstrap with Nix"
echo ""

# Prompt for sudo upfront and keep it alive for the duration of the script
echo "==> Admin password required for system configuration."
sudo -v
while true; do sudo -n true; sleep 60; kill -0 "$$" || exit; done 2>/dev/null &
SUDO_KEEPALIVE_PID=$!
trap "kill $SUDO_KEEPALIVE_PID 2>/dev/null" EXIT

# 1. Install Xcode Command Line Tools (needed for git, compilers)
if ! xcode-select -p &>/dev/null; then
  echo "==> Installing Xcode Command Line Tools..."
  xcode-select --install
  echo "Press any key after installation completes..."
  read -n 1
else
  echo "==> Xcode CLT already installed"
fi

# 2. Install Nix
if [ -d "/nix" ] || command -v nix &>/dev/null; then
  echo "==> Nix already installed"
else
  echo "==> Installing Nix..."
  curl --proto '=https' --tlsv1.2 -sSf -L https://install.determinate.systems/nix | sh -s -- install
fi
# Source Nix into the current shell if not already available
if ! command -v nix &>/dev/null; then
  if [ -e "/nix/var/nix/profiles/default/etc/profile.d/nix-daemon.sh" ]; then
    . /nix/var/nix/profiles/default/etc/profile.d/nix-daemon.sh
  elif [ -e "$HOME/.nix-profile/etc/profile.d/nix.sh" ]; then
    . "$HOME/.nix-profile/etc/profile.d/nix.sh"
  fi
fi

# 3. Install Homebrew (needed for casks and mas)
if [ -x "/opt/homebrew/bin/brew" ]; then
  echo "==> Homebrew already installed"
  eval "$(/opt/homebrew/bin/brew shellenv)"
elif [ -x "/usr/local/bin/brew" ]; then
  echo "==> Homebrew already installed"
  eval "$(/usr/local/bin/brew shellenv)"
else
  echo "==> Installing Homebrew..."
  yes '' | /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  eval "$(/opt/homebrew/bin/brew shellenv)"
fi

# 4. Locate the configuration repo
# This script must be run from inside the git clone. No fallback, no cloning.
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ ! -f "$REPO_DIR/flake.nix" ]; then
  echo "!! No flake.nix next to this script ($REPO_DIR)." >&2
  echo "!! Run bootstrap.sh from inside a clone of the configuration repo." >&2
  exit 1
fi
# Nix flakes evaluate against the git tree, so the repo must be a git repo and
# every file the flake reads must be tracked. Untracked files are invisible.
if [ ! -d "$REPO_DIR/.git" ]; then
  echo "!! $REPO_DIR is not a git repository." >&2
  echo "!! Nix flakes read the git tree; clone the repo rather than copying it." >&2
  exit 1
fi
echo "==> Using configuration in $REPO_DIR"

# 5. Ensure user.nix exists (machine identity; not generated if already present)
if [ ! -f "$REPO_DIR/user.nix" ]; then
  CURRENT_USER=$(whoami)
  CURRENT_HOSTNAME=$(scutil --get LocalHostName 2>/dev/null || hostname -s)
  echo "==> Creating user.nix for user: $CURRENT_USER, hostname: $CURRENT_HOSTNAME"
  cat > "$REPO_DIR/user.nix" << EOF
# Machine identity consumed by flake.nix. Must stay git-tracked.
{
  username = "$CURRENT_USER";
  hostname = "$CURRENT_HOSTNAME";
}
EOF
else
  echo "==> Using existing user.nix"
fi

# Read the hostname the flake is keyed on from user.nix, not from the live
# machine — they can legitimately differ if user.nix was edited by hand.
TARGET_HOSTNAME=$(sed -n 's/.*hostname *= *"\(.*\)".*/\1/p' "$REPO_DIR/user.nix")
if [ -z "$TARGET_HOSTNAME" ]; then
  echo "!! Could not read hostname from $REPO_DIR/user.nix" >&2
  exit 1
fi

# 6. Stage everything so the flake can see it
git -C "$REPO_DIR" add -A

# 7. Build and activate
echo "==> Building configuration (this may take a while on first run)..."
SYSTEM_BUILD=$(nix build "$REPO_DIR#darwinConfigurations.$TARGET_HOSTNAME.system" --print-out-paths --no-link)

echo "==> Built: $SYSTEM_BUILD"

echo "==> Activating configuration (requires root)..."
sudo "$SYSTEM_BUILD/activate"

echo ""
echo "==> Done! Your system is configured."
echo "    Edit the .nix files in $REPO_DIR, then run 'rebuild' in a new shell."
