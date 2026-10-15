# Inference API and key portal

New API fronts KubeAI with user-owned static API keys. The portal is `https://inference.orleans.io`; OpenAI-compatible clients use `https://inference.orleans.io/v1`. Admitted Kubernetes applications can use `http://new-api.new-api.svc.cluster.local:3000/v1` with the same bearer keys. New cluster-internal callers must be added to the network policy in Flux.

## Model Discovery

The sidecar discovers Model custom resources in `inference` using the selector in [gateway.json](gateway.json). Publish a model by adding `inference.orleans.io/expose: 'true'` to its `metadata.labels`.

## Administration and offboarding

New API administrators are managed separately from Keycloak admission. To administer or promote a normal account after deployment, use a localhost port-forward and sign into the private root account with the password from SOPS. The application may request root-password verification for sensitive operations. Run all Kubernetes commands inside devenv:

```sh
devenv shell --quiet -- kubectl --namespace new-api \
  port-forward service/new-api 3000:3000 --address 127.0.0.1
```

Open `http://127.0.0.1:3000`, sign in as `cluster-root`, and use Users to promote or disable the intended account. Keep root credentials out of client applications. For ordinary administration, promote a named Sequoia account rather than sharing the bootstrap root account.

**Offboarding is not automatically synchronized from Keycloak.** Removing the Keycloak group or disabling the Keycloak account blocks subsequent Sequoia logins, but existing New API keys and sessions must also be blocked. Disable the corresponding New API account, revoke its keys/sessions, and remove its Keycloak admission. Keycloak subjects bind the user identity, but no Keycloak admin credentials or background directory synchronizer are installed. This is a manual administrative requirement for this setup.

## Validation

The smoke test uses only disposable local Docker-compatible containers: the pinned New API image, PostgreSQL 17.6, and a mock OAuth/model server. It never uses kubeconfig, cluster resources, or deployment secrets. Containers and their network are removed even after a test failure. Run it with a local Docker-compatible engine available:

```sh
python -B apps/ai/new-api/smoke-test.py
```

It verifies PostgreSQL initialization, non-root/read-only startup, repeated configuration reconciliation without duplicate resources, dynamic catalog changes, unchanged catalog on discovery failure, disabling an empty catalog, recovery to a nonempty catalog, verified-group admission, rejection of missing-group/unverified users, multiple non-admin keys, free-model requests without credits, streaming, per-key model restrictions, key revocation, and user rate limiting. A mock identity provider does not replace checking the actual Keycloak callback and group mapper after authorized deployment.

Run the unit tests for session renewal, rate-limit backoff, discovery pagination, rotated-token reads, filtering, and partial/malformed snapshot rejection:

```sh
python -B -m unittest discover \
  --start-directory apps/ai/new-api --pattern 'test_*.py'
```
