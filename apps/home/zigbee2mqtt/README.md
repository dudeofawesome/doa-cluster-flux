## Updating Zigbee bridge firmware

### Nabu Casa SkyConnect / ZBT-1

1. Download the firmware blob.

    https://github.com/NabuCasa/silabs-firmware-builder/releases
    For the SkyConnect, you'll want something like `skyconnect_ncp-uart-hw_7.4.4.0.gbl`

    | `ncp`  | Zigbee, single protocol |
    | ------ | ----------------------- |
    | `uart` | Communication interface |
    | `hw`   | Hardware flow control   |

1. `nix shell nixpkgs#python312Packages.universal-silabs-flasher`
1. Stop any zigbee2mqtt processes running, which could be locking the serial port.
1. `sudo universal-silabs-flasher --device /dev/serial/by-id/usb-Nabu_Casa_SkyConnect_v1.0_065b344abf18ec11a1baeb9a47486eb0-if00-port0 probe`
1. Verify the detected `ApplicationType` is `EZSP`.
1. `sudo universal-silabs-flasher --device /dev/serial/by-id/usb-Nabu_Casa_SkyConnect_v1.0_065b344abf18ec11a1baeb9a47486eb0-if00-port0 flash --firmware skyconnect_ncp-uart-hw_7.4.4.0.gbl`
1. Re-run the probe, and verify that the `ApplicationType` is still `EZSP` and that the firmware version matches the blob you selected.
