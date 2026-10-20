# Wyoming

[Wyoming Piper](https://github.com/OHF-Voice/wyoming-piper/) provides text-to-speech. [Wyoming Parakeet](https://github.com/albe873/wyoming-parakeet) provides streaming speech recognition using Parakeet Realtime EOU 120M on CPU; [Wyoming Faster Whisper](https://github.com/OHF-Voice/wyoming-faster-whisper/) remains available for comparison. These services use the Wyoming TCP protocol directly with Home Assistant.

| Function       | Service host                        | TCP port | Model               |
| -------------- | ----------------------------------- | -------- | ------------------- |
| Text-to-speech | `piper.wyoming.svc.cluster.local`   | 10200    | `en_US-lessac-high` |
| Streaming speech-to-text | `parakeet.wyoming.svc.cluster.local` | 10300 | `realtime_eou_120m-v1-f16` |
| Speech-to-text | `whisper.wyoming.svc.cluster.local` | 10300    | `base.en`           |

## Home Assistant setup after deployment

1. Open **Settings → Devices & services → Add integration → Wyoming Protocol**.
2. Enter host `piper.wyoming.svc.cluster.local` and port `10200`.
3. Add another **Wyoming Protocol** integration with host `parakeet.wyoming.svc.cluster.local` and port `10300`.
4. In **Settings → Voice assistants**, edit the assistant used by your microphone/satellite. Select the Wyoming Parakeet provider for speech-to-text and English as its language. Select Piper for text-to-speech and choose `en_US-lessac-high`.
5. The existing OpenAI Whisper Cloud integration can remain installed, but select the Wyoming provider in this assistant to use incremental audio processing. Other assistants can continue using the shared API.
6. Test several actual voice commands, including entity names, pauses, and background noise. Compare accuracy and time from the end of speech to the final transcript against Whisper using the same microphone. Select the old provider again to roll back.

## Piper performance

Piper's startup wrapper sizes ONNX Runtime's native thread pool from the container's cgroup v2 CPU quota (`/sys/fs/cgroup/cpu.max`) and process CPU affinity, using the smaller bound. Fractional CPU quotas round down, with a minimum of one thread; an unlimited or unavailable quota falls back to affinity. This automatically follows changes to the container's CPU limit at startup. The pinned Piper version does not expose an ONNX thread setting, and `OMP_NUM_THREADS` does not control the native thread pool in this image.

With the default pool on kings-canyon (48 visible CPUs), a short sentence took 20.7–25.8 seconds to synthesize; explicitly using two threads with worker spinning disabled took 0.94–0.97 seconds with the same `en_US-lessac-high` model. Synthesis blocks Piper's event loop, so long inference can also time out Describe/Info probes and produce `ConnectionResetError` when Piper eventually answers a disconnected client.
