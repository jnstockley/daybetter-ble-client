"""Public command/state and lifecycle behavior, without real BLE."""

import asyncio
from unittest.mock import AsyncMock

import pytest
from bleak.backends.device import BLEDevice
from bleak.exc import BleakError

from daybetter_ble_client import DaybetterLedStrip, led_strip
from daybetter_ble_client.const import Effect
from daybetter_ble_client.util import correct_color, modbus
from tests.test_led_strip import FakeClient, advertisement


@pytest.mark.parametrize(
    ("data", "checksum"),
    [
        (b"", b"\xff\xff"),
        (b"123456789", bytes.fromhex("37 4b")),
        (bytes.fromhex("a0 15 06 ff 00 00"), bytes.fromhex("25 c0")),
    ],
)
def test_modbus_known_vectors(data, checksum):
    assert modbus(data) == checksum


@pytest.mark.parametrize(
    ("color", "expected"),
    [
        ((0, 0, 0), (0, 0, 0)),
        ((255, 255, 255), (255, 100, 140)),
        ((-1, 256, 1000), (0, 100, 140)),
        ((128, 128, 128), (42, 16, 23)),
    ],
)
def test_gamma_correction_and_channel_calibration(color, expected):
    assert correct_color(color) == expected


@pytest.fixture
def connected():
    strip = DaybetterLedStrip("device")
    client = FakeClient()
    strip.client = client
    return strip, client


@pytest.mark.parametrize(
    ("method", "value", "prefix", "pending"),
    [
        ("set_power", True, "a0 11 04 01", "pending_power"),
        ("set_power", False, "a0 11 04 00", "pending_power"),
        ("set_brightness", 0, "a0 13 04 00", "pending_brightness"),
        ("set_brightness", 100, "a0 13 04 64", "pending_brightness"),
        ("set_effect", Effect.FADE_RED_GREEN, "a0 12 04 14", "pending_effect"),
    ],
)
def test_commands_emit_expected_header_and_payload(
    connected, run_async, method, value, prefix, pending
):
    strip, client = connected
    run_async(getattr(strip, method)(value))
    assert client.writes[-1][1][:-2] == bytes.fromhex(prefix)
    assert getattr(strip, pending) == value


@pytest.mark.parametrize("value", [-1, 101])
def test_invalid_brightness_does_not_write(connected, run_async, caplog, value):
    strip, client = connected
    run_async(strip.set_brightness(value))
    assert client.writes == []
    assert strip.pending_brightness is None
    assert "out of range" in caplog.text


def test_uncorrected_color_is_sent_without_gamma(connected, run_async):
    strip, client = connected
    run_async(strip.set_color((128, 128, 128), color_correction=False))
    assert client.writes[-1][1][:-2] == bytes.fromhex("a0 15 06 80 80 80")


def test_disconnected_commands_do_not_touch_transport(run_async, caplog):
    strip = DaybetterLedStrip("device")
    run_async(strip.set_power(True))
    assert not strip.connected
    assert "not connected" in caplog.text


def test_write_failure_is_logged_without_committing_state(connected, run_async, caplog):
    strip, client = connected
    client.write_gatt_char = AsyncMock(side_effect=BleakError("write failed"))
    run_async(strip.set_power(True))
    assert strip.power is None
    assert "write failed" in caplog.text


@pytest.mark.parametrize(
    ("command", "pending", "value", "state"),
    [
        (0x11, "pending_power", False, "power"),
        (0x12, "pending_effect", Effect.FADE_RED_GREEN, "effect"),
        (0x13, "pending_brightness", 50, "brightness"),
        (0x15, "pending_color", (255, 0, 0), "color"),
    ],
)
def test_success_ack_commits_only_pending_state(
    run_async, command, pending, value, state
):
    strip = DaybetterLedStrip("device")
    setattr(strip, pending, value)
    strip.color = (0, 255, 0)
    strip.effect = Effect.SHOW_BLUE
    changes = []
    strip.on_change(lambda: changes.append(getattr(strip, state)))
    # The state parser consumes the protocol header/payload; CRC has separate vectors.
    reply = bytes([0xA1, command, 4, 1])
    reply += modbus(reply)
    run_async(strip._on_status_char_update(None, bytearray(reply)))
    assert getattr(strip, state) == value
    assert getattr(strip, pending) is None
    assert changes == [value]
    if command == 0x12:
        assert strip.color is None
    if command == 0x15:
        assert strip.effect is None


@pytest.mark.parametrize("command", [0x11, 0x12, 0x13, 0x15, 0x99])
def test_ack_without_pending_command_does_not_notify(run_async, command):
    strip = DaybetterLedStrip("device")
    changes = []
    strip.on_change(lambda: changes.append(True))
    reply = bytes([0xA1, command, 4, 1])
    reply += modbus(reply)
    run_async(strip._on_status_char_update(None, bytearray(reply)))
    assert changes == []


@pytest.mark.parametrize(
    "reply", [b"", b"\xa1", b"\xa1\x15\x04", b"\x00\x15\x04\x01", b"\xa1\x15\x04\x00"]
)
def test_short_wrong_direction_and_failed_ack_do_not_commit(run_async, reply):
    strip = DaybetterLedStrip("device")
    strip.pending_color = (255, 0, 0)
    run_async(strip._on_status_char_update(None, bytearray(reply)))
    assert strip.color is None
    assert strip.pending_color == (255, 0, 0)


@pytest.mark.parametrize("power", [False, True])
def test_remote_status_updates_power(run_async, power):
    strip = DaybetterLedStrip("device")
    # Captured P065 status: change only its power field for these parser cases.
    raw = bytearray.fromhex("a1 10 11 01 14 ff 64 32 32 ff 00 00 00 00 00 00 00 aa a3")
    raw[3] = int(power)
    raw[-2:] = modbus(raw[:-2])
    seen = []
    strip.on_change(lambda: seen.append(strip.power))
    run_async(strip._on_status_char_update(None, raw))
    assert strip.power is power
    assert seen == [power]


def test_listener_failure_does_not_block_other_listeners(caplog):
    strip = DaybetterLedStrip("device")
    seen = []

    def broken():
        raise ValueError("listener failed")

    strip.on_change(broken)
    unsubscribe = strip.on_change(lambda: seen.append(True))
    strip._trigger_listeners()
    unsubscribe()
    strip._trigger_listeners()
    assert seen == [True]
    assert "listener failed" in caplog.text


def test_model_and_rssi_use_discovery_data(run_async, monkeypatch):
    strip = DaybetterLedStrip("device")
    assert strip.model == "P031"
    assert strip.rssi is None
    connect = AsyncMock()
    monkeypatch.setattr(strip, "connect", connect)
    data = advertisement(name="p065_test")
    run_async(strip.update_device(BLEDevice("device", None, {}), data))
    assert strip.model == "P065"
    assert strip.rssi == -66


def test_update_without_device_and_address_mismatch(run_async, monkeypatch, caplog):
    strip = DaybetterLedStrip("device")
    monkeypatch.setattr(strip, "connect", AsyncMock())
    run_async(strip.update_device(None, None))
    assert strip.device is None
    run_async(strip.update_device(BLEDevice("other", "P031_test", {}), None))
    assert "does not match" in caplog.text


def test_connect_without_device_and_redundant_connect_are_noops(
    run_async, monkeypatch, connected
):
    factory = AsyncMock()
    monkeypatch.setattr(led_strip, "establish_connection", factory)
    run_async(DaybetterLedStrip("device").connect())
    strip, client = connected
    strip.device = BLEDevice("device", "P031_test", {})
    run_async(strip.connect())
    assert client.writes == []
    factory.assert_not_awaited()


def test_connection_failure_is_logged_and_cleared(run_async, monkeypatch, caplog):
    strip = DaybetterLedStrip("device")
    monkeypatch.setattr(
        led_strip,
        "establish_connection",
        AsyncMock(side_effect=BleakError("unreachable")),
    )
    run_async(strip.update_device(BLEDevice("device", None, {}), None))
    assert not strip.connected
    assert strip.client is None
    assert "unreachable" in caplog.text


def test_disconnect_without_client_or_with_disconnected_transport(run_async):
    strip = DaybetterLedStrip("device")
    run_async(strip.disconnect())
    client = FakeClient()
    client.is_connected = False
    strip.client = client
    run_async(strip.disconnect())
    assert strip.client is None
    assert client.stopped == []


def test_stop_notify_failure_still_disconnects(run_async, connected):
    strip, client = connected
    strip._notifying = True
    client.stop_notify = AsyncMock(side_effect=BleakError("stop failed"))
    with pytest.raises(BleakError, match="stop failed"):
        run_async(strip.disconnect())
    assert not client.is_connected
    assert strip.client is None


def test_handshake_cancellation_cleans_up_and_propagates(run_async, monkeypatch):
    async def scenario():
        client = FakeClient(challenge="missing")
        ready = asyncio.Event()
        original_write = client.write_gatt_char

        async def write(*args, **kwargs):
            await original_write(*args, **kwargs)
            ready.set()

        client.write_gatt_char = write
        factory = AsyncMock(return_value=client)
        monkeypatch.setattr(led_strip, "establish_connection", factory)
        strip = DaybetterLedStrip("device")
        task = asyncio.create_task(
            strip.update_device(BLEDevice("device", "P065_test", {}), None)
        )
        await ready.wait()
        assert not strip.connected
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert strip.client is None
        assert not client.is_connected
        assert strip._handshake_reply is None

    run_async(scenario())


def test_malformed_handshake_challenge_is_rejected(run_async, monkeypatch):
    async def scenario():
        client = FakeClient()

        async def write(uuid, data, **kwargs):
            raw = b"\xa1\x00\x0aNOTIT\x14\x0b"
            await client.callback(None, bytearray(raw + modbus(raw)))

        client.write_gatt_char = write
        monkeypatch.setattr(
            led_strip, "establish_connection", AsyncMock(return_value=client)
        )
        strip = DaybetterLedStrip("device")
        with pytest.raises(BleakError, match="Invalid Daybetter"):
            await strip.update_device(BLEDevice("device", "P065_test", {}), None)
        assert strip.client is None
        assert not client.is_connected

    run_async(scenario())


def test_handshake_write_error_cleans_up_pending_future(run_async, monkeypatch):
    async def scenario():
        client = FakeClient()
        client.write_gatt_char = AsyncMock(side_effect=BleakError("GATT write failed"))
        monkeypatch.setattr(
            led_strip, "establish_connection", AsyncMock(return_value=client)
        )
        strip = DaybetterLedStrip("device")
        with pytest.raises(BleakError, match="GATT write failed"):
            await strip.update_device(BLEDevice("device", "P065_test", {}), None)
        assert strip._handshake_reply is None
        assert not client.is_connected

    run_async(scenario())
