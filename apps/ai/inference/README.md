# Shared model inference

KubeAI 0.24.0 provides the internal OpenAI-compatible base URL `http://kubeai.kubeai-system.svc.cluster.local/openai/v1`. Set the request's `model` to a registered catalog name.

## Hardware and lifecycle

Models have zero minimum replicas. The scale-down delay is approximately five minutes of idle retention. Active and queued requests contribute to demand.

Configure callers with a 30-second timeout and disable automatic retries when a bounded wait is required. KubeAI does not enforce this deadline. For streaming clients, check whether their timeout means total duration or inactivity between chunks. A cold start may exceed 30 seconds even with cached weights. A request for Qwen cannot run while Llama holds one GPU, and neither model preempts the other. Requests can time out; retry later after the occupied model becomes idle. Disconnecting cancels the held HTTP request, but model pods may remain pending or continue loading until autoscaling releases them.

## GPUs

kings-canyon has two RTX 3060s and one RTX 3090. [docs/gpus.md](../../../docs/gpus.md) explains how they are split and why.

The `rtx3060` profile requests `nvidia.com/gpu`, which covers only the two RTX 3060s, so `rtx3060:2` always gets both of them. Models using this profile get their GPUs from the device plugin and must not set `NVIDIA_VISIBLE_DEVICES` or use `envFrom`. An admission policy rejects both, because either one could override the cards the device plugin allocated.

The RTX 3090 is a single `devic.es/rtx3090` unit, shared first come first served with other GPU jobs on the cluster, such as [Dungeon Scriber's](../dungeon-scriber/README.md). Whichever pod is scheduled first holds the card until it exits, and the other stays Pending; neither preempts. A model releases the card after its idle scale-down delay.

A model opts in with the `rtx3090` profile. KubeAI profiles cannot set environment variables, so the model pins the card itself. The `rtx3090-pinned` admission policy rejects a model without these variables, because the CUDA image's default `NVIDIA_VISIBLE_DEVICES=all` would expose every GPU:

<!-- prettier-ignore -->
```yaml
spec:
  resourceProfile: rtx3090:1
  maxReplicas: 1
  env:
    HOME: /tmp
    NVIDIA_VISIBLE_DEVICES: GPU-6dda6c74-00cd-a40f-442e-e952e7c54db1
    NVIDIA_DRIVER_CAPABILITIES: compute,utility
```

The 3090 has 24 GB of VRAM, the same total as `rtx3060:2`, but on one card, so a model moved to it doesn't need `--split-mode` or `--tensor-split`.

## Persistent weights and budget

The explicitly managed `inference-models` PVC declares 128 GiB storage on the GPU node; model pods scale to zero without deleting weights.
