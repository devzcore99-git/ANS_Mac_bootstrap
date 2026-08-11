{ pkgs, ... }:

{
  # Enable zsh as default shell
  programs.zsh.enable = true;

  environment.shells = [ pkgs.zsh ];
}
