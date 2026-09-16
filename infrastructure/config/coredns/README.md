# LAN hostname resolution

K3s CoreDNS imports `coredns-custom` and forwards `.local` hostname queries to the `avahi2dns` Service at `10.43.0.54`. The existing Kubernetes plugin continues handling `cluster.local`, including nonexistent service names; public DNS uses the existing upstream forwarder. No application DNS policy changes are needed for pods using cluster DNS.

The bridge runs on `kings-canyon`, where Avahi resolution of LAN devices has been verified, and serves the whole cluster through its Service. It asks the host's existing Avahi daemon over its D-Bus socket. Avahi sends the multicast requests on the LAN. The bridge itself uses ordinary pod networking, runs as an unprivileged user, and does not expose a DNS port on the host. The node must have an active Avahi service and `/run/dbus/system_bus_socket`. If this node is unavailable, `.local` lookups fail; Kubernetes service and public DNS remain independent. Additional replicas on other nodes require verifying their Avahi and LAN access first.

This supports IPv4 hostname lookups (A records). AAAA queries return no data because LAN IPv6 link-local addresses cannot be used across the pod network. It does not proxy DNS-SD browsing, SRV/TXT discovery, or reverse DNS. Applications using their own DNS servers bypass this configuration.

`avahi2dns` 0.2.1 is built by `.github/workflows/build-images.yaml` from checksum-verified upstream binaries. CoreDNS accepts both TCP and UDP clients and uses UDP to reach the bridge. Avahi lookups are bounded to 1.5 seconds, below CoreDNS's default upstream read timeout. Readiness checks query the bridge's local SOA record and do not depend on any particular device being powered on.

## Rollout and verification

Publish the bridge image before deploying its Deployment. The existing Flux `infrastructure-config` dependency on `infrastructure-controllers` waits for the bridge before adding the CoreDNS forwarding configuration. K3s already mounts `coredns-custom`; CoreDNS reloads the import automatically after the ConfigMap volume updates.

Check that `10.43.0.54` is unused before first deployment. After Flux reconciles, verify bridge readiness, then query `gaggimate.local`, `kubernetes.default.svc.cluster.local`, a nonexistent name under `svc.cluster.local`, and a public hostname through cluster DNS. Test both UDP and TCP. Verify Home Assistant can open `ws://gaggimate.local:80/ws` and receive a status event without sending control messages.

To roll back, remove `mdns.override` from `coredns-custom` through Git and wait for CoreDNS to reload before removing the bridge. Kubernetes service and public DNS routing do not depend on the bridge.
