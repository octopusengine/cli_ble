# MicroPython BLE architecture in `esp_upy/inspirace`

This note describes the MicroPython BLE code bundled under
`esp_upy/inspirace`. It focuses on how the ESP becomes a BLE peripheral that a
phone or `cli_ble` can control over Nordic UART Service (NUS).

## Directory map

| Path | Purpose |
| --- | --- |
| `ble_led.py` | NUS peripheral example that maps Bluefruit Control Pad input to an LED. |
| `ble/ble_uart.py` | Small, direct `bluetooth.BLE` UART-style example. |
| `ble/test_ble_uart.py` | Application loop for the direct `BLEUART` example. |
| `ble/ble_advertising.py` | Helper for creating and decoding BLE advertising payloads. |
| `lib/blesync.py` | Low-level singleton wrapper around MicroPython's `bluetooth.BLE`. |
| `lib/blesync_server.py` | GATT server framework: services, characteristics, advertising, and connections. |
| `lib/blesync_client.py` | GATT client framework for an ESP acting as a BLE central. |
| `lib/blesync_uart/` | Nordic UART Service definitions for both server and client roles. |
| `utils/ble/bluefruit.py` | Bluefruit Connect Control Pad message constants. |

The imports in the examples assume that these modules have been copied to the
ESP filesystem with the same `lib/` and `utils/` layout. The MicroPython build
must include the `bluetooth` module and support BLE on the chosen board.

## The two implementation styles

### 1. `blesync` framework — used by `ble_led.py`

This is the higher-level style used by the project LED example. The application
declares a service class, registers a callback with a decorator, and calls
`Server.start()`.

```text
cli_ble or Bluefruit Connect
        │ GATT write to NUS RX
        ▼
MicroPython bluetooth.BLE IRQ
        ▼
blesync.py event dispatcher
        ▼
blesync_server.Service / Characteristic callback
        ▼
@UARTService.on_message application function
        ▼
LED action and optional GATT notification on NUS TX
```

### 2. Direct `bluetooth.BLE` — used by `ble/ble_uart.py`

`BLEUART` uses `bluetooth.BLE` directly. It registers the service and handles
`_IRQ_CENTRAL_CONNECT`, `_IRQ_CENTRAL_DISCONNECT`, and `_IRQ_GATTS_WRITE` in
its own `_irq()` method. `test_ble_uart.py` provides an `on_rx()` callback and
periodically calls `uart.send()`.

This is useful for learning the native MicroPython API. For the current project
and named `cli_ble` tools, the `blesync` style is more convenient because it
already models services, characteristics, callbacks, and notifications.

## Nordic UART Service

`lib/blesync_uart/server.py` defines NUS for an ESP peripheral:

| UUID | Server-side name | Properties | Direction |
| --- | --- | --- | --- |
| `6e400001-b5a3-f393-e0a9-e50e24dcca9e` | UART service | — | container service |
| `6e400003-b5a3-f393-e0a9-e50e24dcca9e` | `_tx` | read, notify | ESP → phone/CLI |
| `6e400002-b5a3-f393-e0a9-e50e24dcca9e` | `_rx` | write | phone/CLI → ESP |

The names are from the ESP peripheral's perspective. A desktop CLI therefore
writes to `nus-rx` and subscribes to `nus-tx`.

The server RX characteristic has a 100-byte configured buffer with
`buffer_append=True`. NUS does not define an application protocol or message
framing; an application should define explicit command boundaries if it needs
to handle long or rapidly repeated writes reliably.

## How `ble_led.py` starts a peripheral

The important application lines are conceptually:

```python
server = blesync_server.Server(device_name, blesync_uart.server.UARTService)
server.start()
```

`Server.start()` does the following:

1. Activates the singleton BLE radio through `blesync.activate()`.
2. Converts each service class into a MicroPython GATT declaration.
3. Calls `gatts_register_services()` and assigns returned value handles to the
   declared characteristics.
4. Registers callbacks for central connect, central disconnect, and GATT
   writes.
5. Starts connectable advertising with the configured device name.

On disconnect, `Server` starts advertising again. With the default
`multiple_connections=False`, it does not deliberately keep advertising while
a central is connected. Set `multiple_connections=True` only when the
application and radio hardware have been designed for multiple centrals.

### Important advertising detail

`blesync_server.Server` currently builds its advertising payload with a name
and appearance only. Although it registers the NUS service in GATT, it does
not pass the service UUID to `_create_advertising_payload()`.

As a result, `cli_ble -s --name octopus-led` can find the example by name, but
`cli_ble -s --service nus` is not guaranteed to find it. After connecting,
GATT discovery still correctly reports the NUS service and its characteristics.
To advertise NUS explicitly, the server implementation would need to include
the service UUID in its advertising payload.

## Message dispatch and notifications

`UARTService` exposes the RX write callback as `UARTService.on_message`:

```python
@blesync_uart.server.UARTService.on_message
def on_message(service, conn_handle, message):
    # message is raw bytes written by the central
    service.send(conn_handle, response_bytes)
```

When a central writes to RX, `blesync_server.Service._on_gatts_write()` reads
the characteristic value and invokes this callback. `service.send()` then
notifies the same connection through TX.

`blesync.py` owns one global `bluetooth.BLE()` object and maps native IRQ event
numbers to callback lists and result queues. It copies incoming byte buffers
before handing them to callbacks, which avoids retaining an IRQ-owned buffer.
Callbacks are still invoked by its IRQ dispatcher, so application callbacks
should remain short: change a pin, store a flag, or enqueue work rather than
performing long calculations or blocking I/O.

## Bluefruit Connect Control Pad

`utils/ble/bluefruit.py` names the byte sequences sent by the Bluefruit Connect
mobile app:

| Button | Bytes | `ble_led.py` behavior |
| --- | --- | --- |
| UP | `b'!B516'` | set LED on |
| DOWN | `b'!B615'` | set LED off |
| LEFT | `b'!B714'` | no action yet |
| RIGHT | `b'!B813'` | toggle LED |
| F1 | `b'!B11'` | no action yet |
| F2 | `b'!B219'` | no action yet |
| F3 | `b'!B318'` | no action yet |
| F4 | `b'!B417'` | no action yet |

`ble_led.py` compares the received raw bytes with these constants and echoes
the message back with `service.send()`. The host-side `devices.json` maps the
same values to named CLI tools such as `led-on`, `led-off`, and `led-toggle`.

## ESP as a BLE central

The same framework can make an ESP act as a client instead of a peripheral.
`blesync_client.py` can:

1. Scan and parse advertising data.
2. Connect with `gap_connect()`.
3. Discover GATT services, characteristics, and descriptors.
4. Dispatch notifications to matching service characteristics.

`lib/blesync_uart/client.py` is the client-side NUS definition. Here its
`send()` method writes to remote RX, while `on_message` is attached to remote
TX notifications. This direction reversal is expected: the remote peripheral
still owns the service's RX/TX naming.

## Security and the keyed LED example

The inspiration framework itself does not enable BLE pairing, encryption, or
authorization. `esp_upy/test_ble_key.py` adds an application-level gate:

1. A central first writes the configured key bytes.
2. The ESP records that connection handle as authenticated and sends `ok`.
3. Later commands from that connection are accepted.
4. Other commands receive `unauthorized` and do not change the LED.
5. Authentication state is removed on disconnect.

This is useful as a learning example, but it is not cryptographic protection:
the shared key is sent as plain BLE application data unless the BLE link is
also paired and encrypted.

## Practical debugging checklist

- Confirm the board runs the intended script, not an older `ble_led.py`.
- Use a unique advertised name, for example `octopus-led-<short-id>`.
- Scan by name if the NUS UUID is not in advertising data.
- Connect with `cli_ble -c ADDRESS` to inspect the actual GATT table.
- Use `--notify nus-tx` before a command when an application sends replies.
- Keep commands small and define framing before sending structured or long
  payloads.
- Re-advertising happens after disconnect; rescan if the peripheral uses a
  changing BLE address.
- For devices that report *Insufficient Authentication*, complete OS-level BLE
  pairing before accessing protected characteristics.

## Related host-side documentation

- [English CLI overview](../README.md)
- [Czech ESP32-C3 guide](../doc/cli_ble_esp_cz.md)
- [Device profile and tool format](../doc/devices.md)
