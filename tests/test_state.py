"""Offline snapshots and refresh lifecycle, using full protocol frames."""

import asyncio
from unittest.mock import AsyncMock

import pytest
from bleak.exc import BleakError

from daybetter_ble_client import DaybetterLedStrip, led_strip
from daybetter_ble_client.const import P031, P065, Effect
from daybetter_ble_client.util import modbus
from tests.devices import make_device
from tests.test_led_strip import FakeClient

# P065 capture used by the earlier power-only test: FADE_RED_GREEN, 100%.
EFFECT_STATUS = bytes.fromhex(
    "a1 10 11 01 14 ff 64 32 32 ff 00 00 00 00 00 00 00 aa a3"
)


def status(*, power=1, effect=1, brightness=50, rgb=(17, 34, 51)):
    """Synthetic variations of the documented 14-byte status payload."""
    body = bytes([0xA1, 0x10, 0x11, power, effect, 0xFF, brightness, 50, 50])
    body += bytes(rgb) + bytes(5)
    return bytearray(body + modbus(body))


@pytest.mark.parametrize("profile", [P031, P065])
def test_snapshot_updates_all_fields_once(run_async, profile):
    async def scenario():
        strip = DaybetterLedStrip("device")
        strip._profile = profile
        seen = []
        strip.on_change(
            lambda: seen.append((strip.power, strip.brightness, strip.color))
        )
        raw = status(power=0)
        await strip._on_status_char_update(None, raw)
        assert seen == [(False, 50, (17, 34, 51))]
        assert strip.effect is None
        assert strip.effect_id == 1
        assert strip.raw_status == bytes(raw[3:-2])
        assert strip.last_state_update is not None
        before = strip.last_state_update
        await strip._on_status_char_update(None, bytearray(EFFECT_STATUS))
        assert strip.effect == Effect.FADE_RED_GREEN
        assert strip.effect_id == 0x14
        assert strip.brightness == 100
        assert strip.color is None
        assert strip.last_state_update >= before
        await strip._on_status_char_update(None, status(effect=0xD3))
        assert strip.effect is None
        assert strip.effect_id == 0xD3
        assert strip.color is None

    run_async(scenario())


@pytest.mark.parametrize(
    "kind", ["crc", "length", "direction", "short", "power", "brightness"]
)
def test_invalid_status_never_changes_state(run_async, kind):
    async def scenario():
        strip = DaybetterLedStrip("device")
        seen = []
        strip.on_change(lambda: seen.append(True))
        raw = status()
        if kind == "crc":
            raw[-1] ^= 1
        elif kind == "length":
            raw[2] -= 1
            raw[-2:] = modbus(raw[:-2])
        elif kind == "direction":
            raw[0] = 0xA0
            raw[-2:] = modbus(raw[:-2])
        elif kind == "short":
            raw = bytearray.fromhex("a1 10 04 01")
            raw += modbus(raw)
        elif kind == "power":
            raw = status(power=2)
        else:
            raw = status(brightness=101)
        await strip._on_status_char_update(None, raw)
        assert strip.power is None
        assert strip.last_state_update is None
        assert seen == []

    run_async(scenario())


def test_corrupt_ack_does_not_commit_pending_state(run_async):
    strip = DaybetterLedStrip("device")
    strip.pending_power = True
    run_async(
        strip._on_status_char_update(None, bytearray.fromhex("a1 11 04 01 00 00"))
    )
    assert strip.power is None


def test_state_is_initialized_per_instance(run_async):
    async def scenario():
        one = DaybetterLedStrip("one")
        await one._on_status_char_update(None, status())
        one.pending_power = True
        two = DaybetterLedStrip("two")
        assert two.power is two.brightness is two.color is two.effect is None
        assert two.pending_power is None
        assert two.raw_status is two.last_state_update is None

    run_async(scenario())


@pytest.mark.parametrize("profile", [P031, P065])
def test_connect_obtains_initial_state_and_refresh_reads_again(
    run_async, monkeypatch, profile
):
    async def scenario():
        strip = DaybetterLedStrip("device")
        client = FakeClient()
        factory = AsyncMock(return_value=client)
        monkeypatch.setattr(led_strip, "establish_connection", factory)
        await strip.update_device(
            make_device("device", profile.model + "_test", {}), None
        )
        assert strip.power is True
        assert strip.brightness == 100
        assert strip.color == (255, 0, 0)
        assert client.writes[-1][0] == profile.write_characteristic
        assert client.writes[-1][1][:-2] == bytes.fromhex("a0 10 04 00")
        before = strip.last_state_update
        await strip.async_refresh_state()
        assert strip.last_state_update >= before
        await strip.disconnect()

    run_async(scenario())


def attached():
    strip = DaybetterLedStrip("device")
    client = FakeClient()
    strip.client = client
    client.callback = strip._on_status_char_update
    client.disconnected_callback = strip._on_disconnected
    return strip, client


def test_refresh_requires_connection(run_async):
    with pytest.raises(BleakError, match="not connected"):
        run_async(DaybetterLedStrip("device").async_refresh_state())


def test_refresh_raises_disconnect_cause_from_callback(run_async):
    async def scenario():
        strip, client = attached()
        cause = BleakError("remote disconnect")
        started = asyncio.Event()

        async def write(*_args, **_kwargs):
            started.set()
            await asyncio.Event().wait()

        client.write_gatt_char = write
        refresh = asyncio.create_task(strip.async_refresh_state())
        await started.wait()
        client.disconnected_callback(client, cause)
        with pytest.raises(BleakError) as raised:
            await refresh
        assert raised.value is cause
        assert strip.disconnect_reason is cause

    run_async(scenario())


def test_refresh_preserves_gatt_write_exception(run_async):
    async def scenario():
        strip, client = attached()
        cause = BleakError("GATT write failed")

        async def write(*_args, **_kwargs):
            raise cause

        client.write_gatt_char = write
        with pytest.raises(BleakError) as raised:
            await strip.async_refresh_state()
        assert raised.value is cause

    run_async(scenario())


def test_disconnect_callback_cause_is_available_without_pending_refresh():
    strip, client = attached()
    cause = BleakError("transport disconnected")

    strip._on_disconnected(client, cause)

    assert strip.disconnect_reason is cause


@pytest.mark.parametrize("failure", ["missing", "stalled", "write", "corrupt"])
def test_refresh_failure_propagates_and_allows_retry(run_async, failure):
    async def scenario():
        strip, client = attached()
        original = client.write_gatt_char

        async def write(uuid, data, **kwargs):
            if failure == "write":
                raise BleakError("write failed")
            if failure == "stalled":
                await asyncio.Event().wait()
            if failure == "corrupt":
                raw = status()
                raw[-1] ^= 1
                await client.callback(None, raw)

        client.write_gatt_char = write
        with pytest.raises(BleakError if failure == "write" else TimeoutError):
            await strip.async_refresh_state(timeout=0.01)
        assert strip.last_state_update is None
        client.write_gatt_char = original
        await strip.async_refresh_state()
        assert strip.power is True

    run_async(scenario())


@pytest.mark.parametrize(
    "reason", ["cancel", "manual", "remote", "remote_stalled", "after_response"]
)
def test_interrupted_refresh_cleans_up_and_releases_command_lock(run_async, reason):
    async def scenario():
        strip, client = attached()
        started = asyncio.Event()
        original = client.write_gatt_char

        async def write(uuid, data, **kwargs):
            if reason == "after_response":
                await client.callback(None, status())
            started.set()
            if reason in ("remote_stalled", "after_response"):
                await asyncio.Event().wait()

        client.write_gatt_char = write
        task = asyncio.create_task(strip.async_refresh_state())
        await started.wait()
        if reason == "cancel":
            task.cancel()
        elif reason == "manual":
            await strip.disconnect()
        else:
            await client.disconnect()
        with pytest.raises(
            asyncio.CancelledError if reason == "cancel" else BleakError
        ):
            await asyncio.wait_for(task, 0.5)
        if reason == "cancel":
            client.write_gatt_char = original
            await strip.async_refresh_state()
            await strip.set_power(False)
            assert client.writes[-1][1][1] == 0x11
        else:
            assert not strip.connected
            assert strip.pending_power is None

    run_async(scenario())


def test_deferred_refresh_write_cannot_reach_replacement_connection(run_async):
    async def scenario():
        strip, old = attached()
        new = FakeClient()

        async def replace():
            await strip.disconnect()
            strip.client = new

        read = asyncio.create_task(strip.async_refresh_state())
        replacement = asyncio.create_task(replace())
        with pytest.raises(BleakError):
            await read
        await replacement
        assert old.writes == new.writes == []

    run_async(scenario())


def test_overlapping_refreshes_and_commands_are_serialized(run_async):
    async def scenario():
        strip, client = attached()
        started = asyncio.Event()
        second_started = asyncio.Event()
        second_written = asyncio.Event()
        commands = []

        async def write(uuid, data, **kwargs):
            commands.append(data[1])
            if len(commands) == 1:
                started.set()
            if len(commands) == 2:
                second_written.set()

        client.write_gatt_char = write
        first = asyncio.create_task(strip.async_refresh_state())
        await started.wait()

        async def second_read():
            second_started.set()
            await strip.async_refresh_state()

        second = asyncio.create_task(second_read())
        await second_started.wait()
        command = asyncio.create_task(strip.set_power(False))
        await client.callback(None, status())
        await first
        # Second read owns the lock until its own response, not the first's.
        await second_written.wait()
        assert commands == [0x10, 0x10]
        assert not second.done()
        await client.callback(None, status(power=0))
        await asyncio.gather(second, command)
        assert commands == [0x10, 0x10, 0x11]
        assert strip.power is False

    run_async(scenario())


def test_snapshot_supersedes_late_ack_for_an_older_command(run_async):
    async def scenario():
        strip, client = attached()
        await strip.set_brightness(20)
        await strip._on_status_char_update(None, status(brightness=50))
        ack = bytes.fromhex("a1 13 04 01")
        await strip._on_status_char_update(None, bytearray(ack + modbus(ack)))
        assert strip.brightness == 50
        assert strip.pending_brightness is None

    run_async(scenario())


def test_initial_refresh_failure_disconnects(run_async, monkeypatch):
    async def scenario():
        client = FakeClient()
        original = client.write_gatt_char

        async def write(uuid, data, **kwargs):
            if data[1] == 0x10:
                raise BleakError("status read failed")
            await original(uuid, data, **kwargs)

        client.write_gatt_char = write
        monkeypatch.setattr(
            led_strip, "establish_connection", AsyncMock(return_value=client)
        )
        strip = DaybetterLedStrip("device")
        with pytest.raises(BleakError, match="status read failed"):
            await strip.update_device(make_device("device", "P065_test", {}), None)
        assert not strip.connected
        assert not client.is_connected

    run_async(scenario())


def test_reconnect_ignores_old_notifications_and_clears_pending_commands(
    run_async, monkeypatch
):
    async def scenario():
        strip = DaybetterLedStrip("device")
        old = FakeClient()
        monkeypatch.setattr(
            led_strip, "establish_connection", AsyncMock(return_value=old)
        )
        await strip.update_device(make_device("device", "P031_test", {}), None)
        await strip.set_brightness(20)
        assert strip.pending_brightness == 20
        await strip.disconnect()
        assert strip.pending_brightness is None
        new = FakeClient()
        monkeypatch.setattr(
            led_strip, "establish_connection", AsyncMock(return_value=new)
        )
        await strip.connect()
        await old.callback(None, status(power=0, brightness=1))
        assert strip.power is True
        assert strip.brightness == 100

    run_async(scenario())
