#!/bin/bash
set -e

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

# 4. Set up the flake directory
FLAKE_DIR="$HOME/CODE_Mac_bootstrap"
mkdir -p "$FLAKE_DIR"/{hosts,modules,home}

# 5. Detect user and hostname
CURRENT_USER=$(whoami)
CURRENT_HOSTNAME=$(scutil --get LocalHostName 2>/dev/null || hostname -s)
echo "==> Configuring for user: $CURRENT_USER, hostname: $CURRENT_HOSTNAME"

# 6. Generate all nix files inline (guarantees integrity regardless of source)
cat > "$FLAKE_DIR/user.nix" << EOF
{
  username = "$CURRENT_USER";
  hostname = "$CURRENT_HOSTNAME";
}
EOF

cat > "$FLAKE_DIR/flake.nix" << 'NIXEOF'
{
  description = "macOS system configuration";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-unstable";

    nix-darwin = {
      url = "github:nix-darwin/nix-darwin";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    home-manager = {
      url = "github:nix-community/home-manager";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs = inputs@{ self, nixpkgs, nix-darwin, home-manager, ... }:
    let
      userConfig = import ./user.nix;
      username = userConfig.username;
      hostname = userConfig.hostname;
    in {
    darwinConfigurations.${hostname} = nix-darwin.lib.darwinSystem {
      system = "aarch64-darwin";
      specialArgs = { inherit username hostname; };
      modules = [
        ./hosts/macbook.nix
        home-manager.darwinModules.home-manager
        {
          home-manager.useGlobalPkgs = true;
          home-manager.useUserPackages = true;
          home-manager.users.${username} = import ./home;
        }
      ];
    };
  };
}
NIXEOF

cat > "$FLAKE_DIR/hosts/macbook.nix" << 'NIXEOF'
{ pkgs, username, hostname, ... }:

{
  imports = [
    ../modules/system.nix
    ../modules/packages.nix
    ../modules/homebrew.nix
    ../modules/shell.nix
  ];

  # Let Determinate manage Nix itself
  nix.enable = false;

  # Set your hostname
  networking.hostName = hostname;

  # The primary user (required for system.defaults, homebrew, etc.)
  system.primaryUser = username;

  # The user
  users.users.${username} = {
    name = username;
    home = "/Users/${username}";
  };

  # Used for backwards compatibility
  system.stateVersion = 5;

  # Allow unfree packages
  nixpkgs.config.allowUnfree = true;
}
NIXEOF

cat > "$FLAKE_DIR/modules/system.nix" << 'NIXEOF'
{ pkgs, ... }:

{
  # macOS system preferences
  system.defaults = {

    # Dock
    dock = {
      autohide = true;
      mru-spaces = false;
      minimize-to-application = true;
      show-recents = false;
    };

    # Finder
    finder = {
      AppleShowAllExtensions = true;
      FXEnableExtensionChangeWarning = false;
      FXPreferredViewStyle = "Nlsv";
      ShowPathbar = true;
      ShowStatusBar = true;
    };

    # Global
    NSGlobalDomain = {
      AppleShowAllExtensions = true;
      InitialKeyRepeat = 15;
      KeyRepeat = 2;
      NSAutomaticCapitalizationEnabled = false;
      NSAutomaticSpellingCorrectionEnabled = false;
    };

    # Trackpad
    trackpad = {
      Clicking = true;
      TrackpadRightClick = true;
    };
  };

  # Keyboard
  system.keyboard = {
    enableKeyMapping = true;
    remapCapsLockToEscape = false;
  };

  # Security
  security.pam.services.sudo_local.touchIdAuth = true;
}
NIXEOF

cat > "$FLAKE_DIR/modules/packages.nix" << 'NIXEOF'
{ pkgs, ... }:

{
  # CLI tools installed via Nix (preferred over Homebrew for CLI)
  environment.systemPackages = with pkgs; [
    # Core utilities
    coreutils
    curl
    wget

    # Development
    git
    gh
    lazygit
    delta

    # Search & navigation
    ripgrep
    fd
    fzf
    eza
    bat
    zoxide

    # System
    htop
    tree
    jq
    yq

    # Editors
    neovim
  ];
}
NIXEOF

cat > "$FLAKE_DIR/modules/homebrew.nix" << 'NIXEOF'
{ pkgs, ... }:

{
  homebrew = {
    enable = true;

    onActivation = {
      autoUpdate = true;
      cleanup = "zap";
      upgrade = true;
    };

    taps = [];

    brews = [
      "mas"
    ];

    casks = [
      # Browsers
      "firefox"
      "google-chrome"
      "brave-browser"

      # Development
      "visual-studio-code"
      "docker"
      "vscodium"
      "zed"
      "sublime-text"

      # Productivity
      "keepassxc"
      "notion"
      "windows-app"
      "utm"
      "ollama"

      # Utilities
      "rectangle"
      "aldente"
    ];

    masApps = {
      # "Xcode" = 497799835;
    };
  };
}
NIXEOF

cat > "$FLAKE_DIR/modules/shell.nix" << 'NIXEOF'
{ pkgs, ... }:

{
  programs.zsh.enable = true;
  environment.shells = [ pkgs.zsh ];
}
NIXEOF

cat > "$FLAKE_DIR/home/default.nix" << 'NIXEOF'
{ pkgs, lib, ... }:

{
  imports = [
    ./git.nix
    ./zsh.nix
  ];

  home.stateVersion = "24.05";

  # Ensure ~/.local/bin is on PATH (Claude Code installs here)
  home.sessionPath = [ "$HOME/.local/bin" ];

  # Install Claude Code (native installer) if not present
  home.activation.installClaudeCode = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
    if [ ! -x "$HOME/.local/bin/claude" ]; then
      echo "Installing Claude Code (native)..."
      PATH="/usr/bin:/bin:/usr/sbin:/sbin:$PATH" /usr/bin/curl -fsSL https://claude.ai/install.sh | PATH="/usr/bin:/bin:/usr/sbin:/sbin:$PATH" /bin/bash -s stable
    fi
  '';

  # Let home-manager manage itself
  programs.home-manager.enable = true;
}
NIXEOF

cat > "$FLAKE_DIR/home/git.nix" << 'NIXEOF'
{ pkgs, ... }:

{
  programs.git = {
    enable = true;
    userName = "Austin Hill";
    userEmail = "you@example.com";

    delta = {
      enable = true;
      options = {
        navigate = true;
        side-by-side = true;
      };
    };

    extraConfig = {
      init.defaultBranch = "main";
      push.autoSetupRemote = true;
      pull.rebase = true;
      merge.conflictstyle = "zdiff3";
    };

    aliases = {
      st = "status";
      co = "checkout";
      br = "branch";
      lg = "log --oneline --graph --decorate";
    };
  };
}
NIXEOF

cat > "$FLAKE_DIR/home/zsh.nix" << 'NIXEOF'
{ pkgs, ... }:

{
  programs.zsh = {
    enable = true;
    autosuggestion.enable = true;
    syntaxHighlighting.enable = true;

    shellAliases = {
      ls = "eza --icons";
      ll = "eza -la --icons";
      lt = "eza --tree --icons";
      cat = "bat";
      cd = "z";

      # Rebuild system config
      rebuild = "darwin-rebuild switch --flake ~/CODE_Mac_bootstrap";
    };

    initExtra = ''
      # Initialize zoxide
      eval "$(zoxide init zsh)"

      # Initialize fzf
      eval "$(fzf --zsh)"
    '';
  };

  programs.starship = {
    enable = true;
    enableZshIntegration = true;
  };
}
NIXEOF

echo "==> Building nix-darwin configuration from $FLAKE_DIR..."

# Ensure flake dir is a git repo (Nix flakes require this)
if [ ! -d "$FLAKE_DIR/.git" ]; then
  echo "==> Initializing git repo in $FLAKE_DIR..."
  git -C "$FLAKE_DIR" init
fi

# Ensure all files are tracked by git (Nix flakes ignores untracked files)
git -C "$FLAKE_DIR" add -A

# Build the system configuration
echo "==> Building configuration (this may take a while on first run)..."
SYSTEM_BUILD=$(nix build "$FLAKE_DIR#darwinConfigurations.$CURRENT_HOSTNAME.system" --print-out-paths --no-link)

echo "==> Built: $SYSTEM_BUILD"

# Activate
echo "==> Activating configuration (requires root)..."
sudo "$SYSTEM_BUILD/activate"

echo ""
echo "==> Done! Your system is configured."
echo "    Run 'rebuild' in a new shell to apply future changes."
