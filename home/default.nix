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
