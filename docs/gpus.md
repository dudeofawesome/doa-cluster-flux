# GPUs

kings-canyon is the cluster's only GPU node. It has three cards, split between two Kubernetes resources:

| Card     | PCI address    | UUID                                       | Kubernetes resource | Used by                                     |
| -------- | -------------- | ------------------------------------------ | ------------------- | ------------------------------------------- |
| RTX 3060 | `0000:81:00.0` | `GPU-0e5f94ee-b735-84ad-6e2f-61ab731b442f` | `nvidia.com/gpu`    | KubeAI's `rtx3060` profile                  |
| RTX 3090 | `0000:82:00.0` | `GPU-6dda6c74-00cd-a40f-442e-e952e7c54db1` | `devic.es/rtx3090`  | shared: KubeAI's `rtx3090` profile and jobs |
| RTX 3060 | `0000:c2:00.0` | `GPU-8b0b486f-fe4e-78fc-597f-2eaa9ec0b7a3` | `nvidia.com/gpu`    | KubeAI's `rtx3060` profile                  |

Always refer to a card by its UUID. GPU indexes and `/dev/nvidiaN` numbers depend on probe order and can change when cards are added or moved; UUIDs belong to the card.

## How a pod gets a GPU

Getting a GPU takes two separate steps, and they don't automatically agree:

1. **Scheduling.** A device plugin advertises a count on the node, such as `nvidia.com/gpu: 2`. A pod that requests one is placed on that node and holds one unit until it exits. This is only bookkeeping; nothing is attached yet.
2. **Attachment.** When a container using the `nvidia` RuntimeClass starts, the NVIDIA container runtime reads `NVIDIA_VISIBLE_DEVICES` and attaches the GPUs it names.

Several things can set `NVIDIA_VISIBLE_DEVICES`, and the last one wins:

| Order | Source                          | Example                                                                  |
| ----- | ------------------------------- | ------------------------------------------------------------------------ |
| 1     | the container image             | CUDA images default to `all`                                             |
| 2     | the device plugin               | the UUIDs of the cards it allocated, added by kubelet at container start |
| 3     | the pod spec (`env`, `envFrom`) | whatever the pod sets                                                    |

So reserving a GPU and seeing one are different things. A pod that reserves one RTX 3060 but sets `NVIDIA_VISIBLE_DEVICES=all` sees all three cards, including the ones other pods hold. Pods that don't use the `nvidia` RuntimeClass run with runc, which attaches no GPUs at all.

The rest of this page is about keeping those two steps in agreement.

## The RTX 3060s: `nvidia.com/gpu`

The [NVIDIA device plugin](../infrastructure/controllers/nvidia-device-plugin/release.yaml) advertises the two RTX 3060s, and only them, as `nvidia.com/gpu: 2`.

-   **Only the 3060s.** The plugin advertises every GPU it can see. Its chart hardcodes `NVIDIA_VISIBLE_DEVICES=all` for the plugin's own container and has no value to change it, so a postRenderer patch replaces it with the two 3060 UUIDs.
-   **Allocations by UUID.** `deviceIDStrategy: uuid` makes the plugin hand containers UUIDs instead of indexes. Inside the plugin's container the two visible cards are numbered 0 and 1, but on the host index 1 is the RTX 3090, so passing indexes would give the 3090 to inference.
-   **Fails loudly.** If a 3060 is replaced, its UUID changes, the plugin can't find it and fails at startup (`failOnInitError: true`). It never silently advertises the wrong card.

A pod requesting `nvidia.com/gpu` gets both steps from the plugin: the scheduler reserves the cards and the plugin attaches the same cards. The pod must not set `NVIDIA_VISIBLE_DEVICES` itself, or it would replace that allocation.

## The RTX 3090: `devic.es/rtx3090`

The NVIDIA device plugin can't advertise different cards on one node under different resource names; chart 0.20.1 rejects a custom `resources` config. So the RTX 3090 is advertised by [generic-device-plugin](../infrastructure/controllers/generic-device-plugin/), which already handles the water meter's radio:

-   A [NodeFeatureRule](../infrastructure/config/nfd/rtx3090.yaml) labels any node with an RTX 3090 (PCI ID `10de:2204`) with `feature.node.kubernetes.io/rtx3090.present`, and generic-device-plugin runs on those nodes.
-   It advertises `devic.es/rtx3090: 1`, keyed by the card's sysfs path, `/sys/bus/pci/devices/0000:82:00.0`. The PCI address stays fixed as long as the card stays in its slot. If the card is removed or moved, the count drops to 0 and pods that want it stay Pending.
-   A pod holding the resource gets one read-only file, `/run/devic.es/rtx3090/uevent`, which shows the card's PCI identity. It gets no device nodes, because `/dev/nvidiaN` numbers follow probe order and could point at a 3060.

`devic.es/rtx3090` is therefore a **scheduling token**: it reserves the card but attaches nothing. Every container in a pod holding it sets `NVIDIA_VISIBLE_DEVICES` to the 3090's UUID, and the nvidia RuntimeClass attaches the card from that. The admission policies below enforce this.

## Admission policies

Two ValidatingAdmissionPolicies in [`infrastructure/config/gpu-admission`](../infrastructure/config/gpu-admission/) reject pods whose two steps would disagree:

| Policy                         | Applies to                                                        | Requires                                                                                                                                                          |
| ------------------------------ | ----------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `rtx3090-pinned`               | pods requesting `devic.es/rtx3090`, in every namespace            | the `nvidia` RuntimeClass; `NVIDIA_VISIBLE_DEVICES` set literally to the 3090's UUID in every container, including init and debug containers; no `nvidia.com/gpu` |
| `inference-device-plugin-gpus` | `nvidia` RuntimeClass pods in `inference` that don't use the 3090 | an `nvidia.com/gpu` request; no `NVIDIA_VISIBLE_DEVICES` and no `envFrom` in any container                                                                        |

Some details behind those rules:

-   `envFrom` is banned in `inference` GPU pods because the policy can't see inside a ConfigMap or Secret, and one could carry `NVIDIA_VISIBLE_DEVICES`. Pods holding the 3090 may use `envFrom`, because their explicit `env` entry takes precedence over it.
-   The device plugin's own value is added by kubelet after admission, so the policies never see it and never block it.
-   Both policies use `failurePolicy: Ignore`. `rtx3090-pinned` is evaluated for every pod in the cluster, and an evaluation error shouldn't block all of them. If a policy did fail to evaluate, the cost is limited to one pod on kings-canyon seeing more GPUs than it should. A namespace that needs a hard guarantee adds its own policy with `Fail`, as [`dungeon-scriber`](../apps/ai/dungeon-scriber/README.md) does.

What the policies don't cover:

-   Outside `inference`, a pod using the `nvidia` RuntimeClass without the 3090 token can still choose GPUs with `NVIDIA_VISIBLE_DEVICES`. [dcgm-exporter](../apps/monitoring/dcgm-exporter/release.yaml) relies on this, setting `all` to collect metrics from every card.
-   CDI annotations (`cdi.k8s.io/…`) are a second way to attach a device, and they aren't blocked cluster-wide.

## Using the RTX 3090

Any namespace can use the card. A pod that wants it:

-   requests `devic.es/rtx3090: '1'` under `resources.limits`, and doesn't also request `nvidia.com/gpu`;
-   sets `runtimeClassName: nvidia`;
-   sets `NVIDIA_VISIBLE_DEVICES=GPU-6dda6c74-00cd-a40f-442e-e952e7c54db1` in every container, init containers included;
-   sets `NVIDIA_DRIVER_CAPABILITIES=compute,utility`.

<!-- prettier-ignore -->
```yaml
spec:
  runtimeClassName: nvidia
  containers:
    - name: job
      image: docker.io/pytorch/pytorch@sha256:<digest>
      env:
        - name: NVIDIA_VISIBLE_DEVICES
          value: GPU-6dda6c74-00cd-a40f-442e-e952e7c54db1
        - name: NVIDIA_DRIVER_CAPABILITIES
          value: compute,utility
      resources:
        limits:
          devic.es/rtx3090: '1'
```

For KubeAI models, use the `rtx3090` profile; see the [inference README](../apps/ai/inference/README.md#gpus).

On the first run of a new workload, check that `nvidia-smi -L` inside the container lists only the RTX 3090.

### Sharing

The card's two main users are KubeAI's `rtx3090` models and [Dungeon Scriber's batch jobs](../apps/ai/dungeon-scriber/README.md). There is exactly one `devic.es/rtx3090`, so the card is first come first served. Whichever pod is scheduled first holds it until the pod exits. Every other pod that wants it stays Pending, and nothing preempts. A KubeAI model releases it after its idle scale-down delay (about five minutes); a batch job holds it until it finishes.

## Host prerequisite: UUID names in the CDI spec

kings-canyon's NVIDIA container toolkit runs in CDI mode. It turns each entry in `NVIDIA_VISIBLE_DEVICES` into a CDI device name, `nvidia.com/gpu=<entry>`, and looks it up in the node's generated CDI spec. kings-canyon's spec has named devices only by index (`0`, `1`, `2` and `all`), so without UUID names those values wouldn't resolve and GPU containers would fail to start.

kings-canyon's NixOS configuration ([`hosts/nixos/kings-canyon/k3s-gpu.nix`](https://github.com/dudeofawesome/nix-config/blob/main/hosts/nixos/kings-canyon/k3s-gpu.nix) in nix-config) adds UUID names to the spec ([nix-config#108](https://github.com/dudeofawesome/nix-config/pull/108)):

```nix
hardware.nvidia-container-toolkit.extraArgs = [ "--device-name-strategy" "uuid" ];
```

`nvidia-ctk cdi generate` writes each device once per naming strategy, so the index names stay as well. To check the host, run `nvidia-ctk cdi list` on kings-canyon and look for `nvidia.com/gpu=GPU-…` entries.

## The order Flux applies things

Flux's dependencies apply these pieces in this order:

1. `infrastructure-controllers`: the NVIDIA device plugin, which now advertises only the 3060s.
2. `infrastructure-operators`: KubeAI's `rtx3090` profile.
3. `infrastructure-config`: the NodeFeatureRule and the admission policies.
4. `infrastructure-generic-device-plugin`: the `devic.es/rtx3090` token.

The token appears only after the policies that guard it exist. Until then, `rtx3090` models just stay Pending.

## Replacing or moving a card

Run `nvidia-smi --query-gpu=name,pci.bus_id,uuid --format=csv` on kings-canyon to read the current UUIDs and PCI addresses. `git grep` for an old UUID finds every place it appears.

-   **Replacing a 3060:** put the new UUID in the patch in [`nvidia-device-plugin/release.yaml`](../infrastructure/controllers/nvidia-device-plugin/release.yaml) and in the table above. Until then, the device plugin fails at startup and inference has no 3060s.
-   **Replacing the 3090:** update the UUID in [`rtx3090.yaml`](../infrastructure/config/gpu-admission/rtx3090.yaml) (the variable and the message), in the policy tests and in the docs. Until then, pods pinned to the old UUID fail to start, because the CDI spec no longer lists it.
-   **Moving the 3090 to another slot:** update the sysfs path in [`generic-device-plugin/config.yaml`](../infrastructure/controllers/generic-device-plugin/config.yaml). Until then, the token count is 0 and 3090 pods stay Pending.

## Testing the admission policies

```sh
python3 infrastructure/config/gpu-admission/tests/run.py
```

This starts a throwaway local API server from the Kubernetes envtest binaries, applies the policies from this repository, and submits the test pods in [`tests/cases.yaml`](../infrastructure/config/gpu-admission/tests/cases.yaml), checking that each is allowed or denied as expected. It never connects to the cluster. The first run downloads about 100 MB of binaries into `~/.cache/doa-cluster-flux/envtest`.

To add a case, copy a pod in `cases.yaml` and set its `test.gpu-admission/expect` annotation to `allow` or to the name of the policy that must deny it; the file's header explains every annotation. [`dungeon-scriber`](../apps/ai/dungeon-scriber/tests/gpu-admission.yaml) keeps its own cases, which run in the same suite.

## Possible improvements

-   **Inject the UUID automatically.** A MutatingAdmissionPolicy could add `NVIDIA_VISIBLE_DEVICES` to every pod that requests `devic.es/rtx3090`. That would remove the per-pod setting and the KubeAI workaround, with the validating policy kept as a backstop. The cluster runs Kubernetes 1.35, where that API is off by default, so this needs a k3s feature gate on the host, or a Kubernetes release that turns it on.
-   **Dynamic Resource Allocation.** DRA is the proper long-term fit: a ResourceClaim selects a card by model or UUID and attaches exactly that card. It isn't usable yet: KubeAI 0.24's resource profiles can't express ResourceClaims, and the NVIDIA DRA driver can't share GPUs with the device plugin, so it would have to take over the 3060s too. Once KubeAI supports claims, both workloads can move to the NVIDIA DRA driver.
