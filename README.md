# cli_ble

`cli_ble` is a small cross-platform command-line tool for Bluetooth Low Energy
(BLE). It is built on [Bleak](https://github.com/hbldh/bleak) and supports
scanning, GATT inspection, characteristic reads/writes, notifications, and
friendly named commands for configured devices.

The project includes an ESP32-C3 / Nordic UART Service example that controls
an LED and supports a simple `hi` → `hello` exchange.

## Requirements and setup

- Python 3.10 or newer
- A working BLE adapter; Bluetooth enabled in the operating system
- On Linux, BlueZ must be running

Create a virtual environment and install dependencies:

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

On macOS or Linux, activate it with:

```bash
source venv/bin/activate
```

### Linux and BlueZ

Linux is supported through Bleak's BlueZ backend. Use BlueZ 5.55 or newer and
make sure that the Bluetooth service is running:

```bash
sudo apt install bluez python3-venv
sudo systemctl enable --now bluetooth
bluetoothctl --version
```

For a BLE peripheral that requires bonding, such as a MeshCore companion, pair
it in BlueZ before using protected characteristics:

```bash
bluetoothctl
power on
agent on
default-agent
scan on
pair AA:BB:CC:DD:EE:FF
trust AA:BB:CC:DD:EE:FF
```

Then use the normal CLI command, for example:

```bash
python cli_ble.py -c AA:BB:CC:DD:EE:FF --notify nus-tx --listen 60
```

`--pair` can also request pairing from the CLI. If a PIN is required, use a
longer timeout and ensure a BlueZ pairing agent is active.

## Basic BLE operations

```powershell
# Scan nearby devices
python cli_ble.py -s

# Filter a scan by advertised name
python cli_ble.py -s --name octopus-led

# Inspect GATT services, characteristics, and descriptors
python cli_ble.py -c AA:BB:CC:DD:EE:FF

# Read one characteristic
python cli_ble.py -c AA:BB:CC:DD:EE:FF --receive CHARACTERISTIC_UUID

# Read all characteristics advertised as readable, plus descriptor values
python cli_ble.py -c AA:BB:CC:DD:EE:FF --read-all-safe

# Write UTF-8 text or binary data
python cli_ble.py -c AA:BB:CC:DD:EE:FF --send CHARACTERISTIC_UUID "hello"
python cli_ble.py -c AA:BB:CC:DD:EE:FF --send CHARACTERISTIC_UUID "01 ff 7a" --hex

# Subscribe to notifications
python cli_ble.py -c AA:BB:CC:DD:EE:FF --notify CHARACTERISTIC_UUID --listen 30
```

`--read-all-safe` never writes or subscribes. It only reads characteristics
that advertise the `read` property, then attempts to read discovered
descriptors. A protected or unsupported read is reported for that individual
UUID or descriptor while the remaining inspection continues.

### GATT aliases

`cli_ble.json` defines optional aliases for common UUIDs. Full UUIDs always
remain valid; aliases are only a shorter equivalent for `--service`, `--send`,
`--receive`, and `--notify`.

```powershell
# Nordic UART Service, RX/write characteristic, and TX/notify characteristic
python cli_ble.py -s --service nus
python cli_ble.py -c AA:BB:CC:DD:EE:FF --send nus-rx "hello"
python cli_ble.py -c AA:BB:CC:DD:EE:FF --notify nus-tx --listen 30
```

Run `python cli_ble.py --examples` to print the current alias list.

Run `python cli_ble.py --help` or `python cli_ble.py --examples` for the full
command reference.

## Configured devices and tools

[`devices.json`](devices.json) maps device IDs to BLE profiles and named tools.
It keeps UUIDs and device-specific command frames out of everyday commands.

```powershell
# List configured devices
python cli_ble.py devices

# Inspect one device configuration
python cli_ble.py device test-led info

# Run a tool: short and long forms
python cli_ble.py -d test-led led-on
python cli_ble.py device test-led run led-on

python cli_ble.py -d test-led led-off
python cli_ble.py -d test-led led-toggle
python cli_ble.py -d test-led esp-hi
```

Configured devices are resolved by advertised-name prefix first, making them
resilient to changing BLE addresses. The configured MAC address is a fallback.

To discover a device and create a safe initial configuration entry:

```powershell
python cli_ble.py --add octopus-led-48034
python cli_ble.py --add octopus-led-48034 test-led
```

The optional second form saves the discovered device under `test-led` in
`devices.json`; without it, the CLI derives the device ID from the advertised
name. The command scans for the exact advertised name, prints GATT services, detects
known profiles, and avoids duplicate entries. It does not generate write tools
automatically.

To remove a configured device, use the explicit destructive command and type
`yes` at its confirmation prompt:

```powershell
python cli_ble.py --delete test-led
```

## ESP32-C3 example

Run [`esp_upy/test_ble_key.py`](esp_upy/test_ble_key.py) on the ESP32-C3. It
implements Nordic UART Service and recognizes Bluefruit Connect Control Pad
messages, including LED on/off/toggle. It can also require a simple shared key
before accepting commands.

Copy `.env.example` to `.env` and set the configured key:

```text
KEY1=replace-with-your-key
```

The corresponding ESP example currently uses `KEY = 123`. A named device tool
sends the configured environment value before its command, and does not print
or log the key value.

This shared-key check is not cryptographic protection. Use BLE pairing and
encryption, or a proper authentication protocol, when the device needs real
access control.

## Tests

```powershell
python -m unittest discover -s tests -v
```

## Documentation

- [Czech general CLI documentation](doc/cli_ble_cz.md)
- [Czech ESP32-C3 guide](doc/cli_ble_esp_cz.md)
- [MicroPython ESP BLE architecture](esp_upy/esp_upy.md)
- [Device profile and tool format](doc/devices.md)
