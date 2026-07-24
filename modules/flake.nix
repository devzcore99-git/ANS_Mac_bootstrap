{
  description = "Austin's macOS system configuration";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-unstable";

    nix-darwin = {
      url = "github:nix-darwin/nix-darwin";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    home-manager = {
      url = "github:nix-community/home-manager";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs = inputs@{ self, nixpkgs, nix-darwin, home-manager, ... }:
    let
      userConfig = import ./user.nix;
      username = userConfig.username;
      hostname = userConfig.hostname;
    in {
    darwinConfigurations.${hostname} = nix-darwin.lib.darwinSystem {
      system = "aarch64-darwin";
      specialArgs = { inherit username hostname; };
      modules = [
        ./hosts/macbook.nix
        home-manager.darwinModules.home-manager
        {
          h