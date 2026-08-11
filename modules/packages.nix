{ pkgs, ... }:

{
  # CLI tools installed via Nix (preferred over Homebrew for CLI)
  # Only tools actually in use on this machine are declared here.
  # curl and jq are omitted deliberately — macOS ships both in /usr/bin.
  environment.systemPackages = with pkgs; [
    # Development
    git
    gh

    # Search & navigation
    ripgrep
  ];
}
