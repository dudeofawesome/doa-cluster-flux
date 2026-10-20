# Installation and verification

## Credentials

Edit the existing encrypted Secret with:

```sh
sops infrastructure/operators/uptime-kuma/secrets.yaml
```

Keep its required `WARNING_unencrypted` header. Secret `kuma-credentials` belongs to namespace `uptime-kuma-operator`, with keys `username` and `password` for the existing Kuma account. The operator also supports optional `totpSecret` and `sessionToken` keys; do not use a metrics API key as a login credential.

Credentials are read from environment variables at startup. After changing the encrypted Secret, update a pod annotation under `spec.values.podAnnotations` in `release.yaml` through Git to restart the operator and pick up the change.

## Flux deployment

The chart source is the OCI HelmRepository in `sources/uptime-kuma-operator.yaml`. The operator Flux Kustomization in `clusters/doa-cluster/uptime-kuma.yaml` supplies its namespace, encrypted credentials and HelmRelease. Its dependency on `apps-monitoring` ensures Kuma and the Prometheus Operator CRDs are available first. The chart installs the Monitor CRD, and Flux's HelmRelease CRD policy permits schema updates during upgrades.

The operator Kustomization permits reconciliation. The separate `uptime-kuma-monitors` Kustomization remains suspended. Once the explicit monitor batch is ready, remove its `suspend: true` in Git. Grafana's annotation is in its app manifests and is independent of that monitor-batch suspension.

## Adding an explicit monitor

Add the Monitor to `apps/monitoring/uptime-kuma/monitors/ingresses.yaml`. The adjacent Kustomization deploys it into `uptime-kuma`. Keep these resources out of the monitored apps' Kustomizations: the separate collection preserves CRD/controller ordering and avoids a bootstrap cycle. Keeping Monitor CRs in `uptime-kuma` also avoids widening the operator's watch namespaces and Secret-read permissions for each monitored app.

Preparing these files does not deploy them. Deployment requires explicit `deploy changes` authorization, and deployed resource changes must go through Git.

## Local validation

```sh
devenv shell --quiet -- kustomize build infrastructure/operators/uptime-kuma
devenv shell --quiet -- kustomize build apps/monitoring/uptime-kuma/monitors
devenv shell --quiet -- kustomize build apps/monitoring/grafana
```

The operator build contains SOPS ciphertext; do not decrypt or print real credentials during validation. Render the pinned chart with the HelmRelease values and validate Monitor resources against the CRD bundled with that release. Use Flux dry-run builds for `sources`, `apps-monitoring`, and the dedicated operator and monitor Kustomizations to check effective discovery and dependency layout.

## Runtime verification

After authorized deployment, inspect the Flux Kustomization and HelmRelease conditions, pod readiness and operator logs. Confirm successful Kuma authentication. The image serves `/healthz` and `/readyz` on port 8081 and metrics on port 8080; the chart supplies the probes. The metrics ServiceMonitor uses `release: monitoring` to match this cluster's Prometheus selection.

Before enabling the full monitor batch, verify an opted-in monitor is created, updated, restored after drift and deleted with its source. Confirm an unannotated routing resource does not create a monitor and an unrelated manually managed Kuma monitor remains unchanged. Inspect `Monitor.status.conditions` and `Monitor.status.monitorID` for explicit CRs.

Verify ingress URLs and status expectations from Kuma's network environment, especially SSO boundaries and authenticated endpoints. TLS validation must remain enabled. Public status pages, channel provisioning and the JSON aggregate check are separate feature gaps documented in the README; ordinary HTTP-monitor verification does not complete them.
