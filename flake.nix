# `nix develop --no-pure-eval`
{
  inputs = {
    nixpkgs.url = "github:cachix/devenv-nixpkgs/rolling";
    nixpkgs-unstable.url = "github:NixOS/nixpkgs/nixpkgs-unstable";
    nixpkgs-stable.url = "github:NixOS/nixpkgs/nixos-24.11";

    systems.url = "github:nix-systems/default";
    devenv = {
      url = "github:cachix/devenv/v1.3.1";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    nixpkgs-python = {
      url = "github:cachix/nixpkgs-python";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  nixConfig = {
    extra-substituters = [
      "https://devenv.cachix.org"
    ];
    extra-trusted-public-keys = [
      "devenv.cachix.org-1:w1cLUi8dv3hnoSPGAuibQv+f9TZLr6cv/Hm9XgU50cw="
    ];
  };

  outputs =
    {
      self,
      nixpkgs,
      nixpkgs-stable,
      devenv,
      systems,
      ...
    }@inputs:
    let
      forEachSystem = nixpkgs.lib.genAttrs (import systems);
    in
    {
      overlay = final: prev: {
        stable = import inputs.nixpkgs-stable {
          system = final.system;
          config.allowUnfree = true;
        };
        unstable = import inputs.nixpkgs-unstable {
          system = final.system;
          config.allowUnfree = true;
        };
      };
    }
    // {
      packages = forEachSystem (system: {
        devenv-up = self.devShells.${system}.default.config.procfileScript;
      });

      devShells = forEachSystem (
        system:
        let
          pkgs = import nixpkgs {
            inherit system;

            overlays = [
              self.overlay
            ];
          };

          rosettaPkgs = if pkgs.stdenv.isDarwin && pkgs.stdenv.isAarch64 then pkgs.pkgsx86_64Darwin else pkgs;
        in
        {
          default = devenv.lib.mkShell {
            inherit inputs pkgs;
            modules = [ ./devenv.nix ];
          };
        }
      );

      formatter = forEachSystem (
        system: (import inputs.nixpkgs-unstable { inherit system; }).nixfmt-rfc-style
      );
    };
}
