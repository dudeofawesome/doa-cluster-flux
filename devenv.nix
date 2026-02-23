{ pkgs, ... }:
{
  name = "doa-cluster-flux";

  packages = with pkgs; [
    actionlint
  ];

  languages = {
    python = {
      enable = true;
      version = "3.13";
      poetry = {
        enable = true;
        package = pkgs.unstable.poetry;
        install.enable = true;
        activate.enable = true;
      };
    };
  };
}
