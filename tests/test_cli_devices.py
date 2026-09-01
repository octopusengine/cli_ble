"""Tests for configured BLE device profiles and named tools."""

import argparse
import asyncio
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import AsyncMock, patch

import cli_ble
from lib.wrapp_ble import BleDevice, GattCharacteristic, GattDescriptor, GattService


class ConfiguredDeviceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = cli_ble.load_devices_config()
        self.device = cli_ble.configured_device(self.config, "test-led")

    def test_test_led_uses_nordic_uart_and_has_named_tools(self) -> None:
        self.assertEqual(self.device["profile"], "nordic-uart")
        self.assertEqual(
            self.config["profiles"]["nordic-uart"]["write"],
            "nus-rx",
        )
        self.assertEqual(self.device["tools"]["led-on"]["text"], "!B516")
        self.assertEqual(self.device["tools"]["led-off"]["text"], "!B615")
        self.assertEqual(self.device["tools"]["led-toggle"]["text"], "!B813")
        self.assertEqual(self.device["tools"]["esp-hi"]["text"], "hi")
        self.assertTrue(self.device["tools"]["esp-hi"]["notify"])
        self.assertEqual(self.device["tools"]["esp-hi"]["listen"], 2)
        self.assertEqual(self.device["auth"]["environment"], "KEY1")

    def test_unknown_device_lists_available_ids(self) -> None:
        with self.assertRaisesRegex(ValueError, r"Available devices: .*test-led"):
            cli_ble.configured_device(self.config, "missing")

    def test_name_prefix_resolves_a_current_rotating_address(self) -> None:
        devices = [BleDevice("11:22:33:44:55:66", "octopus-led-99999", -45)]
        with (
            patch("cli_ble.scan_devices", AsyncMock(return_value=devices)),
            patch("cli_ble.info_colored"),
            patch("cli_ble.info_segments"),
        ):
            address = asyncio.run(
                cli_ble.resolve_configured_device_address("test-led", self.device, 10)
            )
        self.assertEqual(address, "11:22:33:44:55:66")

    def test_configured_address_is_used_when_no_name_matches(self) -> None:
        with (
            patch("cli_ble.scan_devices", AsyncMock(return_value=[])),
            patch("cli_ble.info_colored"),
            patch("cli_ble.warning"),
        ):
            address = asyncio.run(
                cli_ble.resolve_configured_device_address("test-led", self.device, 10)
            )
        self.assertEqual(address, "48:31:B7:33:D0:36")

    def test_duplicate_detection_uses_address_and_advertised_name_prefix(self) -> None:
        same_address = BleDevice("48:31:B7:33:D0:36", "different", -45)
        matching_prefix = BleDevice("11:22:33:44:55:66", "octopus-led-new", -45)
        self.assertEqual(cli_ble.configured_duplicates(self.config, same_address), ["test-led"])
        self.assertEqual(cli_ble.configured_duplicates(self.config, matching_prefix), ["test-led"])

    def test_profile_detection_and_id_generation(self) -> None:
        services = [
            GattService(
                "6e400001-b5a3-f393-e0a9-e50e24dcca9e",
                "Nordic UART Service",
                (),
            )
        ]
        self.assertEqual(cli_ble.profile_for_services(self.config, services), "nordic-uart")
        self.assertEqual(cli_ble.device_id_from_name("Octopus LED 48034", {"octopus-led-48034": {}}), "octopus-led-48034-2")

    def test_add_registers_an_unknown_device_with_its_discovered_address(self) -> None:
        config = {
            "version": 1,
            "profiles": {
                "nordic-uart": {
                    "service": "6e400001-b5a3-f393-e0a9-e50e24dcca9e",
                    "write": "write-uuid",
                    "notify": "notify-uuid",
                }
            },
            "devices": {},
        }
        services = [GattService("6e400001-b5a3-f393-e0a9-e50e24dcca9e", "Nordic UART Service", ())]
        args = argparse.Namespace(
            add="new-device",
            add_as_name="my-new-device",
            timeout=1,
            pair=False,
            retries=0,
            retry_delay=0,
        )
        with TemporaryDirectory() as directory:
            config_path = Path(directory) / "devices.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            with (
                patch.object(cli_ble, "DEVICES_FILE", config_path),
                patch("cli_ble.scan_devices", AsyncMock(return_value=[BleDevice("11:22:33:44:55:66", "new-device", -40)])),
                patch("cli_ble.communicate", AsyncMock(return_value=services)),
                patch("cli_ble.info_colored"),
                patch("cli_ble.info_segments"),
                patch("cli_ble.info"),
                patch("cli_ble.warning"),
            ):
                asyncio.run(cli_ble.add_configured_device(args))
            saved = json.loads(config_path.read_text(encoding="utf-8"))
        entry = saved["devices"]["my-new-device"]
        self.assertEqual(entry["match"]["address"], "11:22:33:44:55:66")
        self.assertEqual(entry["profile"], "nordic-uart")
        self.assertEqual(entry["tools"], {})

    def test_add_accepts_a_mac_address_and_saves_the_discovered_name(self) -> None:
        config = {
            "version": 1,
            "profiles": {
                "test-profile": {
                    "service": "service-uuid",
                    "write": "write-uuid",
                    "notify": "notify-uuid",
                }
            },
            "devices": {},
        }
        args = argparse.Namespace(
            add="f8-ed-34-67-47-e0",
            add_as_name="smartsolar",
            timeout=1,
            pair=False,
            retries=0,
            retry_delay=0,
        )
        device = BleDevice("F8:ED:34:67:47:E0", "SmartSolar HQ1945MC2EK", -69)
        with TemporaryDirectory() as directory:
            config_path = Path(directory) / "devices.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            with (
                patch.object(cli_ble, "DEVICES_FILE", config_path),
                patch("cli_ble.scan_devices", AsyncMock(return_value=[device])),
                patch("cli_ble.communicate", AsyncMock(return_value=[])),
                patch("cli_ble.info_colored"),
                patch("cli_ble.info_segments"),
                patch("cli_ble.warning"),
            ):
                asyncio.run(cli_ble.add_configured_device(args))
            saved = json.loads(config_path.read_text(encoding="utf-8"))
        entry = saved["devices"]["smartsolar"]
        self.assertEqual(entry["name"], "SmartSolar HQ1945MC2EK")
        self.assertEqual(entry["match"]["advertised_name_prefix"], "SmartSolar HQ1945MC2EK")
        self.assertEqual(entry["match"]["address"], "F8:ED:34:67:47:E0")

    def test_delete_requires_yes_and_removes_only_the_confirmed_device(self) -> None:
        config = {
            "version": 1,
            "profiles": {
                "nordic-uart": {
                    "service": "service-uuid",
                    "write": "write-uuid",
                    "notify": "notify-uuid",
                }
            },
            "devices": {
                "delete-me": {
                    "name": "Delete Me",
                    "match": {"address": "11:22:33:44:55:66"},
                    "tools": {},
                }
            },
        }
        with TemporaryDirectory() as directory:
            config_path = Path(directory) / "devices.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            with (
                patch.object(cli_ble, "DEVICES_FILE", config_path),
                patch("builtins.input", return_value="no"),
                patch("cli_ble.info"),
                patch("cli_ble.info_colored"),
            ):
                self.assertFalse(cli_ble.delete_configured_device("delete-me"))
            self.assertIn("delete-me", json.loads(config_path.read_text(encoding="utf-8"))["devices"])
            with (
                patch.object(cli_ble, "DEVICES_FILE", config_path),
                patch("builtins.input", return_value="yes"),
                patch("cli_ble.info"),
                patch("cli_ble.info_colored"),
            ):
                self.assertTrue(cli_ble.delete_configured_device("delete-me"))
            self.assertNotIn("delete-me", json.loads(config_path.read_text(encoding="utf-8"))["devices"])

    def test_configured_run_delegates_to_the_shared_device_runner(self) -> None:
        args = argparse.Namespace(device_id="test-led", tool_id="esp-hi", timeout=1)
        result = cli_ble.device_runner.DeviceToolResult(
            device_id="test-led",
            tool_id="esp-hi",
            description="Send a greeting and wait for hello",
            address="11:22:33:44:55:66",
            address_source="advertised_name",
            connected=True,
            authentication_sent=True,
            sent=(
                cli_ble.device_runner.SentValue(
                    "6e400002-b5a3-f393-e0a9-e50e24dcca9e", b"hi"
                ),
            ),
            notifications=(),
            duration_ms=12,
        )
        with (
            patch("cli_ble.device_runner.run_device_tool", AsyncMock(return_value=result)) as run_tool,
            patch("cli_ble.info_segments"),
            patch("cli_ble.info_colored"),
            patch("cli_ble.info"),
        ):
            asyncio.run(cli_ble.run_configured_device_tool(args))
        self.assertEqual(run_tool.call_args.args[2:4], ("test-led", "esp-hi"))
        self.assertEqual(
            run_tool.call_args.args[1]["nus-rx"], "6e400002-b5a3-f393-e0a9-e50e24dcca9e"
        )

    def test_short_and_long_device_commands_select_the_same_tool(self) -> None:
        with patch.object(sys, "argv", ["cli_ble.py", "-d", "test-led", "led-on"]):
            short_args = cli_ble.parse_arguments()
        with patch.object(sys, "argv", ["cli_ble.py", "device", "test-led", "run", "led-on"]):
            long_args = cli_ble.parse_arguments()
        self.assertEqual(
            (short_args.device_action, short_args.device_id, short_args.tool_id),
            (long_args.device_action, long_args.device_id, long_args.tool_id),
        )

    def test_device_without_a_tool_selects_safe_inspection(self) -> None:
        with patch.object(sys, "argv", ["cli_ble.py", "-d", "test-led"]):
            args = cli_ble.parse_arguments()
        self.assertEqual((args.device_action, args.device_id, args.tool_id), ("inspect", "test-led", None))

    def test_device_inspection_prints_config_and_connects_without_writing(self) -> None:
        args = argparse.Namespace(
            device_id="test-led",
            timeout=5,
            pair=False,
            retries=0,
            retry_delay=2,
            services=False,
            read_all_safe=False,
        )
        with (
            patch("cli_ble.load_devices_config", return_value=self.config),
            patch("cli_ble.print_configured_device_info") as print_info,
            patch("cli_ble.resolve_configured_device_address", AsyncMock(return_value="11:22:33:44:55:66")),
            patch("cli_ble.communicate", AsyncMock(return_value=[])) as communicate,
        ):
            asyncio.run(cli_ble.inspect_configured_device(args))
        print_info.assert_called_once_with("test-led", self.device, self.config)
        self.assertEqual(communicate.call_args.args[0].connect, "11:22:33:44:55:66")
        self.assertTrue(communicate.call_args.args[0].services)
        self.assertIsNone(communicate.call_args.args[0].send)
        self.assertIsNone(communicate.call_args.args[0].notify)

    def test_add_accepts_an_optional_configured_device_id(self) -> None:
        with patch.object(
            sys,
            "argv",
            ["cli_ble.py", "--add", "octopus-led-48034", "test-led"],
        ):
            args = cli_ble.parse_arguments()
        self.assertEqual(args.add, "octopus-led-48034")
        self.assertEqual(args.add_as_name, "test-led")
        self.assertIsNone(args.device_action)

    def test_add_identifies_colon_separated_mac_addresses(self) -> None:
        self.assertTrue(cli_ble.is_mac_address("F8:ED:34:67:47:E0"))
        self.assertTrue(cli_ble.is_mac_address("f8-ed-34-67-47-e0"))
        self.assertFalse(cli_ble.is_mac_address("SmartSolar HQ1945MC2EK"))
        self.assertEqual(
            cli_ble.normalize_mac_address("F8:ED:34:67:47:E0"),
            cli_ble.normalize_mac_address("f8-ed-34-67-47-e0"),
        )

    def test_read_all_safe_requires_a_connection_and_is_parsed(self) -> None:
        with patch.object(
            sys,
            "argv",
            ["cli_ble.py", "--connect", "AA:BB:CC:DD:EE:FF", "--ras"],
        ):
            args = cli_ble.parse_arguments()
        self.assertTrue(args.read_all_safe)
        self.assertEqual(args.connect, "AA:BB:CC:DD:EE:FF")

    def test_notification_source_does_not_repeat_a_uuid_already_in_sender(self) -> None:
        uuid = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"
        item = cli_ble.device_runner.NotificationValue(
            uuid,
            f"{uuid} (Handle: 15): Nordic UART TX",
            b"hello",
        )
        self.assertEqual(
            cli_ble.notification_source_label(item),
            f"{uuid} (Handle: 15): Nordic UART TX",
        )

    def test_gatt_aliases_are_optional_shortcuts_for_full_uuids(self) -> None:
        aliases = cli_ble.load_gatt_aliases()
        self.assertEqual(
            cli_ble.resolve_gatt_alias("NUS-TX", aliases),
            "6e400003-b5a3-f393-e0a9-e50e24dcca9e",
        )
        self.assertEqual(
            cli_ble.resolve_gatt_alias("6e400003-b5a3-f393-e0a9-e50e24dcca9e", aliases),
            "6e400003-b5a3-f393-e0a9-e50e24dcca9e",
        )
        args = argparse.Namespace(
            service_filters=["nus"],
            send=["nus-rx", "hi"],
            receive=None,
            notify="nus-tx",
        )
        cli_ble.resolve_cli_gatt_aliases(args)
        self.assertEqual(args.service_filters, ["6e400001-b5a3-f393-e0a9-e50e24dcca9e"])
        self.assertEqual(args.send[0], "6e400002-b5a3-f393-e0a9-e50e24dcca9e")
        self.assertEqual(args.notify, "6e400003-b5a3-f393-e0a9-e50e24dcca9e")

    def test_gatt_inspection_lists_descriptors_and_safely_reads_each_value(self) -> None:
        services = [
            GattService(
                "service-uuid",
                "Test Service",
                (
                    GattCharacteristic(
                        "readable-uuid",
                        "Readable",
                        ("read",),
                        (GattDescriptor(10, "descriptor-uuid", "Descriptor"),),
                    ),
                    GattCharacteristic(
                        "blocked-uuid",
                        "Blocked",
                        ("read",),
                        (GattDescriptor(11, "blocked-descriptor", "Blocked descriptor"),),
                    ),
                    GattCharacteristic(
                        "write-only-uuid",
                        "Write only",
                        ("write",),
                        (GattDescriptor(12, "write-descriptor", "Write descriptor"),),
                    ),
                ),
            )
        ]

        class FakeConnection:
            def __init__(self) -> None:
                self.characteristic_reads: list[str] = []
                self.descriptor_reads: list[int] = []

            async def read(self, uuid: str) -> bytes:
                self.characteristic_reads.append(uuid)
                if uuid == "blocked-uuid":
                    raise RuntimeError("not authorised")
                return b"characteristic value"

            async def read_descriptor(self, handle: int) -> bytes:
                self.descriptor_reads.append(handle)
                if handle == 11:
                    raise RuntimeError("descriptor not authorised")
                return f"descriptor {handle}".encode()

        connection = FakeConnection()
        with (
            patch("cli_ble.info") as info,
            patch("cli_ble.info_segments"),
            patch("cli_ble.warning") as warning,
        ):
            cli_ble.print_services(services)
            asyncio.run(cli_ble.read_all_safe_values(connection, services))

        self.assertTrue(any("descriptor-uuid" in call.args[0] for call in info.call_args_list))
        self.assertEqual(connection.characteristic_reads, ["readable-uuid", "blocked-uuid"])
        self.assertEqual(connection.descriptor_reads, [10, 11, 12])
        warnings = [call.args[0] for call in warning.call_args_list]
        self.assertTrue(any("blocked-uuid" in message for message in warnings))
        self.assertTrue(any("blocked-descriptor" in message for message in warnings))


class NotificationOrderTests(unittest.TestCase):
    def test_notification_starts_before_a_write_and_stops_afterwards(self) -> None:
        class FakeConnection:
            is_connected = True

            def __init__(self) -> None:
                self.calls: list[str] = []

            async def start_notify(self, _characteristic: str, callback: object) -> None:
                self.calls.append("notify")
                self.callback = callback

            async def write(self, _characteristic: str, _payload: bytes) -> None:
                self.calls.append("write")

            async def stop_notify(self, _characteristic: str) -> None:
                self.calls.append("stop-notify")

            async def disconnect(self) -> None:
                self.calls.append("disconnect")

        connection = FakeConnection()
        args = argparse.Namespace(
            connect="AA:BB:CC:DD:EE:FF",
            retries=0,
            retry_delay=0,
            timeout=1,
            pair=False,
            services=False,
            send=["write-uuid", "hi"],
            hex=False,
            receive=None,
            notify="notify-uuid",
            listen=0.001,
        )
        with (
            patch("cli_ble.connect_with_retries", AsyncMock(return_value=connection)),
            patch("cli_ble.info_colored"),
            patch("cli_ble.info_segments"),
        ):
            asyncio.run(cli_ble.communicate(args))
        self.assertEqual(connection.calls, ["notify", "write", "stop-notify", "disconnect"])


if __name__ == "__main__":
    unittest.main()
