{ pkgs, username, hostname, ... }:

{
  imports = [
    ../modules/system.nix
    ../modules/packages.nix
    ../modules/homebrew.nix
    ../modules/shell.nix
  ];

  # Nix settings
  nix.settings.experimental-features = [ "nix-command" "flakes" ];

  # Set your hostname
  networking.hostName = hostname;

  # The primary user (required for system.defaults, homebrew, etc.)
  system.primaryUser = username;

  # The user
  users.users.${username} = {
    name = username;
    home = "/Users/${username}";
  };

  # Used for backwards 