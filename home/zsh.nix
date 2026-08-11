{ pkgs, hostname, flakeDir, ... }:

let
  # Build-time fallback only. Empty string = "not configured", which the
  # rebuild function below treats as an error rather than a path.
  configuredFlakeDir = if flakeDir == null then "" else flakeDir;
in
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
    };

    initExtra = ''
      # Initialize zoxide
      eval "$(zoxide init zsh)"

      # Initialize fzf
      eval "$(fzf --zsh)"

      # Rebuild the system configuration.
      #
      # The clone can live anywhere — including an external volume — so the
      # flake path is resolved when rebuild is called, not baked in at build
      # time. In order:
      #   1. $FLAKE_DIR, if set
      #   2. the nearest ancestor of $PWD holding both flake.nix and user.nix
      #   3. flakeDir from user.nix, if it was set
      # Extra arguments are passed through to darwin-rebuild.
      rebuild() {
        local dir="''${FLAKE_DIR:-}"

        if [[ -z "$dir" ]]; then
          local d="$PWD"
          # Both files, so an unrelated project's flake.nix is not mistaken
          # for this configuration.
          while [[ "$d" != "/" ]]; do
            if [[ -f "$d/flake.nix" && -f "$d/user.nix" ]]; then
              dir="$d"
              break
            fi
            d="''${d:h}"
          done
        fi

        if [[ -z "$dir" ]]; then
          dir="${configuredFlakeDir}"
        fi

        if [[ -z "$dir" ]]; then
          print -u2 "rebuild: could not locate the configuration flake."
          print -u2 "  cd into the clone, or set FLAKE_DIR, or set flakeDir in user.nix."
          return 1
        fi

        if [[ ! -f "$dir/flake.nix" ]]; then
          print -u2 "rebuild: no flake.nix in $dir"
          return 1
        fi

        # Select by hostname explicitly: darwin-rebuild otherwise defaults to
        # the live hostname, which need not match the one in user.nix.
        darwin-rebuild switch --flake "$dir#${hostname}" "$@"
      }
    '';
  };

  programs.starship = {
    enable = true;
    enableZshIntegration = true;
  };
}
