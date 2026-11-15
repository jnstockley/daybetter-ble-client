"""Exercise the runnable demo without accessing or changing actual lights."""

import importlib.util
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from bleak.backends.device import BLEDevice

from daybetter_ble_client.const import P031, P065
from tests.test_led_strip import advertisement


@pytest.fixture
def example():
    path = Path(__file__).resolve().parents[2] / "examples" / "test.py"
    spec = importlib.util.spec_from_file_location("daybetter_example", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeStrip:
    def __init__(self, address):
        self.address = address
        self.model = "P065"
        self.power = self.color = self.brightness = self.rssi = None
        self.connected = True
        self.update_device = AsyncMock()
        self.set_power = AsyncMock()
        self.set_color = AsyncMock()
        self.set_brightness = AsyncMock()
        self.disconnect = AsyncMock()
        self.unsubscribed = False

    def on_change(self, listener):
        listener()

        def unsubscribe():
            self.unsubscribed = True

        return unsubscribe


def devices(*services):
    return {
        str(i): (BLEDevice(str(i), f"P065_test{i}", {}), advertisement(service))
        for i, service in enumerate(services)
    }


@pytest.mark.parametrize(
    "services",
    [(), ("unrelated-service",), (P031.discovery_service, P065.discovery_service)],
)
def test_requires_exactly_one_supported_strip(
    example, monkeypatch, run_async, caplog, services
):
    monkeypatch.setattr(
        example.BleakScanner, "discover", AsyncMock(return_value=devices(*services))
    )

    def should_not_connect(*args):
        raise AssertionError(
            "Example should not connect when target is ambiguous or absent"
        )

    monkeypatch.setattr(example, "DaybetterLedStrip", should_not_connect)
    run_async(example.run())
    assert "Expected one supported strip" in caplog.text


def prepare(example, monkeypatch):
    strips = []

    def factory(address):
        strip = FakeStrip(address)
        strips.append(strip)
        return strip

    monkeypatch.setattr(
        example.BleakScanner,
        "discover",
        AsyncMock(return_value=devices(P065.discovery_service)),
    )
    monkeypatch.setattr(example, "DaybetterLedStrip", factory)
    monkeypatch.setattr(example.asyncio, "sleep", AsyncMock())
    return strips


def test_cycles_colors_and_always_disconnects(example, monkeypatch, run_async):
    strips = prepare(example, monkeypatch)
    run_async(example.run())
    strip = strips[0]
    assert [call.args for call in strip.set_color.await_args_list] == [
        ((255, 0, 0),),
        ((0, 255, 0),),
        ((0, 0, 255),),
    ]
    assert [call.args for call in strip.set_power.await_args_list] == [
        (True,),
        (False,),
    ]
    strip.set_brightness.assert_awaited_once_with(10)
    strip.disconnect.assert_awaited_once()
    assert strip.unsubscribed


@pytest.mark.parametrize("failure", ["initialization", "disconnected", "color"])
def test_failures_release_connection_and_listener(
    example, monkeypatch, run_async, failure
):
    strips = prepare(example, monkeypatch)
    original = example.DaybetterLedStrip

    def factory(address):
        strip = original(address)
        if failure == "initialization":
            strip.update_device.side_effect = RuntimeError("init failed")
        elif failure == "disconnected":
            strip.connected = False
        else:
            strip.set_color.side_effect = RuntimeError("color failed")
        return strip

    monkeypatch.setattr(example, "DaybetterLedStrip", factory)
    with pytest.raises(RuntimeError):
        run_async(example.run())
    strip = strips[0]
    strip.disconnect.assert_awaited_once()
    assert strip.unsubscribed
