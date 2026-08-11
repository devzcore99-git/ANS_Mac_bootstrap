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
      # Optional; null means the `rebuild` helper resolves the path at runtime.
      # `or null` keeps clones whose user.nix predates the field evaluating.
      flakeDir = userConfig.flakeDir or null;
    in {
    darwinConfigurations.${hostname} = nix-darwin.lib.darwinSystem {
      system = "aarch64-darwin";
      specialArgs = { inherit username hostname; };
      modules = [
        ./hosts/macbook.nix
        home-manager.darwinModules.home-manager
        {
          home-manager.useGlobalPkgs = true;
          home-manager.useUserPackages = true;
          # specialArgs does not reach home-manager modules; extraSpecialArgs does.
          home-manager.extraSpecialArgs = { inherit username hostname flakeDir; };
          home-manager.users.${username} = import ./home;
        }
      ];
    };
  };
}
