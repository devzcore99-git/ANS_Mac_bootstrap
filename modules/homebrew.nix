{ pkgs, ... }:

{
  # Homebrew — used for GUI apps (casks) and Mac App Store (mas)
  # Nix handles CLI tools; Homebrew handles what it does best.
  homebrew = {
    enable = true;

    onActivation = {
      autoUpdate = true;
      cleanup = "zap"; # remove anything not declared here
      upgrade = true;
    };

    # Homebrew taps
    taps = [
      "anomalyco/tap" # provides opencode
    ];

    # Homebrew formulae (prefer nix packages above; use this for exceptions)
    # NOTE: cleanup = "zap" uninstalls any formula NOT listed here, so every
    # brew-installed formula must be declared or it gets removed on activation.
    brews = [
      "mas"

      "anomalyco/tap/opencode"
      "audacious"
      "btop"
      "docker"          # CLI only; Docker Desktop cask ships its own in /usr/local/bin
      "nmap"
      "nvtop"
      "python-tk@3.14"
      "rsync"           # newer than macOS's bundled openrsync

      # gh deliberately NOT here — packages.nix declares it as a Nix package.
      # ripgrep likewise; it arrives as an opencode dependency.
    ];

    # GUI applications
    casks = [
      # Browsers
      "firefox"
      "google-chrome"
      "brave-browser"

      # Development
      "visual-studio-code"
      #"iterm2"
      "docker-desktop"
      "vscodium"
      "zed"
      "sublime-text"
      "gitkraken"

      # AI / ML
      "claude"
      "lm-studio"
      "comfy"
      "ollama-app"

      # Productivity
      "keepassxc"
      "notion"
      "utm"

      # Communication
      # "slack"
      # "discord"

      # Utilities
      "rectangle"     # window management
      "aldente"
      "little-snitch" # network filter — system extension, re-approval needed if zapped
      "rsyncui"
      # "alt-tab"
      # "the-unarchiver"
    ];

    # Mac App Store applications
    # Find IDs with: mas search <app name>
    # NOTE: mas cannot sign in on macOS 10.15+ (Apple removed the private API).
    # A fresh machine must be signed into the App Store GUI first or these no-op.
    masApps = {
      "Windows App" = 1295203466;
      "GarageBand" = 682658836;
      "iMovie" = 408981434;

      # Pages / Numbers / Keynote omitted — preinstalled on a new Mac.
      # Note: they are NOT restored by an erase-and-reinstall of macOS;
      # in that case grab them free from the App Store by hand.

      # "Xcode" = 497799835;
    };
  };
}
