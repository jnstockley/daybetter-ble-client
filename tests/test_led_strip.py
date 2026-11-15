"""Protocol boundary tests; no Bluetooth adapter required."""
import asyncio
import unittest
from unittest.mock import patch

from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData
from bleak.exc import BleakError

from daybetter_led_strip import DaybetterLedStrip
from daybetter_led_strip import const

P031_WRITE = '0000a031-0000-1000-8000-00805f9b34fb'
P065_WRITE = '0000a065-0000-1000-8000-00805f9b34fb'
P065_STATUS = '0000f065-0000-1000-8000-00805f9b34fb'
P065_SERVICE = '0000e065-0000-1000-8000-00805f9b34fb'
P065_DISCOVERY = '0000c065-0000-1000-8000-00805f9b34fb'


class FakeClient:
    """Only replace the external BLE transport; use captured hardware replies."""
    def __init__(self, challenge='valid', auth='valid', notify_error=False):
        self.is_connected = True
        self.writes = []
        self.notify_uuid = None
        self.stopped = []
        self.callback = None
        self.challenge = challenge
        self.auth = auth
        self.notify_error = notify_error
        self.disconnected_callback = None

    async def start_notify(self, uuid, callback):
        if self.notify_error:
            raise BleakError('notifications unavailable')
        self.notify_uuid = uuid
        self.callback = callback

    async def stop_notify(self, uuid):
        self.stopped.append(uuid)

    async def disconnect(self):
        self.is_connected = False
        if self.disconnected_callback:
            self.disconnected_callback(self)

    async def write_gatt_char(self, uuid, data, **kwargs):
        self.writes.append((uuid, bytes(data)))
        if data[1] == 0:
            replies = {
                'valid': 'a1 00 0a 43 43 48 49 50 14 0b 63 8c',
                'corrupt': 'a1 00 0a 43 43 48 49 50 14 0b 00 00',
                'truncated': 'a1 00 0a 43',
            }
            if self.challenge == 'disconnect':
                await self.disconnect()
                return
            reply = replies.get(self.challenge)
        elif data[1] == 1:
            reply = ('a1 01 09 43 00 00 00 00 01 68 98' if self.auth == 'valid'
                     else 'a1 01 09 43 43 48 49 50 00 16 e1')
        else:
            reply = None
        if reply:
            await self.callback(None, bytearray.fromhex(reply))


def advertisement(*services, name=None):
    return AdvertisementData(name, {}, {}, list(services), None, -66, ())


class StripTests(unittest.IsolatedAsyncioTestCase):
    async def attach(self, name='P065_fc58', adv=None, client=None):
        strip = DaybetterLedStrip('test-address')
        client = client or FakeClient()
        self.options = None
        async def establish(*args, **kwargs):
            self.options = kwargs
            client.disconnected_callback = kwargs.get('disconnected_callback')
            return client
        with patch('daybetter_led_strip.led_strip.establish_connection', establish):
            await strip.update_device(BLEDevice('test-address', name, {}), adv)
        return strip, client

    async def test_p031_default_retains_original_red_packet(self):
        strip, client = await self.attach(name='Unknown')
        await strip.set_color((255, 0, 0))
        self.assertEqual(client.writes, [(P031_WRITE, bytes.fromhex('a0 15 06 ff 00 00 25 c0'))])
        await strip.disconnect()

    async def test_p065_detected_from_name_and_uses_its_services(self):
        strip, client = await self.attach()
        self.assertIn(P065_SERVICE, self.options['services'])
        self.assertEqual(client.notify_uuid, P065_STATUS)
        self.assertTrue(strip.connected)
        await strip.disconnect()
        self.assertEqual(client.stopped, [P065_STATUS])
        self.assertFalse(strip.connected)

    async def test_advertised_service_overrides_conflicting_name(self):
        strip, client = await self.attach(name='P031_wrong', adv=advertisement(P065_DISCOVERY))
        await strip.set_power(True)
        self.assertEqual(client.writes[-1][0], P065_WRITE)
        await strip.disconnect()

    async def test_both_models_can_be_discovered_with_public_services(self):
        services = getattr(const, 'SUPPORTED_DISCOVERY_SERVICES', ())
        self.assertIn(const.SERVICE_DISCOVERY, services)
        self.assertIn(P065_DISCOVERY, services)

    async def test_listeners_are_isolated_between_strips(self):
        one = DaybetterLedStrip('one')
        two = DaybetterLedStrip('two')
        calls = []
        remove = one.on_change(lambda: calls.append('one'))
        try:
            two._trigger_listeners()
            self.assertEqual(calls, [])
        finally:
            remove()

    async def test_p065_echoes_device_challenge_before_color(self):
        strip, client = await self.attach()
        await strip.set_color((255, 0, 0))
        self.assertEqual(client.writes, [
            (P065_WRITE, bytes.fromhex('a0 00 08 43 43 48 49 50 ac ca')),
            (P065_WRITE, bytes.fromhex('a0 01 0a 43 43 48 49 50 14 0b 3f d9')),
            (P065_WRITE, bytes.fromhex('a0 15 07 ff 00 00 ff 7c 5b')),
        ])
        await strip.disconnect()

    async def test_p065_effect_uses_variant_byte(self):
        strip, client = await self.attach()
        await strip.set_effect(const.Effect.FADE_RED_GREEN)
        # Independently recorded protocol format: preset id followed by variant.
        self.assertEqual(client.writes[-1][1][3:-2], b'\x14\xff')
        await strip.disconnect()

    async def test_rejected_authentication_disconnects_and_raises(self):
        client = FakeClient(auth='rejected')
        with self.assertRaises(BleakError):
            await self.attach(client=client)
        self.assertFalse(client.is_connected)
        self.assertEqual([p[1] for _, p in client.writes], [0, 1])

    async def test_invalid_or_missing_challenge_times_out_and_disconnects(self):
        for kind in ('corrupt', 'truncated', 'missing'):
            with self.subTest(kind=kind):
                client = FakeClient(challenge=kind)
                with patch('daybetter_led_strip.led_strip.HANDSHAKE_TIMEOUT', 0.01, create=True):
                    with self.assertRaises((BleakError, TimeoutError)):
                        await self.attach(client=client)
                self.assertFalse(client.is_connected)
                self.assertEqual(len(client.writes), 1)

    async def test_disconnect_during_handshake_fails_promptly(self):
        client = FakeClient(challenge='disconnect')
        with self.assertRaises(BleakError):
            await self.attach(client=client)
        self.assertFalse(client.is_connected)

    async def test_notification_failure_cleans_up_connection(self):
        client = FakeClient(notify_error=True)
        with self.assertRaises(BleakError):
            await self.attach(client=client)
        self.assertFalse(client.is_connected)

    async def test_update_of_connected_device_reconnects_and_authenticates(self):
        strip, old = await self.attach()
        new = FakeClient()
        async def establish(*args, **kwargs):
            new.disconnected_callback = kwargs['disconnected_callback']
            return new
        with patch('daybetter_led_strip.led_strip.establish_connection', establish):
            await strip.update_device(BLEDevice('test-address', 'P065_fc58', {}), None)
        self.assertFalse(old.is_connected)
        self.assertTrue(strip.connected)
        self.assertEqual([p[1] for _, p in new.writes], [0, 1])
        await strip.disconnect()


    async def test_handshake_timeout_includes_stalled_write(self):
        client = FakeClient()
        started = asyncio.Event()
        original_write = client.write_gatt_char
        async def stalled_write(uuid, data, **kwargs):
            if data[1] == 0:
                started.set()
                await asyncio.Event().wait()
            await original_write(uuid, data, **kwargs)
        client.write_gatt_char = stalled_write
        with patch('daybetter_led_strip.led_strip.HANDSHAKE_TIMEOUT', 0.01):
            task = asyncio.create_task(self.attach(client=client))
            await started.wait()
            await asyncio.sleep(0.03)
            completed = task.done()
            if not completed:
                task.cancel()
            try:
                await task
            except (TimeoutError, asyncio.CancelledError):
                pass
        self.assertTrue(completed, 'Handshake write must share the response deadline')
        self.assertFalse(client.is_connected)

    async def test_late_disconnect_of_old_client_does_not_clear_new_connection(self):
        strip, old = await self.attach()
        new = FakeClient()
        async def establish(*args, **kwargs):
            new.disconnected_callback = kwargs['disconnected_callback']
            return new
        with patch('daybetter_led_strip.led_strip.establish_connection', establish):
            await strip.update_device(BLEDevice('test-address', 'P065_fc58', {}), None)
        old.disconnected_callback(old)
        self.assertTrue(strip.connected, 'Stale callback must not discard the new connection')
        await strip.disconnect()
        self.assertFalse(new.is_connected)

    async def test_manual_disconnect_notifies_even_when_callback_is_delayed(self):
        strip, client = await self.attach()
        states = []
        strip.on_change(lambda: states.append(strip.connected))
        async def delayed_disconnect():
            client.is_connected = False
        client.disconnect = delayed_disconnect
        await strip.disconnect()
        self.assertEqual(states, [False])
        client.disconnected_callback(client)
        self.assertEqual(states, [False])


if __name__ == '__main__':
    unittest.main()
