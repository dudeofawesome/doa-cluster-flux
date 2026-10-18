# Shared model inference

KubeAI 0.24.0 provides the internal OpenAI-compatible base URL `http://kubeai.kubeai-system.svc.cluster.local/openai/v1`. Set the request's `model` to a registered catalog name.

## Hardware and lifecycle

Models have zero minimum replicas. The scale-down delay is approximately five minutes of idle retention. Active and queued requests contribute to demand.

Configure callers with a 30-second timeout and disable automatic retries when a bounded wait is required. KubeAI does not enforce this deadline. For streaming clients, check whether their timeout means total duration or inactivity between chunks. A cold start may exceed 30 seconds even with cached weights. A request for Qwen cannot run while Llama holds one GPU, and neither model preempts the other. Requests can time out; retry later after the occupied model becomes idle. Disconnecting cancels the held HTTP request, but model pods may remain pending or continue loading until autoscaling releases them.

## Shared RTX 3090

`nvidia.com/gpu` (the `rtx3060` profile) covers only the two RTX 3060s. The RTX 3090 is a single `devic.es/rtx3090` unit shared with Dungeon Scriber batch jobs ([GPU split](../dungeon-scriber/README.md#gpu-split)), first come first served. Whichever pod is scheduled first holds the card until it exits; the other stays Pending, and neither preempts. A model scales down after its idle delay, while a batch job holds the card until it finishes.

A model opts in with the `rtx3090` profile. KubeAI profiles cannot set environment variables, so the model must pin the card itself; otherwise the CUDA image's `NVIDIA_VISIBLE_DEVICES=all` would expose every GPU:

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

Admission policies in [gpu-admission](../../../infrastructure/config/gpu-admission/) reject `devic.es/rtx3090` pods without that value. In this namespace, they also reject nvidia-runtime pods that set `NVIDIA_VISIBLE_DEVICES` themselves instead of leaving it to the device plugin.

## Persistent weights and budget

The explicitly managed `inference-models` PVC declares 128 GiB storage on the GPU node; model pods scale to zero without deleting weights.
