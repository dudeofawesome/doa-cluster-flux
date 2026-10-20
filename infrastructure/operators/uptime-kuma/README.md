# Uptime Kuma operator

[Roxxas96/uptime-kuma-operator](https://github.com/Roxxas96/uptime-kuma-operator) reconciles opted-in Kubernetes resources into the existing Uptime Kuma instance. Flux installs the Helm chart from its OCI repository. Chart and image pins live in [release.yaml](release.yaml); the Kuma app and its MariaDB storage have their own lifecycle.

See [installation and verification](docs/install.md) for deployment, credential management and checks.

## Requirements and goals

- Keep the existing Kuma instance and data. Connect through its internal Service instead of installing a second instance or downgrading Kuma.
- Manage monitors through Git and Flux, using explicitly opted-in routing resources or custom monitor CRDs. Discovering a route alone must not create a monitor.
- Support custom monitors independently of ingress discovery, with a declared type, target, timing, success criteria and notification assignments.
- Monitor existing standard Ingress and Traefik IngressRoute hosts. Use annotations for supported discovery and explicit monitor resources for unsupported route types.
- Provide one aggregate Prometheus cluster-health monitor: only firing critical alerts make it unhealthy. Warnings do not. Missing or stale monitoring data must not report healthy.
- Provision that aggregate monitor through a CRD, including its JSON query, comparison operator and expected value. A manually configured monitor is an interim workaround rather than completion of this goal.
- Manage public status-page membership, notification-channel configuration and notification assignments through Git.
- Support the deployed Kuma v2 instance, including authentication, creation, updates, deletion, restarts, reconnects and correction of drift in operator-owned monitors.
- Preserve unrelated manually managed monitors and status pages. Monitor ownership must be explicit.
- Keep credentials encrypted with SOPS and out of Helm values, monitor definitions, logs and documentation. Use Secret `kuma-credentials` with keys `username` and `password`.
- Keep the operator in a dedicated namespace with pinned artifacts, resource limits, non-root execution, TLS validation for checked endpoints and explicit network access. No public operator ingress is needed.
- Install the operator and CRDs before dependent monitors without introducing Flux dependency cycles. Deploy changes through Git only, with explicit `deploy changes` authorization.

## Scope and configuration

The operator watches `uptime-kuma` and `grafana` through namespace-scoped Roles. `watchAll: false` controls namespace scope; `optInByDefault: false` separately requires explicit route opt-in. Add namespaces to `watchNamespaces` when opting in resources elsewhere. The chart grants Secret reads by name in watched namespaces for monitor authentication references; it does not need cluster-wide Secret access.

Grafana's standard Ingress uses `uptime-kuma.io/enabled: 'true'` and related monitoring annotations. Traefik IngressRoute discovery is not supported, so [the explicit monitors](../../../apps/monitoring/uptime-kuma/monitors/ingresses.yaml) use `uptime-kuma.io/v1alpha1`, kind `Monitor`, with type `HTTP`. Creating one of these CRs is itself opt-in; no enabled annotation is needed on a Monitor.

The [monitor collection](../../../apps/monitoring/uptime-kuma/monitors/kustomization.yaml) deploys the central Monitor definitions into `uptime-kuma`, within the operator's watch scope. They are intentionally excluded from the app Kustomizations: including them there would make the app builds require the operator's CRD before the apps needed by the operator can start.

The operator Flux Kustomization depends on `apps-monitoring`, which supplies the existing Kuma app and Prometheus Operator CRDs. The separate monitor Kustomization depends on the operator and remains suspended until the monitor batch is ready for activation. Keeping the operator outside the shared `infrastructure-operators` build avoids a dependency cycle through `apps-base`.

The chart provides HTTP readiness/liveness probes, non-root security settings, and a single-replica Recreate strategy. Its metrics Service and ServiceMonitor integrate with Prometheus. Network policies permit the operator's Kubernetes API and DNS access, its connection to Kuma, and Prometheus scraping.

## Monitor behavior

Explicit HTTP checks use a 60-second interval, 10-second timeout, two retries and TLS certificate validation. These timing values are implementation defaults, not confirmed user requirements. Checks use existing health endpoints where available. Other checks accept landing pages or SSO redirects without following them, which verifies the route/authentication boundary rather than authenticated application functionality. Scrutiny's collector API expects an unauthenticated 401 and has that same limited meaning.

Flux's webhook-only route is excluded because it has no stable public GET health endpoint. TCP passthrough and UDP routes need a separate monitoring design. The Renovate webhook and Home Assistant public-key paths share UI hosts and are not separate checks. An in-cluster Kuma instance cannot independently report a total cluster outage; external monitoring is a separate potential addition.

## Feature gaps and unresolved details

| Requirement | Support and remaining work |
| --- | --- |
| Explicit opt-in | Native opt-in annotations and custom Monitor CRs; namespace scope is configured separately |
| Aggregate cluster health | The [Prometheus metric and desired Kuma settings](../../../apps/monitoring/uptime-kuma/README.md) are defined, but the operator does not expose JSON-query monitors |
| Notification assignments | Monitor CRs can reference existing Kuma notification channels by name |
| Notification-channel provisioning | Not provided by this operator; requires an additional declarative mechanism |
| Public status pages and membership | Not provided by this operator; requires an additional declarative mechanism |
| Destination choices | The target status page and notification destinations still need to be specified |

Empty notification lists in the draft monitors are not completion of Git-managed notifications. Notification names must resolve to existing Kuma channels; an unknown name fails reconciliation. Status-page groups and parent group monitors are different concepts: assigning a monitor's `group` does not publish it on a public status page.

## Completion criteria

The operator must authenticate to the existing Kuma instance and reconcile its monitor lifecycle successfully. The selected opt-in policy must be enforced, intended routes must have appropriate checks, and unrelated monitors must be preserved. Public status-page and notification provisioning must match the agreed destinations. The aggregate check must handle healthy, critical-alert, missing-data and stale-data cases correctly. Successful static rendering alone does not establish runtime compatibility.
