# First login and administration

After deployment, sign in using the Sequoia button. Creating the first OIDC account does not make it an administrator. With authorization to perform runtime setup, open a Rails console and promote the intended account:

```bash
kubectl exec \
  --namespace dawarich --stdin --tty deployment/dawarich \
  --container web -- bin/rails console
```

```ruby
User.find_by!(email: 'YOUR_SEQUOIA_EMAIL').update!(admin: true)
```

The upstream seeds also create `demo@dawarich.app` as an administrator on an empty database. Password login is disabled by configuration. After confirming your own administrator access, remove the unused demo account through Dawarich administration. These runtime setup steps are not executed when preparing these manifests.

Tracking clients use each user's Dawarich API key. The ingress leaves API endpoints and OIDC callbacks accessible without forward authentication.
