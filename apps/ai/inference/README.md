# Shared model inference

KubeAI 0.24.0 provides the internal OpenAI-compatible base URL `http://kubeai.kubeai-system.svc.cluster.local/openai/v1`. Set the request's `model` to a registered catalog name.

## Hardware and lifecycle

Models have zero minimum replicas. The scale-down delay is approximately five minutes of idle retention. Active and queued requests contribute to demand.

Configure callers with a 30-second timeout and disable automatic retries when a bounded wait is required. KubeAI does not enforce this deadline. For streaming clients, check whether their timeout means total duration or inactivity between chunks. A cold start may exceed 30 seconds even with cached weights. A request for Qwen cannot run while Llama holds one GPU, and neither model preempts the other. Requests can time out; retry later after the occupied model becomes idle. Disconnecting cancels the held HTTP request, but model pods may remain pending or continue loading until autoscaling releases them.

## Persistent weights and budget

The explicitly managed `inference-models` PVC declares 128 GiB storage on the GPU node; model pods scale to zero without deleting weights.

## HyperQwen comparison

`qwen3.8-27b-uncensored-w4a16-hyperqwen` runs [HyperQwen](https://github.com/syv-ai/HyperQwen)'s patched vLLM on both RTX 3060s so it can be compared with the llama.cpp Qwen. The two compete for the same GPUs, so only one runs at a time. It uses a different abliterated checkpoint from the Heretic GGUF, so compare output quality as well as speed.

Prepare the weights once, after the Model is deployed:

```sh
kubectl apply -f apps/ai/inference/docs/prepare-hyperqwen-weights.yaml
kubectl wait -n inference --for=condition=complete --timeout=2h job/prepare-hyperqwen-weights
```

Start the benchmark client. It sends requests through KubeAI, so both Qwens are measured the same way and autoscaling sees the traffic:

```sh
kubectl apply -f apps/ai/inference/docs/benchmark-client.yaml
kubectl wait -n inference --for=condition=ready --timeout=30m pod/model-benchmark
```

Boot the model with one request, then read `Available KV cache memory` from the model pod's log and add `--kv-cache-memory=<bytes, slightly under that value>` to the Model before measuring. An unpinned pool changes size with the state of the compile cache.

```sh
kubectl exec -n inference model-benchmark -- curl -sS --max-time 1800 \
  http://kubeai.kubeai-system.svc.cluster.local/openai/v1/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"qwen3.8-27b-uncensored-w4a16-hyperqwen","prompt":"Hello","max_tokens":1}'
```

Run the benchmark against each model, one at a time, when nothing else is using the GPUs:

```sh
for model in qwen3.8-27b-uncensored-w4a16-hyperqwen qwen3.8-27b-heretic-iq4-xs-mtp; do
  kubectl exec -i -n inference model-benchmark -- bash -s "$model" \
    < apps/ai/inference/docs/benchmark.sh
done
kubectl delete -f apps/ai/inference/docs/benchmark-client.yaml
```

The second model can't load until the first scales down, about five minutes later, and the benchmark waits for it. For HyperQwen's tokens per step, run this in the model pod before and after a run. It prints drafts and accepted tokens, and the result is `1 + accepted delta / drafts delta`:

```sh
kubectl exec -n inference <model-pod> -- env VLLM_API=http://127.0.0.1:8000 python3 bench/harness.py spec
```
