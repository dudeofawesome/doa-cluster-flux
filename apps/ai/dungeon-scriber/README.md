# Dungeon Scriber GPU jobs

Dungeon Scriber batch jobs (fine-tuning, transcription and evaluation) run in the `dungeon-scriber` namespace on the RTX 3090 in kings-canyon. The two RTX 3060s stay with KubeAI ([shared model inference](../inference/README.md)), which can also use the RTX 3090 through its opt-in `rtx3090` profile.

## GPU split

| GPU      | PCI address      | UUID                                       | Kubernetes resource | Used by |
| -------- | ---------------- | ------------------------------------------ | ------------------- | ------- |
| RTX 3060 | 00000000:81:00.0 | `GPU-0e5f94ee-b735-84ad-6e2f-61ab731b442f` | `nvidia.com/gpu`    | KubeAI  |
| RTX 3090 | 00000000:82:00.0 | `GPU-6dda6c74-00cd-a40f-442e-e952e7c54db1` | `devic.es/rtx3090`  | shared  |
| RTX 3060 | 00000000:C2:00.0 | `GPU-8b0b486f-fe4e-78fc-597f-2eaa9ec0b7a3` | `nvidia.com/gpu`    | KubeAI  |

The NVIDIA device plugin only sees the RTX 3060s. generic-device-plugin advertises a single `devic.es/rtx3090` on kings-canyon. It is a scheduling token and doesn't attach the GPU. The nvidia RuntimeClass attaches the card by UUID. UUIDs stay stable, while GPU indexes and `/dev/nvidiaN` numbers can change when cards are added or moved.

The RTX 3090 is first come first served between these jobs and KubeAI's `rtx3090` models. Whichever pod is scheduled first holds the single unit until it exits, and the other stays Pending; nothing preempts. An idle model releases it after its scale-down delay.

UUID selection needs the node's CDI specification to list UUID device names. kings-canyon's NixOS configuration (`dudeofawesome/nix-config`, `hosts/nixos/kings-canyon/k3s-gpu.nix`) must generate them:

```nix
hardware.nvidia-container-toolkit.extraArgs = [ "--device-name-strategy" "uuid" ];
```

`nvidia-ctk cdi generate` writes every device once per strategy, so the existing index names stay ([dudeofawesome/nix-config#108](https://github.com/dudeofawesome/nix-config/pull/108)).

## Job contract

A GPU pod in this namespace must:

-   request `devic.es/rtx3090: '1'` under `resources.limits`;
-   set `runtimeClassName: nvidia`;
-   set `NVIDIA_VISIBLE_DEVICES` to `GPU-6dda6c74-00cd-a40f-442e-e952e7c54db1` in every container, init containers included, because CUDA images default it to `all`;
-   set `NVIDIA_DRIVER_CAPABILITIES` to `compute,utility`;
-   use the `jobs` ServiceAccount, which mounts no API token;
-   meet the restricted Pod Security Standard: non-root, `RuntimeDefault` seccomp, no privilege escalation and all capabilities dropped.

The `dungeon-scriber-rtx3090` ValidatingAdmissionPolicy enforces the GPU rules here, on top of the cluster-wide `rtx3090-pinned` policy in [gpu-admission](../../../infrastructure/config/gpu-admission/). It rejects:

-   pods that use the nvidia RuntimeClass without the request;
-   pods that use the nvidia RuntimeClass with any other `NVIDIA_VISIBLE_DEVICES` value;
-   pods with any other RuntimeClass or with `cdi.k8s.io/` annotations.

The ResourceQuota allows one `devic.es/rtx3090` and no `nvidia.com/gpu`.

<!-- prettier-ignore -->
```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: lora-example
  namespace: dungeon-scriber
spec:
  backoffLimit: 0
  ttlSecondsAfterFinished: 86400
  template:
    spec:
      serviceAccountName: jobs
      runtimeClassName: nvidia
      restartPolicy: Never
      securityContext:
        runAsNonRoot: true
        runAsUser: 1000
        runAsGroup: 1000
        fsGroup: 1000
        fsGroupChangePolicy: OnRootMismatch
        seccompProfile:
          type: RuntimeDefault
      containers:
        - name: train
          # A public base image pinned by digest; code and venv live on the PVC.
          image: docker.io/vllm/vllm-openai@sha256:<digest>
          command: [/work/venv/bin/python, /work/src/train.py]
          env:
            - name: NVIDIA_VISIBLE_DEVICES
              value: GPU-6dda6c74-00cd-a40f-442e-e952e7c54db1
            - name: NVIDIA_DRIVER_CAPABILITIES
              value: compute,utility
            - name: HOME
              value: /work/home
            - name: HF_HOME
              value: /models/huggingface
          securityContext:
            allowPrivilegeEscalation: false
            capabilities:
              drop: [ALL]
          resources:
            requests:
              cpu: '8'
              memory: 24Gi
            limits:
              cpu: '16'
              memory: 32Gi
              devic.es/rtx3090: '1'
          volumeMounts:
            - name: models
              mountPath: /models
            - name: work
              mountPath: /work
            - name: shm
              mountPath: /dev/shm
      volumes:
        - name: models
          persistentVolumeClaim:
            claimName: models
        - name: work
          persistentVolumeClaim:
            claimName: work
        # PyTorch DataLoader workers share tensors through /dev/shm.
        - name: shm
          emptyDir:
            medium: Memory
            sizeLimit: 8Gi
```

Inside the container, `/run/devic.es/rtx3090/uevent` is a read-only view of the card's PCI identity (`PCI_ID=10DE:2204`, `PCI_SLOT_NAME=0000:82:00.0`). On the first run, check that `nvidia-smi -L` lists only the RTX 3090.

## Resources and storage

The ResourceQuota fits one LoRA job on a 9B bf16 model: 8 CPUs requested with a 16 CPU limit, 24 GiB of requested memory with a 32 GiB limit, 32 GiB of requested ephemeral storage with a 64 GiB limit, 8 pods and 4 PVCs totalling 256 GiB. The LimitRange gives containers that don't set resources 250m CPU and 512 MiB requests and 2 CPU and 4 GiB limits, so real jobs should set their own resources.

The `models` (100 GiB) and `work` (150 GiB) PVCs use `local-path` on kings-canyon. They are provisioned when Flux creates them. Their sizes are budgets, not reservations: local-path neither reserves nor enforces them. Pruning is disabled for the PVCs and the namespace, so deleting them is a manual step.

## Network

Nothing can connect to pods in this namespace. Pods can reach CoreDNS and TCP 443 on public addresses, which covers Hugging Face and its CDN. They can't reach cluster services, the Kubernetes API, the tailnet or private ranges. The node pulls images, so this policy doesn't affect image pulls.

## Images

Jobs use public base images pinned by digest. The job's code and a pinned virtual environment live on the `work` PVC, so no image pull secret is needed. Containers run as UID 1000 with `HOME` on a PVC or under `/tmp`.
