#!/usr/bin/env bash
# Measure one model through KubeAI, from the docs/benchmark-client.yaml pod.
set -euo pipefail

model=$1
out=/tmp/bench/$model
mkdir -p "$out"

bench() {
  local name=$1
  shift
  # The Qwen 3.8 models share this tokenizer, so token counts are comparable.
  vllm bench serve \
    --base-url http://kubeai.kubeai-system.svc.cluster.local/openai \
    --endpoint /v1/completions \
    --model "$model" \
    --served-model-name "$model" \
    --tokenizer /models/qwen3.8-27b-uncensored-w4a16 \
    --ready-check-timeout-sec 1800 \
    "$@" >"$out/$name.log" 2>&1
  echo "== $name"
  grep -E 'Output token throughput|Total Token throughput|Mean TTFT|Mean TPOT|Failed requests' "$out/$name.log"
}

# The first traffic after a start includes JIT warmup and reads low.
bench warmup --dataset-name random --seed 1 --random-input-len 256 \
  --random-output-len 256 --num-prompts 16 --max-concurrency 8

for temperature in default 0; do
  args=()
  [[ $temperature == default ]] || args=(--temperature "$temperature")
  for concurrency in 1 4; do
    bench "generation-t$temperature-c$concurrency" \
      --dataset-name custom --dataset-path bench/prompts_real.jsonl \
      --custom-output-len 1024 --num-prompts 8 \
      --max-concurrency "$concurrency" "${args[@]}"
  done
done

# A distinct seed per length, so no request is a prefix-cache hit.
seed=100
for length in 4096 16384 65536 102400; do
  seed=$((seed + 1))
  bench "prompt-$length" --dataset-name random --seed "$seed" \
    --random-input-len "$length" --random-output-len 1 \
    --num-prompts 2 --max-concurrency 1
done
