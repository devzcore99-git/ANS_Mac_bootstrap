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

  # Install graphify (PyPI package "graphifyy") if not present. There is no
  # Homebrew formula for it, so uv is declared in modules/homebrew.nix and the
  # tool is installed from PyPI here. Homebrew may not have run yet on a first
  # bootstrap; the install is skipped rather than failed, and the next `rebuild`
  # picks it up.
  home.activation.installGraphify = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
    if [ ! -x "$HOME/.local/bin/graphify" ]; then
      UV=""
      for candidate in /opt/homebrew/bin/uv /usr/local/bin/uv; do
        if [ -x "$candidate" ]; then UV="$candidate"; break; fi
      done
      if [ -n "$UV" ]; then
        echo "Installing graphify (uv tool install graphifyy)..."
        "$UV" tool install graphifyy
      else
        echo "uv not found; skipping graphify. Re-run 'rebuild' once Homebrew has installed uv."
      fi
    fi
  '';

  # Let home-manager manage itself
  programs.home-manager.enable = true;
}
