# inference

llama.cpp models served by KubeAI on `kings-canyon` (2x RTX 3060 12 GB today).

## v2 profiles (A/B)

Two tuned twins run alongside the originals, which stay unchanged as the baseline.
Hermes keeps its current default; pick a v2 model there to compare.

| Model                            | Baseline                     | Changes                                                                                      |
| -------------------------------- | ---------------------------- | -------------------------------------------------------------------------------------------- |
| `qwen3.6-35b-a3b-iq4-xs-v2`      | `qwen3.6-35b-a3b-iq4-xs`     | 4 slots, unified KV, 262144 ctx, bounded host caches, Qwen sampling defaults                 |
| `qwen3.8-27b-heretic-iq4-xs-mtp` | `qwen3.8-27b-heretic-q4-k-m` | IQ4_XS + embedded MTP head, MTP drafting, 2 slots, unified KV, 131072 ctx, sampling defaults |

-   **Slots:** `--parallel N` alone splits the context into N fixed slices; `--kv-unified` shares one
    pool so a single request can still use the full context. Batching raises total throughput but
    not N-fold, and each request decodes a little slower while others run; the win is that short
    requests stop queueing behind long ones. Concurrent long requests compete for the shared pool;
    idle slots are evicted to the host RAM cache first.
-   **Context:** Qwen3.6/3.8 keep KV in only 1 of every 4 layers, so long context is cheap.
-   **MTP:** drafts 2 tokens per step with the model's own MTP head; verification keeps output
    identical. The publisher reports +82% decode for IQ4_XS on large GPUs. MTP keeps 3 copies of each
    slot's recurrent state in VRAM, which is why this model runs 2 slots.

Only one 2-GPU model fits at a time, so switching between profiles waits for the other to scale
down (`scaleDownDelaySeconds`).

### VRAM estimates (per 12 GB card, ~11.6 GiB usable)

Per-layer tensor sizes from the GGUF headers; compute buffers are a guess. The last card also holds
the output layer (and, for the 27B, the MTP head and draft KV), hence the 27B's `6,5` split.

| GiB per card (GPU0 / GPU1) |        35B v2 |       27B MTP |
| -------------------------- | ------------: | ------------: |
| Tensor split               |         `1,1` |         `6,5` |
| Weights                    |     8.1 / 7.9 |     7.1 / 6.7 |
| KV (q8_0, incl. draft)     |     1.3 / 1.3 |     2.4 / 2.1 |
| Recurrent state            |   0.13 / 0.11 |     0.5 / 0.4 |
| Compute (est.)             |     0.7 / 0.9 |     0.6 / 1.1 |
| **Total**                  | ~10.3 / ~10.3 | ~10.6 / ~10.3 |

KV and compute buffers are allocated at load, so an overcommit fails at startup rather than
mid-conversation.

## Validation checklist

1. **Startup log** (`kubectl -n inference logs <pod>`):
    - `initializing, n_slots = 4, n_ctx_slot = 262144, kv_unified = 'true'` (27B: `2` / `131072`).
    - Sum `model buffer size`, `KV buffer size`, `RS buffer size` and `compute buffer size` per
      `CUDA0`/`CUDA1` and compare with the table above; adjust `--tensor-split` if one card is short.
    - 27B: no `failed to initialize speculative decoding context`.
2. **Headroom:** `DCGM_FI_DEV_FB_FREE` per GPU should stay above ~500 MiB under load.
3. **Benchmark** the same prompts against baseline and v2:
    - 1 client, then 4 (27B: 2) concurrent clients; short and long (32k+) prompts.
    - Read `timings.prompt_per_second` and `timings.predicted_per_second` from each response.
    - MTP: `timings.draft_n_accepted / timings.draft_n`, or the `draft acceptance = …` log line.
    - Queueing: `llamacpp:requests_deferred`; throughput: `rate(llamacpp:tokens_predicted_total[5m])`.
4. **Quality:** run a few real Hermes tool-calling tasks on both profiles.

## Rollback

-   **CrashLoop/OOM at startup:** lower `--ctx-size` (35B: `196608`, then `131072`; 27B: `98304`) and
    the matching `context_length` in `apps/home/hermes/config.yaml`. For the 27B,
    `--spec-draft-n-max 1` also frees VRAM.
-   **MTP slower or low acceptance:** drop the `--spec-*` args.
-   **Abandon a profile:** delete its manifest and its entries in `kustomization.yaml` and the Hermes
    config; the baseline models are untouched.
