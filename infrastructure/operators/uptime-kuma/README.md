# Uptime Kuma operator

Prepared integration for [Jasonrve/uptime-kuma-operator](https://github.com/Jasonrve/uptime-kuma-operator), chart/image version `0.2.0`. This uses its Helm distribution; the project does not provide an OLM bundle. The bundled Kuma subchart is disabled so it connects to the existing MariaDB-backed instance. There is no additional public ingress.

The dedicated Flux Kustomizations in [uptime-kuma.yaml](../../../clusters/doa-cluster/uptime-kuma.yaml) are deliberately suspended. This is a preparation, not a working or deployed v2 integration. The operator waits for `apps-monitoring`, and the separate monitor Kustomization waits for the operator and its CRDs. Keeping these outside `infrastructure-operators` avoids a dependency cycle through `apps-base`.

## Credentials

The SOPS-encrypted `secrets.yaml` is included in this directory's `kustomization.yaml`. It contains Secret `kuma-credentials` in namespace `uptime-kuma-operator`, with keys `username` and `password`. These are Kuma account credentials, not the MariaDB credentials or a metrics API key. The post-renderer overrides the chart's hard-coded `uptimekuma_password` key to use `password`. The current client cannot supply a 2FA token. [secrets.example.yaml](secrets.example.yaml) documents the structure and is not included in Kustomize.

Use `sops infrastructure/operators/uptime-kuma/secrets.yaml` to create/edit the file. Include the repository's required `WARNING_unencrypted` header with that exact command, and ensure the file is encrypted before adding it to Git. No placeholder password or generated replacement account is included. Changing the Secret requires restarting the operator through a Git change to its pod template, because the client reads environment variables at startup.

## Activation prerequisites

Source inspection of release commit `5b337541e22cbd84ef2a8a4cb51fa417c077bf74` found these issues:

- The bundled Kuma default is `1.23.13`; the installed instance is `2.5.6`. The typed client omits v2 fields including `conditions`. Validate basic monitor creation, updates, deletion and reconnects against a disposable Kuma 2.5.6 instance before connecting production credentials. Creation compatibility has not been verified.
- The Ingress controller unconditionally adds monitors on reconcile, even with `kuma_load_all_ingress: false` and no annotation. Its periodic sync applies the opt-in filter, which can create/remove unwanted monitors. Fix or verify this behavior before activation. Grafana is annotated with `app.uptimekuma/name: grafana`, so its annotation and resource names agree.
- GenericMonitor lookups and cleanup use `metadata.name`, while creation uses `spec.name`. The prepared resources keep these identical and globally unique. Avoid reusing those names in another namespace or manually tagging unrelated monitors with the operator's `⎈` tag.
- `GenericMonitor` does not support `expectedValue` or `jsonPathOperator`, so the aggregate cluster-health JSON monitor remains a manual Kuma configuration. Do not add those fields to the CRDs; the schema would prune them.

After resolving these issues, pin the verified image/chart and change both Flux Kustomizations to `suspend: false` in Git. Deployment still requires the repository's explicit `deploy changes` authorization.

## Runtime configuration

The Helm post-renderer supplies the username and password references from the credential Secret and adds resource limits, a non-root UID, a read-only root filesystem and writable `/tmp`. Kubernetes API credentials remain mounted because this is a controller. The image is a .NET console worker with no HTTP health endpoint, so no HTTP probes are fabricated. The Kuma ingress policy permits TCP/3001 only from matching operator pods in the dedicated namespace in addition to the existing Traefik ingress.

The upstream chart ignores its security-context values and nests its resource values under `env`; the post-renderer applies these directly instead. The chart version and image digest are pinned. Registry inspection confirmed the published image is Linux/amd64 only, so the pod is restricted to amd64 nodes and uses the image's existing app UID/GID 1654. Security settings and memory limits still need runtime verification in the disposable compatibility test.

## Monitor coverage

[ingresses.yaml](../../../apps/monitoring/uptime-kuma/monitors/ingresses.yaml) defines 23 explicit `GenericMonitor` HTTP checks for Traefik IngressRoute hosts. Grafana uses the upstream standard Ingress discovery, giving 24 intended monitors. Monitor resources are deliberately outside the app's Kustomization so initial app deployment does not require the operator CRDs.

Checks use HTTPS with certificate validation, a 60-second interval, a 10-second timeout and two retries. Existing health endpoints are used for New API, Trek and Dawarich; Keycloak uses its public OIDC discovery document, ntfy uses `/v1/health`, and InfluxDB uses `/health`. Other checks use the ingress landing page. The explicit checks accept 200–399 without following redirects, so an SSO redirect checks the route/auth boundary rather than the protected application's functionality. Scrutiny's collector API deliberately expects 401 without credentials; that only checks its authentication boundary. These URLs/status expectations have not been probed live.

Flux's webhook receiver is excluded because it has a secret generated webhook path, not a stable public GET health route. TCP passthrough and Valheim UDP routes are excluded from HTTP monitoring. The Renovate webhook and Home Assistant public-key paths share hosts with their UI routes and are not separate checks. Notification IDs and public status-page membership remain unmanaged; the CRDs use empty notification lists.

## Validation

Render the chart with the values in `release.yaml`, apply its post-renderer patches, and validate the monitor fields against the published GenericMonitor schema. Build `infrastructure/operators/uptime-kuma` and `apps/monitoring/uptime-kuma/monitors` with Kustomize. Flux's generated `sources`, `apps-monitoring`, and cluster-root builds must still discover the new Helm repository and dedicated Flux Kustomizations. No live reconciliation is part of these checks.
