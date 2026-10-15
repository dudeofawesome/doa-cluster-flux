# Shared model inference

KubeAI 0.24.0 provides the internal OpenAI-compatible base URL `http://kubeai.kubeai-system.svc.cluster.local/openai/v1`. Set the request's `model` to a registered catalog name.

## Hardware and lifecycle

Models have zero minimum replicas. The scale-down delay is approximately five minutes of idle retention. Active and queued requests contribute to demand.

Configure callers with a 30-second timeout and disable automatic retries when a bounded wait is required. KubeAI does not enforce this deadline. For streaming clients, check whether their timeout means total duration or inactivity between chunks. A cold start may exceed 30 seconds even with cached weights. A request for Qwen cannot run while Llama holds one GPU, and neither model preempts the other. Requests can time out; retry later after the occupied model becomes idle. Disconnecting cancels the held HTTP request, but model pods may remain pending or continue loading until autoscaling releases them.

## Persistent weights and budget

The explicitly managed `inference-models` PVC declares 128 GiB storage on the GPU node; model pods scale to zero without deleting weights.
