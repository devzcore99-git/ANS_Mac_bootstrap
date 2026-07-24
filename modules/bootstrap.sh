#!/bin/bash
set -e

echo "==> macOS Bootstrap with Nix"
echo ""

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

# 4. Build and activate the system configuration
LOCAL_DIR="$HOME/CODE_Mac_bootstrap"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# If running from a non-local path (shared folder, /Volumes, etc.), copy to home directory
case "$SCRIPT_DIR" in
  /Volumes/*|/mnt/*|/media/*)
    echo "==> Detected shared/network volume: $SCRIPT_DIR"
    echo "==> Copying to local path: $LOCAL_DIR"
    rsync -a --delete "$SCRIPT_DIR/" "$LOCAL_DIR/"
    chmod +x "$LOCAL_DIR/bootstrap.sh"
    FLAKE_DIR="$LOCAL_DIR"
    ;;
  "$HOME"/*)
    FLAKE_DIR="$SCRIPT_DIR"
    ;;
  *)
    echo "==> Non-home path detected: $SCRIPT_DIR"
    echo "==> Copying to local path: $LOCAL_DIR"
    rsync -a --delete "$SCRIPT_DIR/" "$LOCAL_DIR/"
    chmod +x "$LOCAL_DIR/bootstrap.sh"
    FLAKE_DIR="$LOCAL_DIR"
    ;;
esac

echo "==> Building nix-darwin configuration from $FLAKE_DIR..."

# Ensure flake dir is a git repo (Nix flakes require this)
if [ ! -d "$FLAKE_DIR/.git" ]; then
  echo "==> Initializing git repo in $FLAKE_DIR..."
  git -C "$FLAKE_DIR" init
  git -C "$FLAKE_DIR" add -A
fi

# Ensure any new files are tracked by git (Nix flakes ignores untracked files)
git -C "$FLAKE_DIR" add -A

# Build the system configuration
echo "==> Building configuration (this may take a while on first run)..."
SYSTEM_BUILD=$(nix build "$FLAKE_DIR#darwinConfigurations.Austins-MacBook-Air.system" --print-out-paths --no-link)

echo "==> Built: $SYSTEM_BUILD"

# Activate
echo "==> Activating configuration (requires root)..."
sudo "$SYSTEM_BUILD/activate"

echo ""
echo "==> Done! Your system is configured."
echo "    Run 'rebuild' in a new shell to apply future changes."
