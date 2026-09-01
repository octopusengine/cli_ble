"""Tests for the presentation-free configured device-tool service."""

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from lib import device_runner
from lib.wrapp_ble import BleDevice


def test_config() -> dict[str, object]:
    return {
        "profiles": {
            "nordic-uart": {
                "service": "nus",
                "write": "nus-rx",
                "notify": "nus-tx",
            }
        },
        "devices": {
            "test-led": {
                "name": "ESP32-C3 Test LED",
                "match": {
                    "advertised_name_prefix": "octopus-led-",
                    "address": "48:31:B7:33:D0:36",
                },
                "profile": "nordic-uart",
                "auth": {"environment": "KEY1"},
                "tools": {
                    "esp-hi": {
                        "text": "hi",
                        "description": "Send a greeting and wait for hello",
                        "notify": True,
                        "listen": 0.001,
                    }
                },
            }
        },
    }


ALIASES = {
    "nus": "6e400001-b5a3-f393-e0a9-e50e24dcca9e",
    "nus-rx": "6e400002-b5a3-f393-e0a9-e50e24dcca9e",
    "nus-tx": "6e400003-b5a3-f393-e0a9-e50e24dcca9e",
}


class FakeConnection:
    is_connected = True

    def __init__(self) -> None:
        self.writes: list[tuple[str, bytes]] = []
        self.callback: object | None = None
        self.stopped = False
        self.disconnected = False

    async def start_notify(self, _characteristic: str, callback: object) -> None:
        self.callback = callback

    async def write(self, characteristic: str, value: bytes) -> None:
        self.writes.append((characteristic, value))
        if value == b"hi" and callable(self.callback):
            self.callback("Nordic UART TX", bytearray(b"hello"))

    async def stop_notify(self, _characteristic: str) -> None:
        self.stopped = True

    async def disconnect(self) -> None:
        self.disconnected = True


class DeviceRunnerTests(unittest.TestCase):
    def test_runner_returns_safe_structured_result_without_the_key(self) -> None:
        connection = FakeConnection()
        with (
            patch("lib.device_runner.get_env_key", return_value="123"),
            patch(
                "lib.device_runner.scan_devices",
                AsyncMock(return_value=[BleDevice("11:22:33:44:55:66", "octopus-led-1", -40)]),
            ),
            patch("lib.device_runner.connect_with_retries", AsyncMock(return_value=connection)),
        ):
            result = asyncio.run(
                device_runner.run_device_tool(
                    test_config(), ALIASES, "test-led", "esp-hi", timeout=1
                )
            )

        self.assertTrue(result.ok)
        self.assertEqual(result.address, "11:22:33:44:55:66")
        self.assertEqual(result.address_source, "advertised_name")
        self.assertTrue(result.connected)
        self.assertTrue(result.authentication_sent)
        self.assertEqual([item.value for item in result.sent], [b"hi"])
        self.assertEqual([item.value for item in result.notifications], [b"hello"])
        self.assertEqual([value for _, value in connection.writes], [b"123", b"hi"])
        self.assertTrue(connection.stopped)
        self.assertTrue(connection.disconnected)

    def test_runner_returns_a_typed_authentication_error(self) -> None:
        with patch("lib.device_runner.get_env_key", return_value=None):
            result = asyncio.run(
                device_runner.run_device_tool(
                    test_config(), ALIASES, "test-led", "esp-hi", timeout=1
                )
            )

        self.assertFalse(result.ok)
        self.assertIsNotNone(result.error)
        assert result.error is not None
        self.assertEqual(result.error.kind, "authentication")
        self.assertEqual(result.sent, ())
        self.assertFalse(result.authentication_sent)


if __name__ == "__main__":
    unittest.main()
