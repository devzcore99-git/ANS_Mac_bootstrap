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
    taps = [];

    # Homebrew formulae (prefer nix packages above; use this for exceptions)
    brews = [
      "mas"
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

      # Communication
      # "slack"
      # "discord"

      # Utilities
      "rectangle"     # window management
      "aldente"
      # "alt-tab"
      # "the-unarchiver"
    ];

    # Mac App Store applications
    # Find IDs with: mas search <app name>
    masApps = {
      # "Xcode" = 497799835;
      # "1Password" = 1333542190;
      # "Magnet" = 441258766;
    };
  };
}
