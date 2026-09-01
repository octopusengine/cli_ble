"""Presentation-free execution of configured BLE device tools.

Both the terminal CLI and a future MCP server use this module. It deliberately
returns data instead of printing so callers can present the same BLE operation
as colored terminal text, JSON, or another user interface.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from time import perf_counter
from typing import Mapping

from lib.wrapp_ble import (
    BleConnectionError,
    BleDeviceNotFoundError,
    BleakError,
    connect_with_retries,
    get_env_key,
    scan_devices,
)


@dataclass(frozen=True)
class SentValue:
    """One non-sensitive value successfully written by a device tool."""

    characteristic: str
    value: bytes


@dataclass(frozen=True)
class NotificationValue:
    """One value received while a device tool was listening for notifications."""

    characteristic: str
    sender: str
    value: bytes


@dataclass(frozen=True)
class DeviceToolError:
    """A stable, machine-readable failure returned by a device-tool run."""

    kind: str
    message: str


@dataclass(frozen=True)
class DeviceToolResult:
    """Structured result of running one configured device tool."""

    device_id: str
    tool_id: str
    description: str | None
    address: str | None
    address_source: str | None
    connected: bool
    authentication_sent: bool
    sent: tuple[SentValue, ...]
    notifications: tuple[NotificationValue, ...]
    duration_ms: int
    diagnostics: tuple[str, ...] = ()
    error: DeviceToolError | None = None

    @property
    def ok(self) -> bool:
        """Return whether the operation completed without a structured error."""
        return self.error is None


class DeviceToolConfigurationError(ValueError):
    """The requested device or tool has an invalid configuration."""


class DeviceToolAuthenticationError(ValueError):
    """A configured authentication key was unavailable."""


def _require_mapping(value: object, location: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise DeviceToolConfigurationError(f"{location} must be an object")
    return value


def _require_string(value: object, location: str) -> str:
    if not isinstance(value, str) or not value:
        raise DeviceToolConfigurationError(f"{location} must be a non-empty string")
    return value


def _resolve_alias(value: str, aliases: Mapping[str, str]) -> str:
    return aliases.get(value.casefold(), value)


def _result(
    *,
    device_id: str,
    tool_id: str,
    description: str | None,
    address: str | None,
    address_source: str | None,
    connected: bool,
    authentication_sent: bool,
    sent: list[SentValue],
    notifications: list[NotificationValue],
    started_at: float,
    diagnostics: list[str],
    error: DeviceToolError | None = None,
) -> DeviceToolResult:
    return DeviceToolResult(
        device_id=device_id,
        tool_id=tool_id,
        description=description,
        address=address,
        address_source=address_source,
        connected=connected,
        authentication_sent=authentication_sent,
        sent=tuple(sent),
        notifications=tuple(notifications),
        duration_ms=round((perf_counter() - started_at) * 1000),
        diagnostics=tuple(diagnostics),
        error=error,
    )


def _error_from_exception(exc: Exception) -> DeviceToolError:
    if isinstance(exc, DeviceToolAuthenticationError):
        return DeviceToolError("authentication", str(exc))
    if isinstance(exc, DeviceToolConfigurationError):
        return DeviceToolError("configuration", str(exc))
    if isinstance(exc, BleDeviceNotFoundError):
        return DeviceToolError("device_not_found", str(exc))
    if isinstance(exc, BleConnectionError):
        return DeviceToolError("connection", str(exc))
    if isinstance(exc, asyncio.TimeoutError):
        return DeviceToolError("timeout", "BLE operation timed out")
    if isinstance(exc, (BleakError, OSError)):
        return DeviceToolError("gatt", str(exc))
    return DeviceToolError("unexpected", str(exc) or type(exc).__name__)


async def _resolve_address(
    device: Mapping[str, object], timeout: float, diagnostics: list[str]
) -> tuple[str, str]:
    """Prefer the current advertised name, then use the configured fallback address."""
    match = _require_mapping(device.get("match"), "device match")
    prefix = match.get("advertised_name_prefix")
    fallback_address = match.get("address")
    if isinstance(prefix, str) and prefix:
        try:
            discovered = await scan_devices(timeout)
        except (BleakError, OSError, asyncio.TimeoutError) as exc:
            diagnostics.append(f"Advertisement scan failed: {exc}")
        else:
            matches = [
                item
                for item in discovered
                if item.name and item.name.casefold().startswith(prefix.casefold())
            ]
            if matches:
                return matches[0].address, "advertised_name"
            diagnostics.append(f"No device matched advertised-name prefix {prefix!r}; using fallback if present.")
    if isinstance(fallback_address, str) and fallback_address:
        return fallback_address, "configured_address"
    raise DeviceToolConfigurationError("device needs a matching advertised-name prefix or fallback address")


async def run_device_tool(
    config: Mapping[str, object],
    aliases: Mapping[str, str],
    device_id: str,
    tool_id: str,
    *,
    timeout: float,
    pair: bool = False,
    retries: int = 0,
    retry_delay: float = 2.0,
) -> DeviceToolResult:
    """Run a configured named tool and return its outcome without producing output.

    Authentication material is written when configured but is never included in
    ``sent``. The caller receives only the non-sensitive tool payload.
    """
    started_at = perf_counter()
    description: str | None = None
    address: str | None = None
    address_source: str | None = None
    connected = False
    authentication_sent = False
    sent: list[SentValue] = []
    notifications: list[NotificationValue] = []
    diagnostics: list[str] = []
    connection = None
    notification_active = False
    notify_characteristic: str | None = None
    failure: Exception | None = None

    try:
        devices = _require_mapping(config.get("devices"), "devices")
        device = _require_mapping(devices.get(device_id), f"device {device_id!r}")
        profiles = _require_mapping(config.get("profiles"), "profiles")
        profile_id = _require_string(device.get("profile"), f"device {device_id!r} profile")
        profile = _require_mapping(profiles.get(profile_id), f"profile {profile_id!r}")
        tools = _require_mapping(device.get("tools"), f"device {device_id!r} tools")
        tool = _require_mapping(tools.get(tool_id), f"tool {tool_id!r}")
        message = _require_string(tool.get("text"), f"tool {tool_id!r} text")
        description_value = tool.get("description")
        if isinstance(description_value, str):
            description = description_value
        write_characteristic = _resolve_alias(
            _require_string(profile.get("write"), f"profile {profile_id!r} write"), aliases
        )
        notify_characteristic = _resolve_alias(
            _require_string(profile.get("notify"), f"profile {profile_id!r} notify"), aliases
        )
        listen = tool.get("listen", 10.0)
        if not isinstance(listen, (int, float)) or listen <= 0:
            raise DeviceToolConfigurationError(f"tool {tool_id!r} listen must be greater than zero")

        key: str | None = None
        auth = device.get("auth")
        if auth is not None:
            auth_config = _require_mapping(auth, f"device {device_id!r} auth")
            environment_name = _require_string(auth_config.get("environment"), "authentication environment")
            key = get_env_key(environment_name)
            if not key:
                raise DeviceToolAuthenticationError(
                    f"Authentication key {environment_name!r} is missing or empty; set it in .env"
                )

        address, address_source = await _resolve_address(device, timeout, diagnostics)
        connection = await connect_with_retries(
            address,
            timeout=timeout,
            pair=pair,
            retries=retries,
            retry_delay=retry_delay,
        )
        if not connection.is_connected:
            raise BleConnectionError("Connection failed.")
        connected = True

        if tool.get("notify"):
            def notification_handler(sender: object, data: bytearray) -> None:
                notifications.append(
                    NotificationValue(notify_characteristic, str(sender), bytes(data))
                )

            await connection.start_notify(notify_characteristic, notification_handler)
            notification_active = True

        if key is not None:
            await connection.write(write_characteristic, key.encode("utf-8"))
            authentication_sent = True
        payload = message.encode("utf-8")
        await connection.write(write_characteristic, payload)
        sent.append(SentValue(write_characteristic, payload))
        if notification_active:
            await asyncio.sleep(float(listen))
    except Exception as exc:
        failure = exc
    finally:
        if connection is not None:
            try:
                if notification_active and notify_characteristic is not None:
                    await connection.stop_notify(notify_characteristic)
            except Exception as exc:
                if failure is None:
                    failure = exc
            finally:
                try:
                    await connection.disconnect()
                except Exception as exc:
                    if failure is None:
                        failure = exc

    if failure is not None:
        return _result(
            device_id=device_id,
            tool_id=tool_id,
            description=description,
            address=address,
            address_source=address_source,
            connected=connected,
            authentication_sent=authentication_sent,
            sent=sent,
            notifications=notifications,
            started_at=started_at,
            diagnostics=diagnostics,
            error=_error_from_exception(failure),
        )

    return _result(
        device_id=device_id,
        tool_id=tool_id,
        description=description,
        address=address,
        address_source=address_source,
        connected=connected,
        authentication_sent=authentication_sent,
        sent=sent,
        notifications=notifications,
        started_at=started_at,
        diagnostics=diagnostics,
    )
