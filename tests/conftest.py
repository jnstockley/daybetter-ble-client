"""Keep all tests offline, including imports during collection."""

import asyncio

import bleak
import pytest

from daybetter_ble_client import led_strip

_session_guard = None


def forbidden(*args, **kwargs):
    pytest.fail("Real Bluetooth access is forbidden in the offline test suite")


async def forbidden_async(*args, **kwargs):
    forbidden()


def protect_bluetooth(monkeypatch):
    for cls in (bleak.BleakClient, bleak.BleakScanner):
        monkeypatch.setattr(cls, "__init__", forbidden)
    for method in (
        "connect",
        "disconnect",
        "read_gatt_char",
        "write_gatt_char",
        "start_notify",
        "stop_notify",
    ):
        monkeypatch.setattr(bleak.BleakClient, method, forbidden_async)
    for method in ("discover", "start", "stop"):
        monkeypatch.setattr(bleak.BleakScanner, method, forbidden_async)
    monkeypatch.setattr(led_strip, "establish_connection", forbidden_async)


def pytest_sessionstart(session):
    global _session_guard
    _session_guard = pytest.MonkeyPatch()
    protect_bluetooth(_session_guard)


def pytest_unconfigure(config):
    if _session_guard is not None:
        _session_guard.undo()


@pytest.fixture(autouse=True)
def block_real_bluetooth(monkeypatch):
    protect_bluetooth(monkeypatch)


@pytest.fixture
def run_async():
    return asyncio.run
