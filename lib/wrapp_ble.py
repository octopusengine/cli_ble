"""Reusable asynchronous interface for Bluetooth Low Energy.

This module is a thin platform-independent layer over :mod:`bleak`. It works
on Windows and Linux (Linux requires BlueZ). It contains no CLI or file I/O,
so it can also be used from other Python applications.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

try:
    from bleak import BleakClient, BleakScanner
    from bleak.exc import BleakDeviceNotFoundError as BleakBackendDeviceNotFoundError
    from bleak.exc import BleakError
except ImportError:
    BleakClient = BleakScanner = None  # type: ignore[assignment,misc]
    BleakBackendDeviceNotFoundError = RuntimeError
    BleakError = RuntimeError

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None  # type: ignore[assignment]


ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class BleUnavailableError(RuntimeError):
    """The Bluetooth library or adapter is unavailable."""


class BleConnectionError(RuntimeError):
    """A connection to a BLE device could not be established or completed."""


class BleDeviceNotFoundError(BleConnectionError):
    """The requested BLE address was not present when connecting."""


@dataclass(frozen=True)
class BleDevice:
    """Basic information about a device found during a BLE scan."""

    address: str
    name: str | None
    rssi: int | None
    service_uuids: tuple[str, ...] = ()


@dataclass(frozen=True)
class GattCharacteristic:
    """Description of one GATT characteristic."""

    uuid: str
    description: str
    properties: tuple[str, ...]


@dataclass(frozen=True)
class GattService:
    """Description of a GATT service and its characteristics."""

    uuid: str
    description: str
    characteristics: tuple[GattCharacteristic, ...]


def filter_devices(
    devices: list[BleDevice],
    *,
    name: str | None = None,
    address: str | None = None,
    service_uuids: list[str] | None = None,
) -> list[BleDevice]:
    """Filter scan results by case-insensitive name, address, and service UUID."""
    name_filter = name.casefold() if name else None
    address_filter = address.casefold() if address else None
    services_filter = {service.casefold() for service in service_uuids or []}
    return [
        device
        for device in devices
        if (not name_filter or name_filter in (device.name or "").casefold())
        and (not address_filter or address_filter in device.address.casefold())
        and (
            not services_filter
            or services_filter.intersection(service.casefold() for service in device.service_uuids)
        )
    ]


def describe_value(value: bytes) -> tuple[str | None, str]:
    """Return the UTF-8 text, when decodable, and an always-safe hex representation."""
    hexadecimal = value.hex(" ") or "(empty)"
    try:
        return value.decode("utf-8"), hexadecimal
    except UnicodeDecodeError:
        return None, hexadecimal


def _require_bleak() -> None:
    if BleakClient is None or BleakScanner is None:
        raise BleUnavailableError(
            "The bleak dependency is missing. Install it with: python -m pip install -r requirements.txt"
        )


def get_env_key(name: str) -> str | None:
    """Load one named key from the local ``.env`` file or the environment.

    The caller defines the device-specific authentication protocol.
    """
    if not name:
        raise ValueError("environment key name must not be empty")
    if load_dotenv is None:
        raise BleUnavailableError(
            "The python-dotenv dependency is missing. Install it with: "
            "python -m pip install -r requirements.txt"
        )
    load_dotenv(ENV_FILE, override=False)
    return os.getenv(name)


def get_ble_key() -> str | None:
    """Load the legacy ``BLE_KEY`` environment entry."""
    return get_env_key("BLE_KEY")


async def scan_devices(timeout: float = 10.0) -> list[BleDevice]:
    """Return BLE devices found during the specified number of seconds."""
    _require_bleak()
    if timeout <= 0:
        raise ValueError("timeout must be greater than zero")

    discovered = await BleakScanner.discover(timeout=timeout, return_adv=True)

    # Newer Bleak versions return a dictionary of address to
    # (BLEDevice, AdvertisementData) pairs; RSSI is in advertisement data.
    if isinstance(discovered, dict):
        return [
            BleDevice(
                address=device.address,
                name=device.name,
                rssi=getattr(advertisement, "rssi", getattr(device, "rssi", None)),
                service_uuids=tuple(getattr(advertisement, "service_uuids", ()) or ()),
            )
            for device, advertisement in discovered.values()
        ]

    # Preserve compatibility with older Bleak backend implementations.
    return [
        BleDevice(
            address=device.address,
            name=device.name,
            rssi=getattr(device, "rssi", None),
            service_uuids=(),
        )
        for device in discovered
    ]


NotificationHandler = Callable[[object, bytearray], None]
RetryCallback = Callable[[int, int, BleConnectionError], None]


class BleConnection:
    """Asynchronous BLE connection and its common GATT operations.

    Usage::

        async with BleConnection("AA:BB:CC:DD:EE:FF") as device:
            value = await device.read("UUID")
            await device.write("UUID", b"hello")
    """

    def __init__(self, device: str, timeout: float = 10.0, pair: bool = False) -> None:
        if timeout <= 0:
            raise ValueError("timeout must be greater than zero")
        self.device = device
        self.timeout = timeout
        self.pair = pair
        self._client: BleakClient | None = None

    @property
    def is_connected(self) -> bool:
        """Return whether the connection is active."""
        return bool(self._client and self._client.is_connected)

    @property
    def client(self) -> BleakClient:
        """Native Bleak client for advanced operations."""
        if self._client is None:
            raise RuntimeError("The device is not connected.")
        return self._client

    async def __aenter__(self) -> BleConnection:
        return await self.connect()

    async def connect(self) -> BleConnection:
        """Connect to the BLE device, optionally requesting OS-level pairing."""
        _require_bleak()
        if self._client is not None:
            raise RuntimeError("This BleConnection instance is already in use.")
        self._client = BleakClient(self.device, timeout=self.timeout, pair=self.pair)
        try:
            await self._client.connect()
        except asyncio.TimeoutError as exc:
            await self._close_failed_client()
            raise BleConnectionError(
                f"Connection to {self.device} timed out after {self.timeout:g} seconds."
            ) from exc
        except BleakBackendDeviceNotFoundError as exc:
            await self._close_failed_client()
            raise BleDeviceNotFoundError(
                f"Device with address {self.device} was not found."
            ) from exc
        except BleakError as exc:
            await self._close_failed_client()
            raise BleConnectionError(f"Unable to connect to {self.device}: {exc}") from exc
        if not self._client.is_connected:
            await self._close_failed_client()
            raise BleConnectionError(f"Connection to {self.device} failed.")
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.disconnect()

    async def disconnect(self) -> None:
        """Disconnect from the BLE device when currently connected."""
        if self._client is not None and self._client.is_connected:
            await self._client.disconnect()
        self._client = None

    async def _close_failed_client(self) -> None:
        """Release a partially connected client without masking the original error."""
        try:
            if self._client is not None and self._client.is_connected:
                await self._client.disconnect()
        except Exception:
            pass
        finally:
            self._client = None

    def services(self) -> list[GattService]:
        """Return services and characteristics discovered after connecting."""
        return [
            GattService(
                uuid=service.uuid,
                description=service.description,
                characteristics=tuple(
                    GattCharacteristic(
                        uuid=characteristic.uuid,
                        description=characteristic.description,
                        properties=tuple(characteristic.properties),
                    )
                    for characteristic in service.characteristics
                ),
            )
            for service in self.client.services
        ]

    async def read(self, characteristic: str) -> bytes:
        """Read one GATT characteristic."""
        return bytes(await self.client.read_gatt_char(characteristic))

    async def write(
        self, characteristic: str, data: bytes, response: bool | None = None
    ) -> None:
        """Write data to a GATT characteristic.

        If ``response`` is unspecified, use Write Request when the
        characteristic supports it, otherwise use Write Command.
        """
        if response is None:
            info = self.client.services.get_characteristic(characteristic)
            response = bool(info and "write" in info.properties)
        await self.client.write_gatt_char(characteristic, data, response=response)

    async def start_notify(
        self, characteristic: str, callback: NotificationHandler
    ) -> None:
        """Start subscribing to a GATT characteristic's notifications."""
        await self.client.start_notify(characteristic, callback)

    async def stop_notify(self, characteristic: str) -> None:
        """Stop subscribing to notifications."""
        await self.client.stop_notify(characteristic)


async def connect_with_retries(
    device: str,
    *,
    timeout: float = 10.0,
    pair: bool = False,
    retries: int = 0,
    retry_delay: float = 2.0,
    on_retry: RetryCallback | None = None,
) -> BleConnection:
    """Connect to a device, retrying connection errors when requested.

    ``retries`` is the number of additional attempts after the first one.
    The returned connection is already connected and must be disconnected by
    the caller, for example with ``await connection.disconnect()``.
    """
    if retries < 0:
        raise ValueError("retries cannot be negative")
    if retry_delay < 0:
        raise ValueError("retry_delay cannot be negative")

    total_attempts = retries + 1
    for attempt in range(1, total_attempts + 1):
        connection = BleConnection(device, timeout=timeout, pair=pair)
        try:
            return await connection.connect()
        except BleConnectionError as exc:
            if attempt == total_attempts:
                raise
            if on_retry is not None:
                on_retry(attempt, total_attempts, exc)
            await asyncio.sleep(retry_delay)

    raise RuntimeError("Connection retry loop ended unexpectedly.")
