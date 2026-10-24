# Dungeon Scriber GPU jobs

Dungeon Scriber's batch jobs (LoRA fine-tuning, transcription and evaluation) run in the `dungeon-scriber` namespace, on kings-canyon's RTX 3090. The two RTX 3060s belong to KubeAI.

The RTX 3090 is shared, first come first served, with KubeAI models that use the `rtx3090` profile. Whichever pod is scheduled first holds the card until it exits, and the other waits in Pending; nothing preempts. An idle model releases the card after about five minutes. A job holds it until the job finishes, so long jobs delay models that want the 3090.

## Running a job

A GPU pod in this namespace must:

-   request `devic.es/rtx3090: '1'` under `resources.limits`;
-   set `runtimeClassName: nvidia`;
-   set `NVIDIA_VISIBLE_DEVICES` to `GPU-6dda6c74-00cd-a40f-442e-e952e7c54db1` in every container, init containers included, because CUDA images default it to `all`;
-   set `NVIDIA_DRIVER_CAPABILITIES` to `compute,utility`;
-   use the `jobs` ServiceAccount, which mounts no API token;
-   meet the restricted Pod Security Standard: non-root, `RuntimeDefault` seccomp, no privilege escalation and all capabilities dropped;
-   set its own CPU and memory, because the defaults are sized for small helper containers.

This example fits the namespace's quota:

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

On the first run, check that `nvidia-smi -L` inside the container lists only the RTX 3090. `/run/devic.es/rtx3090/uevent` in the container is a read-only view of the card's PCI identity (`PCI_ID=10DE:2204`, `PCI_SLOT_NAME=0000:82:00.0`).

If the pod stays Pending, something else holds the card. `kubectl get pods -A --field-selector spec.nodeName=kings-canyon` shows what is running there, typically an `rtx3090` model in `inference`.

## What the namespace enforces

| Guard                            | What it does                                                                                                                                                                                                    |
| -------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Pod Security (`restricted`)      | Rejects pods that run as root, escalate privileges, keep capabilities or skip seccomp.                                                                                                                          |
| `dungeon-scriber-rtx3090` policy | Requires the nvidia RuntimeClass exactly when a pod requests `devic.es/rtx3090`, and the 3090's UUID in every container's `NVIDIA_VISIBLE_DEVICES`. Rejects other RuntimeClasses and `cdi.k8s.io/` annotations. |
| ResourceQuota `batch-jobs`       | Allows one `devic.es/rtx3090` and no `nvidia.com/gpu`, and caps CPU, memory, storage, pods and claims (below).                                                                                                  |
| LimitRange `defaults`            | Gives containers that don't set resources 250m CPU, 512 MiB and 1 GiB of ephemeral storage as requests, and 2 CPU, 4 GiB and 8 GiB as limits. Caps any container at 16 CPU and 32 GiB.                          |
| NetworkPolicy `jobs`             | Blocks all incoming connections and allows outgoing DNS and public HTTPS only (below).                                                                                                                          |
| ServiceAccount `jobs`            | Mounts no API token; jobs don't talk to the Kubernetes API.                                                                                                                                                     |

The cluster-wide [`rtx3090-pinned`](../../../infrastructure/config/gpu-admission/rtx3090.yaml) policy checks the same UUID pin everywhere, but it fails open (`failurePolicy: Ignore`) so that an evaluation error can't block every pod in the cluster. `dungeon-scriber-rtx3090` repeats the check with `failurePolicy: Fail`, so a job here never starts with access to the RTX 3060s, even if a policy can't be evaluated.

## Resources and storage

The ResourceQuota fits one LoRA job on a 9B bf16 model and leaves kings-canyon room for inference and the control plane:

| Resource          | Requests | Limits |
| ----------------- | -------- | ------ |
| CPU               | 8        | 16     |
| Memory            | 24 GiB   | 32 GiB |
| Ephemeral storage | 32 GiB   | 64 GiB |

It also allows 8 pods and 4 PVCs declaring 256 GiB in total.

Two PVCs on `local-path`, both on kings-canyon:

-   `models` (100 GiB): base models and adapters, for example as the Hugging Face cache.
-   `work` (150 GiB): datasets, code, the job's virtual environment, checkpoints and outputs.

They are provisioned as soon as Flux creates them, on kings-canyon (`volume.kubernetes.io/selected-node`), so Flux doesn't wait for a first consumer. Their sizes are budgets, not reservations: local-path neither reserves nor enforces them, and both share kings-canyon's disk. Together they use 250 GiB of the 256 GiB quota, so another claim must be small or the budget raised.

Flux never prunes the namespace or the PVCs. Removing them, or reverting this directory, leaves the data in place; deleting it is a manual step.

## Network

Nothing can connect to pods in this namespace. Pods can reach CoreDNS and TCP 443 on public addresses, which covers Hugging Face and its CDN. They can't reach cluster services, the Kubernetes API, the tailnet or private ranges. The node pulls images, so the policy doesn't affect image pulls.

## Images

Jobs use public base images pinned by digest. The job's code and a pinned virtual environment live on the `work` PVC, so no image pull secret is needed. Containers run as UID 1000 with `HOME` on a PVC or under `/tmp`.

## Testing

The GPU admission tests include this namespace's policy and Pod Security settings. [`tests/gpu-admission.yaml`](tests/gpu-admission.yaml) holds its cases, including the example Job above:

```sh
python3 infrastructure/config/gpu-admission/tests/run.py
```
