---
name: setup-cluster-app
description: Set up new applications / deployment and their integrations. Use for adding an app or operator and completing initial setup.
---

# Set up a cluster app

Produce reviewable GitOps configuration, validate it, and document any first-login or external setup that cannot be represented in Git.

## Establish the application contract

Identify the exact upstream project. Ask about consequential unresolved choices: public hostname, admitted users. Do not close a question by ending the turn or silently choosing its answer.

Verify image architecture, health endpoints, writable paths, supported configuration mechanisms, and authentication behavior.

Pin a container tag version rather than using latest or main if possible.

## Choose ownership and layout

- Evaluate available Kubernetes operators before choosing Helm or a raw Deployment. Compare the actual catalog bundle/version and its capabilities with the alternative.
- Put new operators in dedicated namespaces under the current `infrastructure/operators/` pattern. Keep app resources in their own namespace under the appropriate `apps/<group>/<app>/` directory. Keep components with independent lifecycles independent; reuse existing shared services where appropriate.
- Inspect `clusters/doa-cluster/apps.yaml`, `infrastructure.yaml`, and relevant source/catalog configuration. Flux can generate a root Kustomization when one is absent. Do not add a group-level `kustomization.yaml` merely to register an app: that can replace automatic discovery and omit siblings. Build the effective Flux group to verify discovery.
- Establish CRD/controller/webhook readiness before dependent resources. Add shared `dependsOn` changes only for a demonstrated dependency and explain their effect on the whole group. Do not casually update a catalog pin shared by other operators.
- Use the appropriate app-local files for namespace, workload/instance/release, config, storage/database, service/ingress, identity, and encrypted secrets. Pin supported versions/digests using repository conventions and preserve Renovate annotations, including operator channel matchers. Fix a broken matcher instead of deleting it.

## Connect access and identity

Prefer native Keycloak OIDC when supported. Use the display name `Sequoia` when an app exposes a configurable provider label.

Distinguish who can log in from who becomes an administrator.

Apply route restrictions only when required by the intended access policy and verified against the app's endpoints; preserve OIDC callbacks, refresh, and legitimate API access.

## Protect runtime state

Prefer PostgreSQL databases where available.

Inspect the image entrypoint before selecting UID/GID and filesystem restrictions. Preserve init, working directory, required arguments, and initialization behavior when bypassing a root-only wrapper. Use suitable non-root execution, dropped capabilities, no privilege escalation, seccomp, and disabled service-account mounting when compatible. Add appropriate resource requests/limits and startup/readiness/liveness probes based on real endpoints and startup behavior.

Keep operator-owned configuration declarative. Disable supported self-updaters or self-reconfiguration that would bypass pinned Git state when appropriate.

## DRY

Check for existing cluster operators and architecture when creating supporting services (like databases). Postgres, for example, should use the CloudNativePG operator.

## App configuration

App configuration should prefer native config files (rather than env vars) where there are no practical downsides.

Make app config files separate files, with jsonschema headers where possible.

Pushing changes to the config (env var, or file-based) should trigger the deployment to pickup the changes (either via pod recreation or app-native file watcher).

## Validate and hand off

Preparing an app does not authorize deployment. Follow the repository's explicit `deploy changes` requirement before modifying cluster state; deployed resource updates must go through Git.
