{ pkgs, ... }:

{
  programs.git = {
    enable = true;
    userName = "Austin Hill";   # Change to your name
    userEmail = "you@example.com"; # Change to your email

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
