# Configured device commands

`devices.json` turns a technical BLE GATT write into a named device tool. It
keeps Bluetooth UUIDs and the device-specific command format out of everyday
commands.

```powershell
python cli_ble.py devices
python cli_ble.py device test-led info
python cli_ble.py -d test-led
python cli_ble.py -d test-led led-on
python cli_ble.py device test-led run led-on
python cli_ble.py device test-led run led-off
python cli_ble.py device test-led run led-toggle
python cli_ble.py device test-led run esp-hi
python cli_ble.py --add octopus-led-48034
python cli_ble.py --add octopus-led-48034 test-led
python cli_ble.py --add F8:ED:34:67:47:E0 smartsolar
python cli_ble.py --delete test-led
```

`-d DEVICE` prints the matching `devices.json` entry, resolves the device,
connects without reading or writing values, and lists its GATT services,
characteristics, and descriptors. `-d DEVICE TOOL` and `device DEVICE run TOOL`
both scan for the configured
advertised-name prefix first. This
handles BLE devices that rotate their address. The configured `address` is used
only when a matching advertised name is not found.

The lookup duration is controlled by `--timeout`; for a nearby known ESP a
shorter value reduces normal tool startup time:

```powershell
python cli_ble.py -d test-led led-on --timeout 5
```

There is no direct-address-only mode yet. A future explicit switch may skip
the advertised-name scan and use the configured `address` immediately, but it
must remain opt-in because it will not handle rotating BLE addresses.

`--add MAC_OR_NAME [AS_NAME]` searches for one exact advertised name or MAC
address, connects only to inspect and print its GATT services, and adds the
name and current MAC address to `devices.json`. MAC-address matching ignores
letter case and accepts colons or hyphens as separators. `AS_NAME` is optional
and becomes the device ID in
the JSON configuration; otherwise the ID is derived from the advertised name.
It refuses to add an entry when its address or
advertised-name prefix is already configured. If a known profile service is
found, it assigns that profile; no write tool is created automatically.

`--delete DEVICE` prints the configured device ID and name, then removes the
entry only after the exact confirmation `yes`. A different response leaves
`devices.json` unchanged.

## Simple key authentication

An optional device `auth` object makes every `device … run …` connection send
the named value from `.env` before the tool message. The key is never printed
or written to the CLI log.

```json
"auth": {
  "environment": "KEY1"
}
```

For the included ESP example, `.env` contains `KEY1=123` and the board script
[`test_ble_key.py`](esp_upy/test_ble_key.py) contains `KEY = 123`. This is a
simple shared-key gate, not cryptographic protection: the value crosses BLE in
the clear unless the link itself is paired and encrypted.

## File format

`profiles` contains technical BLE transports which can be shared by multiple
devices. The built-in `nordic-uart` profile contains the Nordic UART Service
and its write/notify characteristics. These entries can use the GATT aliases
from `cli_ble.json`, so the built-in profile uses `nus`, `nus-rx`, and
`nus-tx` instead of duplicating their UUIDs. A device binds to one profile and
defines human-friendly tools.

```json
{
  "profiles": {
    "nordic-uart": {
      "service": "SERVICE_UUID",
      "write": "WRITE_CHARACTERISTIC_UUID",
      "notify": "NOTIFY_CHARACTERISTIC_UUID"
    }
  },
  "devices": {
    "device-id": {
      "name": "Visible device label",
      "match": {
        "advertised_name_prefix": "device-prefix-",
        "address": "AA:BB:CC:DD:EE:FF"
      },
      "profile": "nordic-uart",
      "auth": {
        "environment": "KEY1"
      },
      "tools": {
        "tool-id": {
          "text": "UTF-8 command sent to the profile write characteristic",
          "description": "Short tool description",
          "notify": true,
          "listen": 2
        }
      }
    }
  }
}
```

Each device must have a `name` and at least one of `advertised_name_prefix` or
`address`. A profile and tools are optional for a newly discovered device. Each
tool currently sends UTF-8 text.
Set `notify` to `true` to subscribe to the profile notify characteristic before
sending the tool message. `listen` is its optional positive duration in seconds.
