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
