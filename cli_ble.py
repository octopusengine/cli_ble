#!/usr/bin/env python3
"""A simple cross-platform command-line interface for Bluetooth Low Energy.

Requires the ``bleak`` package. On Linux, the Bluetooth adapter and BlueZ
service must be running. On Windows, Bluetooth must be enabled and the app
must not be blocked by privacy settings.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import sys
import traceback
from pathlib import Path

from lib.wrapp_ble import (
    BleConnection,
    BleConnectionError,
    BleDevice,
    BleDeviceNotFoundError,
    BleakError,
    BleUnavailableError,
    GattDescriptor,
    GattService,
    connect_with_retries,
    describe_value,
    filter_devices,
    get_env_key,
    scan_devices,
)
from lib.wrapp_terminal import Terminal

__version__ = "0.2"

CONFIG_FILE = Path(__file__).with_name("cli_ble.json")
DEVICES_FILE = Path(__file__).with_name("devices.json")
TERMINAL = Terminal()
ERROR_TERMINAL = Terminal(sys.stderr)
LOG_FILE: Path | None = None


def configure_console_output() -> None:
    """Prevent unsupported device-name characters from breaking older consoles."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="backslashreplace")


def configure_file_log(filename: str | None) -> None:
    """Enable an append-only plain-text log without terminal color codes."""
    global LOG_FILE
    if filename is None:
        return
    destination = Path(filename)
    with destination.open("a", encoding="utf-8") as log:
        log.write("--- cli_ble log started ---\n")
    LOG_FILE = destination


def log_line(text: object) -> None:
    """Append a plain-text line to the optional log file."""
    if LOG_FILE is not None:
        with LOG_FILE.open("a", encoding="utf-8") as log:
            log.write(f"{text}\n")


def info(text: object) -> None:
    """Print and optionally log normal output in plain text."""
    TERMINAL.w(text)
    log_line(text)


def info_colored(color: str, text: object) -> None:
    """Print one colored status line while keeping the optional log ANSI-free."""
    TERMINAL.print(color, text)
    log_line(text)


def info_segments(*segments: tuple[str | None, object]) -> None:
    """Print colored parts of one status line while logging its plain equivalent."""
    plain_text = "".join(str(text) for _, text in segments)
    display_text = "".join(
        TERMINAL.color(color, text) if color else str(text)
        for color, text in segments
    )
    print(display_text)
    log_line(plain_text)


def warning(text: object) -> None:
    """Print a terminal warning and append a plain-text warning to the log."""
    ERROR_TERMINAL.y(text)
    log_line(f"WARNING: {text}")


def error(text: object) -> None:
    """Print a terminal error and append a plain-text error to the log."""
    ERROR_TERMINAL.r(text)
    log_line(f"ERROR: {text}")


def configure_verbose_logging(enabled: bool) -> None:
    """Enable Bleak diagnostic logs only when verbose mode is explicitly requested."""
    if enabled:
        logging.basicConfig(level=logging.DEBUG, format="DEBUG %(name)s: %(message)s")


def report_error(exc: BaseException, verbose: bool) -> None:
    """Print a short actionable error; show the traceback only in verbose mode."""
    error(f"BLE error: {exc}")

    if isinstance(exc, BleDeviceNotFoundError):
        warning(
            "Tip: a fresh scan was performed. The device may be using a changed private address; "
            "connect again using its current scan address."
        )
    elif isinstance(exc, (BleConnectionError, asyncio.TimeoutError)):
        warning(
            "Tip: the device may be out of range, asleep, already connected elsewhere, "
            "or require pairing. Scan again and try --timeout 25."
        )
    elif isinstance(exc, BleUnavailableError):
        warning("Tip: check the Bluetooth adapter and installed dependencies.")

    if verbose:
        info("\nTechnical details:")
        for line in "".join(
            traceback.format_exception(type(exc), exc, exc.__traceback__)
        ).rstrip().splitlines():
            ERROR_TERMINAL.print("bright_black", line)
            log_line(f"DEBUG: {line}")


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scan for, connect to, and perform basic GATT operations on BLE devices.",
        epilog=(
            "Examples:\n"
            "  python cli_ble.py --scan\n"
            "  python cli_ble.py -s scan1.txt\n"
            "  python cli_ble.py -s -a  # or -sa: all devices\n"
            "  python cli_ble.py -s -t  # or -st: strongest signal\n"
            "  python cli_ble.py --examples\n"
            "  python cli_ble.py --add octopus-led-48034\n"
            "  python cli_ble.py --add octopus-led-48034 test-led\n"
            "  python cli_ble.py --delete test-led\n"
            "  python cli_ble.py -v -c AA:BB:CC:DD:EE:FF  # debug output\n"
            "  python cli_ble.py -s --name MeshCore --service UUID\n"
            "  python cli_ble.py -c AA:BB:CC:DD:EE:FF --pair --retries 2 --log session.log\n"
            "  python cli_ble.py -c AA:BB:CC:DD:EE:FF\n"
            "  python cli_ble.py -c AA:BB:CC:DD:EE:FF --send UUID 'hello'\n"
            "  python cli_ble.py -c AA:BB:CC:DD:EE:FF --receive UUID\n"
            "  python cli_ble.py -c AA:BB:CC:DD:EE:FF --read-all-safe\n"
            "  python cli_ble.py -c AA:BB:CC:DD:EE:FF --notify UUID --listen 15\n"
            "  python cli_ble.py devices\n"
            "  python cli_ble.py -d test-led led-on\n"
            "  python cli_ble.py device test-led run led-on"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("-V", "--version", action="version", version=f"%(prog)s {__version__}")
    action = parser.add_mutually_exclusive_group()
    action.add_argument(
        "-s", "--scan", nargs="?", const="", metavar="FILE",
        help="scan nearby BLE devices; optionally save the result to FILE"
    )
    action.add_argument(
        "-sa", "--scan-all", dest="scan_shortcut", action="store_const", const="all",
        help="scan and print every discovered device"
    )
    action.add_argument(
        "-st", "--scan-top", dest="scan_shortcut", action="store_const", const="top",
        help="scan and print devices with the strongest signal"
    )
    action.add_argument(
        "-c", "--connect", metavar="DEVICE", help="BLE device address or identifier"
    )
    action.add_argument(
        "-e", "--examples", action="store_true", help="print usage examples"
    )
    action.add_argument(
        "--add", metavar="ADVERTISED_NAME",
        help="discover a BLE device by its exact advertised name; optionally add AS_NAME after it"
    )
    action.add_argument(
        "--delete", metavar="DEVICE",
        help="remove a configured device after typing yes to confirm"
    )
    action.add_argument(
        "-d", "--device", nargs=2, metavar=("DEVICE", "TOOL"),
        help="run a configured device tool, e.g. -d test-led led-on"
    )
    parser.add_argument(
        "device_command", nargs="*", metavar="COMMAND",
        help="device commands: devices | device DEVICE info | device DEVICE run TOOL",
    )
    parser.add_argument(
        "--timeout", type=float, default=10.0, help="scan/connection timeout in seconds (default: 10)"
    )
    parser.add_argument(
        "--send", nargs=2, metavar=("CHARACTERISTIC", "MESSAGE"),
        help="write a text message to a GATT characteristic"
    )
    parser.add_argument(
        "--hex", action="store_true",
        help="interpret the --send message as hexadecimal, e.g. --send UUID '01 ff 7a'"
    )
    parser.add_argument(
        "--receive", "--rec", "--recieve", "--read", dest="receive", metavar="CHARACTERISTIC",
        help="read a GATT characteristic once"
    )
    parser.add_argument(
        "--read-all-safe", "--ras", dest="read_all_safe", action="store_true",
        help="read every readable characteristic and discovered descriptor; report failures individually"
    )
    parser.add_argument(
        "--notify", metavar="CHARACTERISTIC",
        help="subscribe to characteristic notifications"
    )
    parser.add_argument(
        "--listen", type=float, default=10.0,
        help="notification listening time in seconds (default: 10)"
    )
    parser.add_argument(
        "--services", action="store_true", help="print GATT services after connecting"
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="show Bleak debug logs and full technical error details"
    )
    parser.add_argument(
        "--name", metavar="TEXT", help="with scan, keep devices whose name contains TEXT"
    )
    parser.add_argument(
        "--address", metavar="TEXT", help="with scan, keep devices whose address contains TEXT"
    )
    parser.add_argument(
        "--service", "--service-uuid", dest="service_filters", metavar="UUID", action="append",
        help="with scan, keep devices advertising this service UUID; may be repeated"
    )
    parser.add_argument(
        "--pair", action="store_true",
        help="request operating-system BLE pairing before connecting"
    )
    parser.add_argument(
        "--retries", type=int, default=0, metavar="COUNT",
        help="additional connection attempts after the first one (default: 0)"
    )
    parser.add_argument(
        "--retry-delay", type=float, default=2.0, metavar="SECONDS",
        help="wait between connection attempts (default: 2)"
    )
    parser.add_argument(
        "--log", metavar="FILE", help="append plain, non-colored output to FILE"
    )
    parser.add_argument(
        "-a", "--all", dest="scan_mode", action="store_const", const="all",
        help="with -s, print every discovered device"
    )
    parser.add_argument(
        "-t", "--top", dest="scan_mode", action="store_const", const="top",
        help="with -s, print devices with the strongest signal"
    )

    args = parser.parse_args()
    command = args.device_command
    args.add_as_name = None
    if args.add is not None and command:
        if len(command) != 1:
            parser.error("use: --add ADVERTISED_NAME [AS_NAME]")
        args.add_as_name = command[0]
        command = []
    if command:
        if any((args.scan is not None, args.scan_shortcut, args.connect, args.examples, args.add is not None, args.delete, args.device)):
            parser.error("device commands cannot be combined with scan, connect, or examples actions")
        if command == ["devices"]:
            args.device_action = "list"
            args.device_id = None
            args.tool_id = None
        elif len(command) == 3 and command[0] == "device" and command[2] == "info":
            args.device_action = "info"
            args.device_id = command[1]
            args.tool_id = None
        elif len(command) == 4 and command[0] == "device" and command[2] == "run":
            args.device_action = "run"
            args.device_id = command[1]
            args.tool_id = command[3]
        else:
            parser.error("use: devices | device DEVICE info | device DEVICE run TOOL")
    else:
        if args.device:
            args.device_action = "run"
            args.device_id, args.tool_id = args.device
        else:
            args.device_action = None
            args.device_id = None
            args.tool_id = None
        if not any((args.scan is not None, args.scan_shortcut, args.connect, args.examples, args.add is not None, args.delete, args.device)):
            parser.error("choose a scan, connect, examples, add, or device command")

    is_scan = args.scan is not None or args.scan_shortcut is not None
    is_add = args.add is not None
    is_delete = args.delete is not None
    is_device_run = args.device_action == "run"
    if is_scan and any((args.send, args.receive, args.notify, args.services, args.read_all_safe)):
        parser.error("--send, --receive, --notify, --services, and --read-all-safe require --connect DEVICE")
    if not is_scan and args.scan_mode:
        parser.error("-a/--all and -t/--top require -s/--scan")
    if args.scan_shortcut and args.scan_mode:
        parser.error("use either -sa/-st or -s together with -a/-t")
    if not is_scan and not is_add and not is_delete and not args.device_action and any((args.name, args.address, args.service_filters)):
        parser.error("--name, --address, and --service require -s/--scan")
    if (args.device_action or is_add or is_delete) and any(
        (args.send, args.receive, args.notify, args.services, args.read_all_safe, args.hex, args.name, args.address, args.service_filters)
    ):
        parser.error(
            "GATT and scan filters cannot be used with device commands, --add, or --delete"
        )
    if args.read_all_safe and not args.connect:
        parser.error("--read-all-safe requires --connect DEVICE")
    if args.pair and not (args.connect or is_device_run or is_add):
        parser.error("--pair requires --connect DEVICE, --add, or a device tool")
    if args.retries < 0 or args.retry_delay < 0:
        parser.error("--retries and --retry-delay cannot be negative")
    if not (args.connect or is_device_run or is_add) and args.retries:
        parser.error("--retries requires --connect DEVICE, --add, or a device tool")
    if args.hex and not args.send:
        parser.error("--hex can only be used with --send")
    if args.listen <= 0 or args.timeout <= 0:
        parser.error("--listen and --timeout must be greater than zero")
    args.scan_mode = args.scan_shortcut or args.scan_mode or "default"
    return args


def report_value(prefix: str, value: bytes) -> None:
    """Report a sent or received value with its human-readable text highlighted."""
    text, hexadecimal = describe_value(value)
    if text is None:
        info_segments(("cyan", prefix), ("yellow", f"hex: {hexadecimal}"))
        return
    info_segments(
        ("cyan", prefix),
        (None, "text: "),
        ("yellow", repr(text)),
        (None, f"; hex: {hexadecimal}"),
    )


def print_examples() -> None:
    """Print anonymized examples without attempting BLE communication."""
    address = "AA:BB:CC:DD:EE:FF"
    battery_level_uuid = "00002a19-0000-1000-8000-00805f9b34fb"
    example_lines = (
        ("Scan (default limit from cli_ble.json):", "python cli_ble.py -s"),
        ("Scan and save to a file:", "python cli_ble.py -s scan1.txt"),
        ("Discover and add a device by its exact advertised name:", "python cli_ble.py --add octopus-led-48034"),
        ("Discover and save it with a chosen device ID:", "python cli_ble.py --add octopus-led-48034 test-led"),
        ("Delete a configured device after confirmation:", "python cli_ble.py --delete test-led"),
        ("Every discovered device:", "python cli_ble.py -sa"),
        ("10 devices with the strongest signal:", "python cli_ble.py -st"),
        ("Connect and print GATT services:", f"python cli_ble.py -c {address}"),
        (
            "Read a characteristic (Battery Level example):",
            f"python cli_ble.py -c {address} --receive {battery_level_uuid}",
        ),
        (
            "Read all readable characteristics and descriptor values:",
            f"python cli_ble.py -c {address} --read-all-safe",
        ),
        (
            "Subscribe to notifications for 30 seconds:",
            f"python cli_ble.py -c {address} --notify CHARACTERISTIC_UUID --listen 30",
        ),
        (
            "Nordic UART notification alias (equivalent to the full UUID):",
            f"python cli_ble.py -c {address} --notify nus-tx --listen 30",
        ),
        (
            "Write a text message:",
            f"python cli_ble.py -c {address} --send CHARACTERISTIC_UUID 'hello'",
        ),
        (
            "Nordic UART write alias (equivalent to the full UUID):",
            f"python cli_ble.py -c {address} --send nus-rx 'hello'",
        ),
        (
            "Write binary data:",
            f"python cli_ble.py -c {address} --send CHARACTERISTIC_UUID '01 ff 7a' --hex",
        ),
        ("List configured devices:", "python cli_ble.py devices"),
        ("Run a configured device tool (short form):", "python cli_ble.py -d test-led led-on"),
        ("Run a configured device tool (long form):", "python cli_ble.py device test-led run led-on"),
    )
    info("Usage examples (AA:BB:CC:DD:EE:FF is an anonymized MAC address):")
    for description, command in example_lines:
        info(f"\n{description}")
        info(f"  {command}")
    aliases = load_gatt_aliases()
    if aliases:
        info("\nConfigured GATT aliases:")
        for alias, uuid in aliases.items():
            info(f"  {alias} = {uuid}")


def message_to_bytes(message: str, as_hex: bool) -> bytes:
    if not as_hex:
        return message.encode("utf-8")
    try:
        return bytes.fromhex(message)
    except ValueError as exc:
        raise ValueError("the hex message must contain digit pairs, e.g. '01 ff 7a'") from exc


def format_scan_line(device: BleDevice) -> tuple[str, str]:
    """Return the plain and terminal-colored representation of a scan line."""
    name = device.name or "unnamed"
    suffix = f", RSSI {device.rssi} dBm" if device.rssi is not None else ""
    info = f"{device.address}\t"
    plain_line = f"{info}{name}{suffix}"
    display_line = (
        TERMINAL.color("white", info)
        + TERMINAL.color("yellow", name)
        + TERMINAL.color("white", suffix)
    )
    return plain_line, display_line


def print_scan_device(device: BleDevice) -> None:
    """Print a colored scan line while writing its plain equivalent to the log."""
    plain_line, display_line = format_scan_line(device)
    print(display_line)
    log_line(plain_line)


def load_cli_config() -> dict[str, object]:
    """Load the shared CLI configuration file."""
    try:
        config = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Unable to load configuration {CONFIG_FILE.name}: {exc}") from exc
    if not isinstance(config, dict):
        raise ValueError(f"{CONFIG_FILE.name} must contain a JSON object")
    return config


def load_scan_limits() -> tuple[int, int]:
    """Load default and top scan limits from cli_ble.json."""
    try:
        scan_config = load_cli_config()["scan"]
        if not isinstance(scan_config, dict):
            raise TypeError("scan must be an object")
        default_limit = scan_config["default"]
        top_limit = scan_config["top"]
    except (KeyError, TypeError) as exc:
        raise RuntimeError(f"Unable to load scan configuration from {CONFIG_FILE.name}: {exc}") from exc

    if (
        not isinstance(default_limit, int)
        or isinstance(default_limit, bool)
        or default_limit <= 0
        or not isinstance(top_limit, int)
        or isinstance(top_limit, bool)
        or top_limit <= 0
    ):
        raise ValueError("scan.default and scan.top in cli_ble.json must be positive integers")
    return default_limit, top_limit


def load_gatt_aliases() -> dict[str, str]:
    """Load case-insensitive GATT UUID aliases from cli_ble.json."""
    aliases = load_cli_config().get("gatt_aliases", {})
    if not isinstance(aliases, dict):
        raise ValueError(f"gatt_aliases in {CONFIG_FILE.name} must be an object")
    normalized: dict[str, str] = {}
    for alias, uuid in aliases.items():
        if not isinstance(alias, str) or not alias.strip():
            raise ValueError(f"GATT alias names in {CONFIG_FILE.name} must be non-empty strings")
        if not isinstance(uuid, str) or not uuid.strip():
            raise ValueError(f"GATT alias {alias!r} in {CONFIG_FILE.name} must map to a non-empty UUID")
        normalized[alias.casefold()] = uuid
    return normalized


def resolve_gatt_alias(value: str, aliases: dict[str, str]) -> str:
    """Resolve a known alias, while preserving full UUIDs and unknown values."""
    return aliases.get(value.casefold(), value)


def resolve_cli_gatt_aliases(args: argparse.Namespace) -> None:
    """Replace aliases in raw scan and GATT CLI options with their UUID values."""
    aliases = load_gatt_aliases()
    if args.service_filters:
        args.service_filters = [resolve_gatt_alias(value, aliases) for value in args.service_filters]
    if args.send:
        args.send[0] = resolve_gatt_alias(args.send[0], aliases)
    if args.receive:
        args.receive = resolve_gatt_alias(args.receive, aliases)
    if args.notify:
        args.notify = resolve_gatt_alias(args.notify, aliases)


def _require_string(value: object, location: str) -> str:
    """Return a non-empty configuration string or raise an actionable error."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{location} in {DEVICES_FILE.name} must be a non-empty string")
    return value


def load_devices_config() -> dict[str, object]:
    """Load and validate configured BLE device profiles and named tools."""
    try:
        config = json.loads(DEVICES_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Unable to load {DEVICES_FILE.name}: {exc}") from exc

    if not isinstance(config, dict):
        raise ValueError(f"{DEVICES_FILE.name} must contain a JSON object")
    if config.get("version") != 1:
        raise ValueError(f"version in {DEVICES_FILE.name} must be 1")

    profiles = config.get("profiles")
    devices = config.get("devices")
    if not isinstance(profiles, dict) or not profiles:
        raise ValueError(f"profiles in {DEVICES_FILE.name} must be a non-empty object")
    if not isinstance(devices, dict):
        raise ValueError(f"devices in {DEVICES_FILE.name} must be an object")

    for profile_id, profile in profiles.items():
        _require_string(profile_id, "profile id")
        if not isinstance(profile, dict):
            raise ValueError(f"profiles.{profile_id} in {DEVICES_FILE.name} must be an object")
        for field in ("service", "write", "notify"):
            _require_string(profile.get(field), f"profiles.{profile_id}.{field}")

    for device_id, device in devices.items():
        _require_string(device_id, "device id")
        if not isinstance(device, dict):
            raise ValueError(f"devices.{device_id} in {DEVICES_FILE.name} must be an object")
        _require_string(device.get("name"), f"devices.{device_id}.name")
        profile_id = device.get("profile")
        if profile_id is not None:
            profile_id = _require_string(profile_id, f"devices.{device_id}.profile")
            if profile_id not in profiles:
                raise ValueError(f"devices.{device_id}.profile references unknown profile {profile_id!r}")
        auth = device.get("auth")
        if auth is not None:
            if not isinstance(auth, dict):
                raise ValueError(f"devices.{device_id}.auth in {DEVICES_FILE.name} must be an object")
            if profile_id is None:
                raise ValueError(f"devices.{device_id}.auth requires a configured profile")
            _require_string(auth.get("environment"), f"devices.{device_id}.auth.environment")
        match = device.get("match")
        if not isinstance(match, dict):
            raise ValueError(f"devices.{device_id}.match in {DEVICES_FILE.name} must be an object")
        name_prefix = match.get("advertised_name_prefix")
        address = match.get("address")
        if name_prefix is not None:
            _require_string(name_prefix, f"devices.{device_id}.match.advertised_name_prefix")
        if address is not None:
            _require_string(address, f"devices.{device_id}.match.address")
        if name_prefix is None and address is None:
            raise ValueError(f"devices.{device_id}.match needs advertised_name_prefix or address")
        tools = device.get("tools", {})
        if not isinstance(tools, dict):
            raise ValueError(f"devices.{device_id}.tools in {DEVICES_FILE.name} must be an object")
        if tools and profile_id is None:
            raise ValueError(f"devices.{device_id}.tools requires a configured profile")
        for tool_id, tool in tools.items():
            _require_string(tool_id, f"devices.{device_id}.tools id")
            if not isinstance(tool, dict):
                raise ValueError(f"devices.{device_id}.tools.{tool_id} must be an object")
            _require_string(tool.get("text"), f"devices.{device_id}.tools.{tool_id}.text")
            _require_string(tool.get("description"), f"devices.{device_id}.tools.{tool_id}.description")
            notify = tool.get("notify", False)
            if not isinstance(notify, bool):
                raise ValueError(f"devices.{device_id}.tools.{tool_id}.notify must be true or false")
            if "listen" in tool:
                listen = tool["listen"]
                if isinstance(listen, bool) or not isinstance(listen, (int, float)) or listen <= 0:
                    raise ValueError(f"devices.{device_id}.tools.{tool_id}.listen must be greater than zero")
            if "listen" in tool and not notify:
                raise ValueError(f"devices.{device_id}.tools.{tool_id}.listen requires notify: true")
    return config


def configured_device(config: dict[str, object], device_id: str) -> dict[str, object]:
    """Return one validated device entry by its friendly identifier."""
    devices = config["devices"]
    assert isinstance(devices, dict)
    device = devices.get(device_id)
    if not isinstance(device, dict):
        available = ", ".join(sorted(devices))
        raise ValueError(f"Unknown device {device_id!r}. Available devices: {available}")
    return device


def print_configured_devices(config: dict[str, object]) -> None:
    """List device identifiers and labels without accessing the BLE adapter."""
    devices = config["devices"]
    assert isinstance(devices, dict)
    info("Configured devices:")
    for device_id, device in devices.items():
        assert isinstance(device, dict)
        info(f"  {device_id}  {device['name']}")


def print_configured_device_info(device_id: str, device: dict[str, object], config: dict[str, object]) -> None:
    """Print the friendly and technical detail for one configured device."""
    profiles = config["profiles"]
    assert isinstance(profiles, dict)
    profile_id = device.get("profile")
    profile = profiles.get(profile_id) if isinstance(profile_id, str) else None
    match = device["match"]
    tools = device.get("tools", {})
    assert isinstance(match, dict) and isinstance(tools, dict)
    info(f"Device: {device_id} ({device['name']})")
    if "advertised_name_prefix" in match:
        info(f"  Advertised name prefix: {match['advertised_name_prefix']}")
    if "address" in match:
        info(f"  Fallback address: {match['address']}")
    if isinstance(profile, dict):
        info(f"  Profile: {profile_id}")
        info(f"    Service: {profile['service']}")
        info(f"    Write characteristic: {profile['write']}")
        info(f"    Notify characteristic: {profile['notify']}")
    else:
        info("  Profile: not configured")
    auth = device.get("auth")
    if isinstance(auth, dict):
        info(f"  Authentication environment key: {auth['environment']}")
    info("  Tools:")
    if not tools:
        info("    No tools configured.")
    else:
        for tool_id, tool in tools.items():
            assert isinstance(tool, dict)
            info(f"    {tool_id}  {tool['description']}")


async def resolve_configured_device_address(
    device_id: str, device: dict[str, object], timeout: float
) -> str:
    """Resolve a current address from the advertised name, then fall back to config."""
    match = device["match"]
    assert isinstance(match, dict)
    prefix = match.get("advertised_name_prefix")
    address = match.get("address")
    if isinstance(prefix, str):
        scan_timeout = min(timeout, 5.0)
        info_colored("cyan", f"Finding {device_id} by advertised name ({scan_timeout:g} s)...")
        devices = await scan_devices(scan_timeout)
        candidates = [
            item for item in devices
            if (item.name or "").casefold().startswith(prefix.casefold())
        ]
        if len(candidates) == 1:
            info_segments(
                ("green", "Found "),
                ("yellow", candidates[0].name or device_id),
                (None, f" at {candidates[0].address}."),
            )
            return candidates[0].address
        if len(candidates) > 1:
            if isinstance(address, str):
                configured = [item for item in candidates if item.address.casefold() == address.casefold()]
                if len(configured) == 1:
                    return configured[0].address
            found = ", ".join(f"{item.name or 'unnamed'} ({item.address})" for item in candidates)
            raise RuntimeError(f"More than one device matches {device_id!r}: {found}")
        if not isinstance(address, str):
            raise BleDeviceNotFoundError(f"No device matched advertised name prefix {prefix!r}")
        warning(f"No device matched advertised name prefix {prefix!r}; using configured fallback address.")
    assert isinstance(address, str)
    return address


def configured_duplicates(config: dict[str, object], discovered: BleDevice) -> list[str]:
    """Return configured IDs matching a discovered device address or advertised name."""
    devices = config["devices"]
    assert isinstance(devices, dict)
    duplicates: list[str] = []
    for device_id, device in devices.items():
        assert isinstance(device, dict)
        match = device["match"]
        assert isinstance(match, dict)
        configured_address = match.get("address")
        prefix = match.get("advertised_name_prefix")
        address_match = isinstance(configured_address, str) and (
            configured_address.casefold() == discovered.address.casefold()
        )
        name_match = isinstance(prefix, str) and bool(discovered.name) and (
            discovered.name.casefold().startswith(prefix.casefold())
        )
        if address_match or name_match:
            duplicates.append(device_id)
    return duplicates


def device_id_from_name(name: str, existing_ids: object) -> str:
    """Make a unique, readable device identifier from an advertised device name."""
    assert isinstance(existing_ids, dict)
    base = re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-") or "device"
    candidate = base
    suffix = 2
    while candidate in existing_ids:
        candidate = f"{base}-{suffix}"
        suffix += 1
    return candidate


def profile_for_services(config: dict[str, object], services: list[GattService]) -> str | None:
    """Return the first configured transport whose service UUID was discovered."""
    profiles = config["profiles"]
    assert isinstance(profiles, dict)
    discovered_uuids = {service.uuid.casefold() for service in services}
    for profile_id, profile in profiles.items():
        assert isinstance(profile, dict)
        if str(profile["service"]).casefold() in discovered_uuids:
            return profile_id
    return None


def save_devices_config(config: dict[str, object]) -> None:
    """Persist a validated device configuration with stable, readable formatting."""
    DEVICES_FILE.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")


def delete_configured_device(device_id: str) -> bool:
    """Ask for confirmation before removing one configured device."""
    config = load_devices_config()
    device = configured_device(config, device_id)
    device_name = device["name"]
    answer = input(f"Delete configured device {device_id!r} ({device_name})? Type yes to confirm: ")
    if answer.strip().casefold() != "yes":
        info("Deletion cancelled.")
        return False
    devices = config["devices"]
    assert isinstance(devices, dict)
    del devices[device_id]
    save_devices_config(config)
    info_colored("green", f"Deleted configured device {device_id!r}.")
    return True


async def add_configured_device(args: argparse.Namespace) -> None:
    """Discover, inspect, and safely register one BLE device by advertised name."""
    config = load_devices_config()
    info_colored("cyan", f"Scanning for advertised device name {args.add!r} ({args.timeout:g} s)...")
    discovered = await scan_devices(args.timeout)
    candidates = [item for item in discovered if (item.name or "").casefold() == args.add.casefold()]
    if not candidates:
        raise BleDeviceNotFoundError(f"No device advertised the exact name {args.add!r}")
    if len(candidates) > 1:
        addresses = ", ".join(item.address for item in candidates)
        raise RuntimeError(f"More than one device advertised the name {args.add!r}: {addresses}")
    device = candidates[0]
    info_segments(
        ("green", "Found "),
        ("yellow", device.name or args.add),
        (None, f" at {device.address}."),
    )

    inspect_args = argparse.Namespace(**vars(args))
    inspect_args.connect = device.address
    inspect_args.send = None
    inspect_args.hex = False
    inspect_args.receive = None
    inspect_args.notify = None
    inspect_args.services = True
    services = await communicate(inspect_args)

    duplicates = configured_duplicates(config, device)
    if duplicates:
        warning(f"Not added: the discovered device already matches {', '.join(duplicates)}.")
        return

    devices = config["devices"]
    assert isinstance(devices, dict)
    requested_id = getattr(args, "add_as_name", None)
    if requested_id is not None:
        if requested_id in devices:
            raise ValueError(f"Cannot add device as {requested_id!r}: that device ID already exists")
        device_id = requested_id
    else:
        device_id = device_id_from_name(device.name or args.add, devices)
    entry: dict[str, object] = {
        "name": device.name or args.add,
        "match": {
            "advertised_name_prefix": device.name or args.add,
            "address": device.address,
        },
        "tools": {},
    }
    profile_id = profile_for_services(config, services)
    if profile_id is not None:
        entry["profile"] = profile_id
    devices[device_id] = entry
    save_devices_config(config)
    info_colored("green", f"Added {device_id!r} to {DEVICES_FILE.name}.")
    if profile_id is not None:
        info(f"Detected profile: {profile_id}. Add named tools before running device commands.")
    else:
        warning("No configured transport profile matched the discovered services; no profile was assigned.")


async def run_configured_device_tool(args: argparse.Namespace) -> None:
    """Resolve and run a named device tool through its configured BLE profile."""
    config = load_devices_config()
    device = configured_device(config, args.device_id)
    tools = device.get("tools", {})
    profiles = config["profiles"]
    assert isinstance(tools, dict) and isinstance(profiles, dict)
    profile_id = device.get("profile")
    if not isinstance(profile_id, str):
        raise ValueError(f"Device {args.device_id!r} has no configured profile and cannot run tools")
    tool = tools.get(args.tool_id)
    if not isinstance(tool, dict):
        available = ", ".join(sorted(tools))
        raise ValueError(f"Unknown tool {args.tool_id!r} for {args.device_id!r}. Available tools: {available}")
    profile = profiles[profile_id]
    assert isinstance(profile, dict)
    auth = device.get("auth")
    key: str | None = None
    if isinstance(auth, dict):
        environment_name = auth["environment"]
        assert isinstance(environment_name, str)
        key = get_env_key(environment_name)
        if not key:
            raise ValueError(
                f"Authentication key {environment_name!r} is missing or empty; set it in .env"
            )
    address = await resolve_configured_device_address(args.device_id, device, args.timeout)
    tool_args = argparse.Namespace(**vars(args))
    tool_args.connect = address
    tool_args.send = None
    tool_args.send_operations = []
    if key is not None:
        tool_args.send_operations.append(
            {
                "characteristic": profile["write"],
                "message": key,
                "sensitive": True,
            }
        )
    tool_args.send_operations.append(
        {
            "characteristic": profile["write"],
            "message": tool["text"],
            "sensitive": False,
        }
    )
    tool_args.hex = False
    tool_args.receive = None
    tool_args.notify = profile["notify"] if tool.get("notify") else None
    if "listen" in tool:
        tool_args.listen = tool["listen"]
    tool_args.services = False
    info_segments(
        ("cyan", f"Running {args.device_id} tool "),
        ("yellow", args.tool_id),
        (None, ": "),
        ("yellow", tool["description"]),
    )
    await communicate(tool_args)
    info_colored("green", "Tool completed.")


def select_scan_devices(
    devices: list[BleDevice], mode: str, default_limit: int, top_limit: int
) -> list[BleDevice]:
    """Select devices for output; top mode sorts by RSSI in descending order."""
    if mode == "all":
        return devices
    if mode == "top":
        return sorted(
            devices,
            key=lambda device: device.rssi if device.rssi is not None else -999,
            reverse=True,
        )[:top_limit]
    return devices[:default_limit]


async def scan(
    duration: float,
    output_file: str | None,
    mode: str,
    *,
    name: str | None,
    address: str | None,
    services: list[str] | None,
) -> None:
    info(f"Scanning for BLE devices ({duration:g} s)...")
    default_limit, top_limit = load_scan_limits()
    devices = await scan_devices(duration)
    devices = filter_devices(devices, name=name, address=address, service_uuids=services)
    devices = select_scan_devices(devices, mode, default_limit, top_limit)
    lines: list[str] = []
    if not devices:
        message = "No BLE devices matched the scan filters." if any((name, address, services)) else "No BLE devices found."
        lines.append(message)
        info(message)
    else:
        for device in devices:
            plain_line, _ = format_scan_line(device)
            lines.append(plain_line)
            print_scan_device(device)

    if output_file:
        destination = Path(output_file)
        destination.write_text("\n".join(lines) + "\n", encoding="utf-8")
        info(f"Result saved to: {destination}")


def print_services(services: list[GattService]) -> None:
    info("GATT services:")
    for service in services:
        info(f"  {service.uuid}  {service.description}")
        for characteristic in service.characteristics:
            properties = ", ".join(characteristic.properties)
            info(f"    {characteristic.uuid}  [{properties}]  {characteristic.description}")
            for descriptor in characteristic.descriptors:
                info(
                    f"      {descriptor.uuid}  (Handle: {descriptor.handle})  "
                    f"{descriptor.description}"
                )


async def read_all_safe_values(device: BleConnection, services: list[GattService]) -> None:
    """Read advertised readable characteristics and descriptors without aborting inspection."""
    info("Reading readable GATT values:")
    for service in services:
        for characteristic in service.characteristics:
            if "read" in {property_name.casefold() for property_name in characteristic.properties}:
                try:
                    value = await device.read(characteristic.uuid)
                except Exception as exc:
                    warning(f"Could not read characteristic {characteristic.uuid}: {exc}")
                else:
                    report_value(f"Characteristic {characteristic.uuid}: ", value)
            for descriptor in characteristic.descriptors:
                await read_descriptor_safe(device, descriptor, characteristic.uuid)


async def read_descriptor_safe(
    device: BleConnection, descriptor: GattDescriptor, characteristic_uuid: str
) -> None:
    """Read and report one descriptor without preventing other GATT reads."""
    try:
        value = await device.read_descriptor(descriptor.handle)
    except Exception as exc:
        warning(
            f"Could not read descriptor {descriptor.uuid} (handle {descriptor.handle}, "
            f"characteristic {characteristic_uuid}): {exc}"
        )
    else:
        report_value(f"Descriptor {descriptor.uuid} (handle {descriptor.handle}): ", value)


async def communicate(args: argparse.Namespace) -> list[GattService]:
    """Connect, perform requested GATT operations, and return discovered services."""
    total_attempts = args.retries + 1
    info_colored("cyan", f"Connecting to {args.connect} (attempt 1/{total_attempts})...")
    if args.pair:
        info("Requesting operating-system BLE pairing before connecting...")

    def on_retry(attempt: int, total: int, exc: BleConnectionError) -> None:
        warning(
            f"Connection attempt {attempt}/{total} failed: {exc}. "
            f"Retrying in {args.retry_delay:g} seconds..."
        )

    try:
        device = await connect_with_retries(
            args.connect,
            timeout=args.timeout,
            pair=args.pair,
            retries=args.retries,
            retry_delay=args.retry_delay,
            on_retry=on_retry,
        )
    except BleDeviceNotFoundError:
        await rescan_missing_device(args.connect, min(args.timeout, 5.0))
        raise

    try:
        if not device.is_connected:
            raise RuntimeError("Connection failed.")
        info_colored("green", "Connected.")
        discovered_services: list[GattService] = []
        send_operations = getattr(args, "send_operations", None)
        if send_operations is None:
            send_operations = []
            if args.send:
                characteristic, message = args.send
                send_operations.append(
                    {"characteristic": characteristic, "message": message, "sensitive": False}
                )
        has_send = bool(send_operations)

        read_all_safe = getattr(args, "read_all_safe", False)
        # Plain -c is a safe way to inspect the available UUIDs.
        if args.services or read_all_safe or not any((has_send, args.receive, args.notify)):
            discovered_services = device.services()
            print_services(discovered_services)

        if read_all_safe:
            await read_all_safe_values(device, discovered_services)

        if args.receive:
            value = await device.read(args.receive)
            report_value(f"Received from {args.receive}: ", value)

        notification_active = False
        if args.notify:
            def notification_handler(sender: object, data: bytearray) -> None:
                report_value(f"Notification from {sender}: ", bytes(data))

            info_colored("cyan", f"Listening to {args.notify} ({args.listen:g} s)...")
            await device.start_notify(args.notify, notification_handler)
            notification_active = True

        try:
            for operation in send_operations:
                characteristic = operation["characteristic"]
                message = operation["message"]
                sensitive = operation.get("sensitive", False)
                if not isinstance(characteristic, str) or not isinstance(message, str):
                    raise ValueError("internal send operation requires text characteristic and message")
                payload = message_to_bytes(message, args.hex)
                await device.write(characteristic, payload)
                if sensitive:
                    info_colored("cyan", "Authentication key sent.")
                else:
                    report_value(f"Sent to {characteristic}: ", payload)
            if args.notify:
                await asyncio.sleep(args.listen)
        finally:
            if notification_active:
                await device.stop_notify(args.notify)
    finally:
        await device.disconnect()
    return discovered_services


async def rescan_missing_device(address: str, duration: float) -> None:
    """Perform a short scan after a device-not-found error and show next steps."""
    warning(f"Device was not found. Running a fresh {duration:g}-second scan...")
    try:
        devices = await scan_devices(duration)
    except (BleakError, OSError, asyncio.TimeoutError) as exc:
        warning(f"Automatic scan could not be completed: {exc}")
        return

    matching_address = [device for device in devices if device.address.casefold() == address.casefold()]
    if matching_address:
        warning("The address appeared during the fresh scan; try the connection command again.")
        return

    warning(
        "The previous address was not present in the fresh scan. The device may use a private "
        "random address; identify it below and use its current address."
    )
    if devices:
        info("Nearby devices from the fresh scan:")
        for device in select_scan_devices(devices, "top", 10, 10):
            print_scan_device(device)


async def main() -> int:
    configure_console_output()
    args = parse_arguments()
    try:
        configure_file_log(args.log)
        configure_verbose_logging(args.verbose)
        if args.examples:
            print_examples()
        elif args.scan is not None or args.scan_shortcut is not None:
            resolve_cli_gatt_aliases(args)
            await scan(
                args.timeout,
                args.scan or None,
                args.scan_mode,
                name=args.name,
                address=args.address,
                services=args.service_filters,
            )
        elif args.add is not None:
            await add_configured_device(args)
        elif args.delete is not None:
            delete_configured_device(args.delete)
        elif args.device_action == "list":
            print_configured_devices(load_devices_config())
        elif args.device_action == "info":
            config = load_devices_config()
            print_configured_device_info(args.device_id, configured_device(config, args.device_id), config)
        elif args.device_action == "run":
            await run_configured_device_tool(args)
        else:
            resolve_cli_gatt_aliases(args)
            await communicate(args)
    except (
        BleUnavailableError,
        BleConnectionError,
        BleakError,
        asyncio.TimeoutError,
        ValueError,
        RuntimeError,
        OSError,
    ) as exc:
        report_error(exc, args.verbose)
        return 1
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        raise SystemExit(130)
