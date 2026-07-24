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
    delta  # git diff viewer

    # Search & navigation
    ripgrep
    fd
    fzf
    eza    # modern ls
    bat    # modern cat
    zoxide # smart cd

    # System
    htop
    tree
    jq
    yq

    # Editors
    neovim
  ];
}
