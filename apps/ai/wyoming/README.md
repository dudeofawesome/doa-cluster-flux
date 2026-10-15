# Wyoming

[Wyoming Piper](https://github.com/OHF-Voice/wyoming-piper/) provides text-to-speech and [Wyoming Faster Whisper](https://github.com/OHF-Voice/wyoming-faster-whisper/) provides speech-to-text for Home Assistant over the Wyoming TCP protocol.

| Function       | Service host                        | TCP port | Model               |
| -------------- | ----------------------------------- | -------- | ------------------- |
| Text-to-speech | `piper.wyoming.svc.cluster.local`   | 10200    | `en_US-lessac-high` |
| Speech-to-text | `whisper.wyoming.svc.cluster.local` | 10300    | `base.en`           |

## Home Assistant setup after deployment

1. Open **Settings → Devices & services → Add integration → Wyoming Protocol**.
2. Enter host `piper.wyoming.svc.cluster.local` and port `10200`.
3. Add another **Wyoming Protocol** integration with host `whisper.wyoming.svc.cluster.local` and port `10300`.
4. In the Assist voice assistant settings, select Piper for text-to-speech and choose `en_US-lessac-high`, and Whisper for speech-to-text.
5. Test a spoken command; if accuracy or latency is unsuitable, tune the Whisper model and resources after measuring actual usage.
