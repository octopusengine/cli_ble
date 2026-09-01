# octopusLAB
# Simple BLE UART authentication example for ESP32 and MicroPython.

print("---> BLE - LED with key")

import blesync_server
import blesync_uart.server
import utils.ble.bluefruit as bf

from lib.octopus_lib import getUid
from time import sleep
from components.led import Led

KEY = 123
KEY_BYTES = str(KEY).encode()

uID5 = getUid(short=5)
led = Led(10)  # P8 L1

led.blink()
sleep(3)
led.blink()

_connections = []
_authenticated_connections = set()


@blesync_uart.server.UARTService.on_message
def on_message(service, conn_handle, message):
    if message == KEY_BYTES:
        _authenticated_connections.add(conn_handle)
        service.send(conn_handle, b"ok")
        return

    if conn_handle not in _authenticated_connections:
        service.send(conn_handle, b"unauthorized")
        return

    if message == b"hi":
        service.send(conn_handle, b"hello")
        return

    if message == bf.UP:
        led.value(1)
    if message == bf.DOWN:
        led.value(0)
    if message == bf.RIGHT:
        led.toggle()

    service.send(conn_handle, message)


@blesync_server.on_connect
def on_connect(conn_handle, addr_type, addr):
    _connections.append(conn_handle)
    print("@blesync_server.on_connect")


@blesync_server.on_disconnect
def on_disconnect(conn_handle, addr_type, addr):
    _connections.remove(conn_handle)
    if conn_handle in _authenticated_connections:
        _authenticated_connections.remove(conn_handle)
    if not _connections:
        print("@blesync_server.on_disconnect")


devName = "octopus-led-" + uID5
print("BLE ESP32 device name: " + devName)

server = blesync_server.Server(devName, blesync_uart.server.UARTService)
server.start()
