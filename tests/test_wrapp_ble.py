"""Unit tests for BLE wrapper behavior that do not need a radio adapter."""

import asyncio
import unittest
from unittest.mock import patch

import lib.wrapp_ble as ble


class TimeoutClient:
    """Minimal fake Bleak client that times out during service discovery."""

    def __init__(self, *_: object, **__: object) -> None:
        self.is_connected = False

    async def connect(self) -> None:
        raise asyncio.TimeoutError


class FlakyClient:
    """Fake client that fails once, then connects successfully."""

    calls = 0
    pair_values: list[bool] = []

    def __init__(self, *_: object, pair: bool = False, **__: object) -> None:
        self.is_connected = False
        type(self).pair_values.append(pair)

    async def connect(self) -> None:
        type(self).calls += 1
        if type(self).calls == 1:
            raise ble.BleakError("temporary connection failure")
        self.is_connected = True

    async def disconnect(self) -> None:
        self.is_connected = False


class BleConnectionTests(unittest.TestCase):
    def test_filter_devices_matches_name_address_and_advertised_service(self) -> None:
        devices = [
            ble.BleDevice("AA:BB:CC:DD:EE:FF", "Octopus LED", -40, ("service-one",)),
            ble.BleDevice("11:22:33:44:55:66", "Other", -60, ("service-two",)),
        ]
        result = ble.filter_devices(
            devices,
            name="octopus",
            address="dd:ee",
            service_uuids=["SERVICE-ONE"],
        )
        self.assertEqual(result, [devices[0]])

    def test_describe_value_keeps_text_and_binary_values_unambiguous(self) -> None:
        self.assertEqual(ble.describe_value(b"hello"), ("hello", "68 65 6c 6c 6f"))
        self.assertEqual(ble.describe_value(b"\xff"), (None, "ff"))

    def test_connection_timeout_is_expressed_as_short_domain_error(self) -> None:
        async def connect() -> None:
            connection = ble.BleConnection("AA:BB:CC:DD:EE:FF", timeout=2)
            with self.assertRaisesRegex(ble.BleConnectionError, "timed out after 2 seconds"):
                await connection.__aenter__()
            self.assertIsNone(connection._client)

        with patch.object(ble, "BleakClient", TimeoutClient):
            asyncio.run(connect())

    def test_connect_with_retries_reuses_pairing_choice(self) -> None:
        async def connect() -> None:
            retry_attempts: list[int] = []
            connection = await ble.connect_with_retries(
                "AA:BB:CC:DD:EE:FF",
                retries=1,
                retry_delay=0,
                pair=True,
                on_retry=lambda attempt, _total, _error: retry_attempts.append(attempt),
            )
            self.assertTrue(connection.is_connected)
            self.assertEqual(retry_attempts, [1])
            await connection.disconnect()

        FlakyClient.calls = 0
        FlakyClient.pair_values = []
        with patch.object(ble, "BleakClient", FlakyClient):
            asyncio.run(connect())
        self.assertEqual(FlakyClient.pair_values, [True, True])


if __name__ == "__main__":
    unittest.main()
