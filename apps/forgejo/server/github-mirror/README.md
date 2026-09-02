# Gitea Mirror

[`gitea-mirror`](https://github.com/RayLabsHQ/gitea-mirror) automatically
creates and updates Forgejo pull mirrors for repositories owned by the GitHub
account `dudeofawesome`.

The application is intentionally internal-only. It has a ClusterIP Service but
no Ingress, so its administrative dashboard is not reachable from the internet.

## Mirroring behavior

The deployment is configured to:

- discover repositories and synchronize mirrors hourly;
- mirror owned public and private repositories into the Forgejo user
  `dudeofawesome`;
- include forks, archived repositories, and Git LFS objects;
- preserve each repository's public or private visibility;
- exclude collaborator-owned, organization-owned, and starred repositories;
- archive orphaned mirrors instead of deleting their data; and
- mirror Git data only, without importing issues, pull requests, releases, or
  wikis.

Configuration is declared in `deployment.yaml`. On its first startup,
`gitea-mirror` writes those environment-derived defaults to its SQLite database.
Changes made later in the dashboard persist in the database and can override
the initial environment defaults. Prefer changing `deployment.yaml` before the
first deployment; after deployment, review the dashboard when changing existing
settings.

## Open the dashboard

Forward the internal Service to the local machine:

```sh
kubectl -n forgejo port-forward service/gitea-mirror 4321:4321
```

Then open <http://localhost:4321>. Stop the command with `Ctrl-C` when finished.
The first dashboard account registered becomes its administrator. Dashboard
accounts are separate from Forgejo accounts.

## Credentials

The SOPS-encrypted `secrets.yaml` contains:

- `github_token`: a GitHub fine-grained token with access to all selected
  repositories and read-only Contents and Metadata permissions;
- `gitea_token`: a Forgejo token belonging to `dudeofawesome` with
  `write:repository` and `read:user` scopes;
- `better_auth_secret`: the dashboard session-signing secret; and
- `encryption_secret`: the key used to encrypt tokens in the SQLite database.

Edit credentials only through SOPS:

```sh
sops apps/forgejo/server/github-mirror/secrets.yaml
```

After rotating any value, increment the `secrets.revision` pod-template
annotation in `deployment.yaml`. The resulting GitOps rollout makes the pod read
the updated Secret. Existing Forgejo pull mirrors can retain the token stored
when they were created. If private mirrors begin failing after GitHub token
rotation, update their mirror authorization in Forgejo or recreate those mirrors
through the dashboard.

Do not rotate or remove `encryption_secret` without also planning to re-enter
the stored API credentials. The existing SQLite data cannot decrypt them with a
different key.

## Observe and troubleshoot

Use read-only commands to inspect the workload:

```sh
kubectl -n forgejo get deployment,pods,pvc -l app=forgejo
kubectl -n forgejo logs deployment/gitea-mirror
kubectl -n forgejo describe deployment/gitea-mirror
```

The health endpoint is available while the port-forward is running:

```sh
curl --fail http://localhost:4321/api/health
```

Common failures include:

- `401` or `403` from GitHub: the GitHub token expired, was revoked, or does not
  cover every selected private repository;
- `401` or `403` from Forgejo: the Forgejo token is invalid or lacks the required
  scopes;
- destination-user errors: sign in to Forgejo as `dudeofawesome` once so the
  OIDC-backed user exists;
- mirror interval errors: keep `GITEA_MIRROR_INTERVAL` at or above Forgejo's
  configured minimum; and
- PVC permission errors: the upstream image and pod security context use UID and
  GID `1001`.

All deployment changes must be committed and reconciled by Flux. Do not edit the
Deployment or Secret directly in the cluster.
