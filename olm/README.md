## Updating OLM

Review every release between the currently vendored version and the target,
including any breaking changes and changes to the official installation method.
Then regenerate from an explicit stable release tag:

```bash
./update.sh v1.10.0
```

Validate the rendered Flux manifests and review the generated diff before
committing the update. Do not use an unpinned `latest` release.

The local Kustomization replaces the controllers' exact-value control-plane
node selector with an `Exists` node-affinity expression. This preserves the
upstream control-plane placement while supporting distributions such as K3s
that assign a non-empty value to the control-plane label.
