---
name: node-maintenance
description: Take a cluster node out of service temporarily
---

Keep the node registered. Follow AGENTS.md: require explicit “deploy changes” before live mutations.

Before maintenance, inspect the node's pods, local storage, and disruption budgets. Confirm the maintenance affinity changes are deployed; only participating DaemonSets respect the label.

```bash
kubectl cordon NODE
kubectl label node NODE orleans.io/maintenance=true --overwrite
kubectl drain NODE --ignore-daemonsets --timeout=10m
```

Verify application pods moved and participating DaemonSets no longer target the node before taking it offline. Stop if draining fails; do not bypass disruption budgets, delete local data, or force-delete unreachable pods without separate authorization. An unreachable node may leave pods stuck terminating.

After maintenance, wait for the node to become Ready, then restore eligibility:

```bash
kubectl wait --for=condition=Ready node/NODE --timeout=5m
kubectl label node NODE orleans.io/maintenance-
kubectl uncordon NODE
```

Check DaemonSet readiness and Flux health. The maintenance label does not affect every DaemonSet or power off the host.
