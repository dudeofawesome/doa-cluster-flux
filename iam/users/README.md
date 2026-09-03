# Adding users to the cluster

Human access uses the `kubernetes` client in the Keycloak `sequoia` realm.
The existing Keycloak `/Admins` group receives that client's
`kubernetes_admin` role. The role is emitted as
`kubernetes_roles: [kubernetes_admin]` and grants the Kubernetes `owner`
ClusterRole through `keycloak-admins.yaml`.

Install [kubelogin](https://github.com/int128/kubelogin), then add an exec-based
credential to an existing kubeconfig:

```sh
kubectl config set-credentials keycloak \
  --exec-api-version=client.authentication.k8s.io/v1 \
  --exec-interactive-mode=IfAvailable \
  --exec-command=kubectl \
  --exec-arg=oidc-login \
  --exec-arg=get-token \
  --exec-arg=--oidc-issuer-url=https://auth.orleans.io/realms/sequoia \
  --exec-arg=--oidc-client-id=kubernetes

kubectl config set-context --current --user=keycloak
kubectl auth whoami
```

After changing a user's client roles, run `kubectl oidc-login clean` to discard
cached tokens before testing the new access.

The control-plane API server must first be configured to trust that issuer and
map `preferred_username` to an `oidc:`-prefixed username and `kubernetes_roles`
to `oidc:kubernetes:`-prefixed groups.

## Break-glass certificate access

`add-user.fish` creates client-certificate credentials. Keep at least one
certificate-based owner credential available for recovery if Keycloak is down.
