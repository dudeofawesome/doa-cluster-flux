{
  description = "Custom container images for the doa cluster";

  inputs = {
    nix-config.url = "github:dudeofawesome/nix-config";
    nixpkgs.follows = "nix-config/nixpkgs-linux-stable";
  };

  outputs =
    { nix-config, nixpkgs, ... }:
    let
      lib = nixpkgs.lib;
      linuxSystems = [
        "x86_64-linux"
        "aarch64-linux"
      ];
    in
    {
      packages = lib.genAttrs linuxSystems (
        system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
        in
        {
          avahi2dns-image = pkgs.callPackage ./images/avahi2dns/image.nix {
            avahi2dns = nix-config.packages.${system}.avahi2dns;
          };
        }
      );

      formatter = lib.genAttrs (
        linuxSystems
        ++ [
          "aarch64-darwin"
          "x86_64-darwin"
        ]
      ) (system: nixpkgs.legacyPackages.${system}.nixfmt);
    };
}
