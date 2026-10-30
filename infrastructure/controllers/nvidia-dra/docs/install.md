# NVIDIA DRA installation

The standalone [DRA Driver for NVIDIA GPUs](https://github.com/kubernetes-sigs/dra-driver-nvidia-gpu) owns whole-GPU allocation. The host continues to own the NVIDIA kernel driver, Container Toolkit, and containerd. GPU Operator is unnecessary for that ownership model and its managed driver installation does not cover NixOS. ComputeDomains, MIG, MPS, and consumable sharing are disabled.

## Host prerequisite

Prepare and deploy `hosts/nixos/kings-canyon/k3s-gpu.nix` in the adjacent `nix-config` repository before deploying these Flux changes. Host deployment and cluster deployment require explicit authorization. On Kubernetes 1.35, KubeAI's device-class requests require `DRAExtendedResource=true` for the API server, scheduler, controller manager, and GPU-node kubelet. Enable it on every control-plane instance if additional servers are added.

The NixOS module extracts the host driver's pinned NVIDIA installer into a conventional driver tree, bind-mounts it at `/run/nvidia/dra-driver`, and advertises `feature.node.kubernetes.io/nvidia-dra.configured=true` through NFD. The bind mount lets the upstream driver find unpatched NVIDIA libraries and `nvidia-smi` without mounting the Nix store in GPU workloads. It must match the loaded kernel driver; reboot after changing NVIDIA driver versions.

Containerd must enable CDI and read `/var/run/cdi`, where DRA writes claim-specific specifications. The kubelet registration and plugin directories are `/var/lib/kubelet/plugins_registry` and `/var/lib/kubelet/plugins`. Model pods use the default container runtime with native CDI. The existing `nvidia` RuntimeClass remains available to monitoring exporters, which inspect all GPUs without reserving them.

CDI hooks execute on the host. The NixOS module exposes its Nix-packaged hook at `/etc/nvidia-dra/nvidia-cdi-hook`, and the HelmRelease sets `nvidiaCDIHookPath` to that path. Without this override, DRA copies a generic Linux hook from its image onto the host, where NixOS rejects it with `stub-ld` when a GPU container starts. Deploy the host hook before reconciling the HelmRelease change.

Before cluster deployment, check the host using its Nix-packaged `nvidia-smi` with the extracted NVML library. The extracted executable under `/run/nvidia/dra-driver/bin` is intended for the DRA container's standard Linux loader; running it directly on NixOS produces a `stub-ld` error. `LD_PRELOAD` selects a library but does not replace the executable's loader.

```sh
ssh kings-canyon 'sh -s' <<'SH'
findmnt /run/nvidia/dra-driver
env -i \
  LD_PRELOAD=/run/nvidia/dra-driver/lib64/libnvidia-ml.so.1 \
  /run/current-system/sw/bin/nvidia-smi --version
/etc/nvidia-dra/nvidia-cdi-hook --version
systemctl cat k3s
SH

kubectl get node kings-canyon \
  -o jsonpath='{.metadata.labels.feature\.node\.kubernetes\.io/nvidia-dra\.configured}{"\n"}'
```

## Allocation handoff

Quiesce GPU inference before the authorized rollout: let GPU model pods scale to zero and stop sending requests until validation completes. Existing device-plugin allocations must finish before DRA begins allocating the same physical GPUs.

The legacy device-plugin HelmRelease is deliberately retained with an unsatisfied `orleans.io/gpu-device-plugin: enabled` node selector. No node should carry that label during DRA operation. Retaining the inert release is necessary because `infrastructure-controllers` currently has `prune: false`; merely removing its manifest would leave the old plugin running. The DRA HelmRelease waits for the legacy release upgrade, and the KubeAI HelmRelease waits for DRA readiness.

The custom DeviceClasses distinguish `NVIDIA GeForce RTX 3060` from `NVIDIA GeForce RTX 3090`. KubeAI profiles `rtx3060` and `rtx3090` request them through `deviceclass.resource.kubernetes.io/<class-name>`. Existing models retain their `rtx3060:1` or `rtx3060:2` settings and now allocate only actual 3060 cards. Assign `rtx3090:1` explicitly to use the 24 GiB card. Each unit is an exclusive full GPU, not a memory share.

## Verify after authorized deployment

```sh
flux get helmrelease nvidia-device-plugin -n kube-system
flux get helmrelease nvidia-dra -n nvidia-dra
kubectl get daemonset -n kube-system nvidia-device-plugin
kubectl get pods -n nvidia-dra
kubectl get deviceclasses
kubectl get resourceslices -o yaml
```

The old device-plugin DaemonSet must have zero desired pods. The DRA plugin must run on `kings-canyon`, with ResourceSlices advertising two 12 GiB RTX 3060s and one 24 GiB RTX 3090. Confirm the exact `productName` attributes match the custom DeviceClass selectors.

The upstream documentation is inconsistent about GeForce support: its prerequisites specify data-center GPUs, while its allocation overview lists all NVIDIA GPUs. Treat successful allocation on these exact cards as a rollout requirement. The following optional smoke pods are outside Kustomize resources and allocate all three GPUs while running. Run them only during the authorized rollout, with inference idle:

```sh
kubectl apply -f infrastructure/controllers/nvidia-dra/docs/verify-gpus.yaml
kubectl wait -n inference --for=jsonpath='{.status.phase}'=Succeeded \
  --timeout=120s pod/dra-verify-3060 pod/dra-verify-3090
kubectl logs -n inference dra-verify-3060
kubectl logs -n inference dra-verify-3090
kubectl delete -f infrastructure/controllers/nvidia-dra/docs/verify-gpus.yaml
```

The first pod must print exactly two RTX 3060s; the second must print exactly one RTX 3090. Kubernetes automatically deletes these generated extended-resource claims once the pods finish, so an empty ResourceClaim list after successful completion is expected. To inspect an allocation, run `kubectl get resourceclaims -n inference -o yaml` while a GPU model pod is running.

Then request one existing GPU model through KubeAI and inspect its generated pod and claim to confirm allocation, library injection, model loading, and inference. Resume normal traffic only after that check succeeds. Check DCGM workload attribution as well as host GPU telemetry after the allocator change.

If a wait times out, inspect both pods with `kubectl describe pod -n inference dra-verify-3060` and `kubectl describe pod -n inference dra-verify-3090`. A pod in `Failed` phase cannot reach `Succeeded`. After correcting a startup failure, delete and recreate the smoke pods using the manifest above so they receive fresh claims and CDI specifications. Fixing the hook path does not restart pods whose `restartPolicy` is `Never`.

## Rollback

Quiesce inference and let all DRA GPU pods and claims terminate first. In Git, change the DRA kubelet-plugin node selector to an unsatisfied selector and reconcile that change so its DaemonSet stops. Confirm there are no DRA plugin pods or outstanding claims, then suspend the DRA HelmRelease in Git before restoring the legacy device-plugin selector and KubeAI's `nvidia.com/gpu` requests and `runtimeClassName: nvidia`. Remove KubeAI's dependency on the DRA release in that rollback. Suspending alone leaves deployed pods running. Apply the rollback through Git only after deployment is authorized.

The host driver tree and extended-resource feature gate can remain installed while rolling back the allocator. Do not run both allocators on the same GPUs.
