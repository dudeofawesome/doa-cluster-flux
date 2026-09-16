{
  lib,
  dockerTools,
  avahi2dns,
  bind,
}:

dockerTools.buildLayeredImage {
  name = "ghcr.io/dudeofawesome/avahi2dns";
  tag = avahi2dns.version;

  contents = [
    avahi2dns
    bind.dnsutils
  ];

  config = {
    Entrypoint = [ (lib.getExe avahi2dns) ];
    User = "65534:65534";
    Env = [ "PATH=/bin" ];
  };
}
