{ pkgs, ... }:
{
  name = "doa-cluster-flux";

  packages = with pkgs; [
    actionlint
    kustomize
    fluxcd
    kubectl
  ];

  languages = {
    python = {
      enable = true;
      version = "3.13";
      poetry = {
        enable = true;
        package = pkgs.poetry;
        install.enable = true;
        activate.enable = true;
      };
    };
  };
}
