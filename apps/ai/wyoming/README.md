# Wyoming

[Wyoming Piper](https://github.com/OHF-Voice/wyoming-piper/) provides text-to-speech for Home Assistant over the Wyoming TCP protocol.

## Home Assistant setup after deployment

1. Open **Settings → Devices & services → Add integration → Wyoming Protocol**.
2. Enter host `wyoming.wyoming.svc.cluster.local` and port `10200`.
3. In the Assist voice assistant settings, select Piper for text-to-speech and choose `en_US-lessac-high`.
4. Generate a short test announcement and check response latency before using it for routine announcements.
