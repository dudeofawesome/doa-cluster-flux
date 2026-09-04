{ pkgs, ... }:
{
  name = "doa-cluster-flux";

  packages = with pkgs; [
    actionlint
    kustomize
    fluxcd
    kubectl
    kubectx
    mosquitto
    renovate
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

  env.KUBECONFIG =
    let
      kubeContextOverlay = pkgs.writeText "doa-cluster-flux-kubeconfig-overlay" ''
        apiVersion: v1
        kind: Config
        current-context: doa-admin
      '';
    in
    "${kubeContextOverlay}:${builtins.getEnv "HOME"}/.kube/config";
}
