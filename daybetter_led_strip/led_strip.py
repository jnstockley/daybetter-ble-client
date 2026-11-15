import asyncio
import logging
from typing import cast, Callable

from bleak import BleakClient
from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.scanner import AdvertisementData
from bleak.backends.device import BLEDevice
from bleak.exc import BleakError
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection

from .const import (
    COMMAND_BRIGHTNESS,
    COMMAND_COLOR,
    COMMAND_EFFECT,
    COMMAND_POWER,
    DEVICE_PROFILES,
    P031,
    SERVICE_GENERIC_ACCESS_PROFILE,
    Effect,
)
from .util import correct_color, modbus, RgbColor

_LOGGER = logging.getLogger(__name__)

Listener = Callable[[], None]
HANDSHAKE_TIMEOUT = 5.0

class DaybetterLedStrip:
    """Control a Daybetter RGB LED strip over Bluetooth Low Energy. Uses a BleakClient for the BLE connection"""

    address: str
    device: BLEDevice | None = None
    advertisment_data: AdvertisementData | None = None
    client: BleakClient | None = None

    # pending state changes sent via command
    pending_power: bool | None = None
    pending_color: RgbColor | None = None
    pending_brightness: int | None = None
    pending_effect: Effect | None = None

    # current state
    power: bool | None = None
    color: RgbColor | None = None
    brightness: int | None = None
    effect: Effect | None = None

    listeners: list[Listener]

    def __init__(self, address: str):
        self.address = address
        self.listeners = []
        self._profile = P031
        self._authenticated = False
        self._notifying = False
        self._handshake_reply: asyncio.Future[bytes] | None = None
        self._handshake_command: int | None = None

    @property
    def model(self) -> str:
        """Detected model; defaults to P031 until identifying data is available."""
        return self._profile.model

    async def update_device(self, device: BLEDevice | None, advertisment_data: AdvertisementData | None):
        """Update this client with a new BLEDevice and AdvertismentData from scanning. Will attempt to connect if applicable"""

        if device is not None and device.address != self.address:
            _LOGGER.warning("Updated device address %s does not match original address %s", device.address, self.address)

        if self.client is not None:
            await self.disconnect()

        self.device = device
        self.advertisment_data = advertisment_data

        services = {s.lower() for s in advertisment_data.service_uuids} if advertisment_data else set()
        profile = next((p for p in DEVICE_PROFILES if p.discovery_service in services), None)
        if profile is None:
            name = (advertisment_data.local_name if advertisment_data else None) or (device.name if device else None) or ""
            profile = next((p for p in DEVICE_PROFILES if name.upper().startswith(p.model + "_")), None)
        if profile is not None:
            self._profile = profile

        # attempt reconnect with new device
        if device is not None:
            await self.connect()

        self._trigger_listeners()

    async def connect(self):
        """Initialize the BleakClient"""

        if self.device is None:
            return
        if self.connected:
            return
        self._authenticated = False

        try:
            self.client = await establish_connection(
                BleakClientWithServiceCache,
                self.device,
                self.device.name or "Unknown Device",
                disconnected_callback=self._on_disconnected,
                services=[SERVICE_GENERIC_ACCESS_PROFILE, self._profile.control_service],
            )
        except Exception:
            _LOGGER.exception("Could not connect to %s", self.address)
            self.client = None
            return
        try:
            await self.client.start_notify(self._profile.status_characteristic, self._on_status_char_update)
            self._notifying = True
            if self._profile.requires_handshake:
                await self._authenticate()
        except BaseException:
            await self.disconnect()
            raise

    async def _handshake_exchange(self, command: int, payload: bytes) -> bytes:
        self._handshake_command = command
        reply: asyncio.Future[bytes] = asyncio.get_running_loop().create_future()
        self._handshake_reply = reply

        async def exchange():
            await self._write_packet(command, payload)
            return await reply

        try:
            return await asyncio.wait_for(exchange(), HANDSHAKE_TIMEOUT)
        finally:
            if not reply.done():
                reply.cancel()
            elif not reply.cancelled():
                reply.exception()  # consume a disconnect error if the write itself failed
            self._handshake_reply = None
            self._handshake_command = None

    async def _authenticate(self):
        challenge = await self._handshake_exchange(0x00, b"CCHIP")
        if len(challenge) != 7 or not challenge.startswith(b"CCHIP"):
            raise BleakError("Invalid Daybetter handshake challenge")
        response = await self._handshake_exchange(0x01, challenge)
        # The P065 success reply is 43 00 00 00 00 01; it does not echo CCHIP.
        if len(response) != 6 or response[-1] != 1:
            raise BleakError("Daybetter handshake rejected")
        self._authenticated = True

    async def disconnect(self):
        """Manually disconnect the BleakClient"""

        if self.client is None:
            return

        client = self.client
        try:
            if client.is_connected:
                try:
                    if self._notifying:
                        await client.stop_notify(self._profile.status_characteristic)
                finally:
                    await client.disconnect()
        finally:
            notify_listeners = self.client is client
            self.client = None
            self._authenticated = False
            self._notifying = False
            if notify_listeners:
                self._trigger_listeners()

    async def _write_led_control(self, command: int, payload: bytes):
        """Write the given payload to the LED control characteristic.
        Prepends the header and appends checksum to the payload.
        """
        if not self.connected:
            _LOGGER.warning("Cannot write characteristic: not connected to device")
            return

        try:
            await self._write_packet(command, payload)
        except BleakError as e:
            _LOGGER.error("Failed to write characteristic: %s", e)

    async def _write_packet(self, command: int, payload: bytes):
        # leading byte + command + length + payload + checksum not included
        length = 3 + len(payload)
        full_payload = bytes([0xA0, command & 0xff, length & 0xff]) + payload
        full_payload += modbus(full_payload)  # checksum

        await cast(BleakClient, self.client).write_gatt_char(
            self._profile.write_characteristic, full_payload, response=True
        )

    async def set_color(self, new_color: RgbColor, color_correction = True):
        """Attempt to configure the current color of the lights. Will not turn on if currently off"""

        r, g, b = new_color
        if color_correction:
            r, g, b = correct_color(new_color)
        # RR GG BB
        payload = bytes([r & 0xFF, g & 0xFF, b & 0xFF]) + self._profile.variant

        # will be committed to self.color when acked
        self.pending_color = new_color
        await self._write_led_control(COMMAND_COLOR, payload)

    async def set_brightness(self, new_brightness: int):
        """Attempt to configure the brightness of the lights. Value should be between 0 and 100 (0x00 and 0x64)."""
        if not (0 <= new_brightness <= 100):
            _LOGGER.warning("Brightness value %d out of range (0-100)", new_brightness)
            return

        # between 00 and 64
        payload = bytes([new_brightness & 0xFF])
        # will be committed to self.brightness when acked
        self.pending_brightness = new_brightness
        await self._write_led_control(COMMAND_BRIGHTNESS, payload)

    async def set_effect(self, effect: Effect):
        """Attempt to put the light into one of the preset effect modes."""
        payload = bytes([effect.value & 0xff]) + self._profile.variant
        self.pending_effect = effect
        await self._write_led_control(COMMAND_EFFECT, payload)

    async def set_power(self, on: bool):
        """Attempt to turn the lights on or off."""
        # 00 = off, 01 = on
        payload = bytes([0x01 if on else 0x00])
        # will be committed to self.power when acked
        self.pending_power = on
        await self._write_led_control(COMMAND_POWER, payload)

    async def _on_status_char_update(self, _char: BleakGATTCharacteristic, data: bytearray):
        if self._handshake_reply is not None and not self._handshake_reply.done():
            if (len(data) >= 5 and data[0] == 0xA1
                    and data[1] == self._handshake_command
                    and len(data) == data[2] + 2
                    and modbus(data[:-2]) == data[-2:]):
                self._handshake_reply.set_result(bytes(data[3:-2]))
            return
        # power change - sent when changed from IR remote
        # A1 10 11 [00|01] CRC
        if len(data) >= 4 and data[0] == 0xA1 and data[1] == 0x10 and data[2] == 0x11:
            self.power = data[3] == 0x01
            self._trigger_listeners()

        # ack - sent after we send a command - change state and trigger listeners
        # A1 XX 04 01 CRC
        if len(data) >= 4 and data[0] == 0xA1 and data[3] == 0x01:
            if data[1] == COMMAND_POWER:
                # Commit pending power
                if self.pending_power is not None:
                    self.power = self.pending_power
                    self.pending_power = None
                    self._trigger_listeners()
            elif data[1] == COMMAND_EFFECT:
                # Commit pending effect
                if self.pending_effect is not None:
                    self.effect = self.pending_effect
                    self.pending_effect = None
                    # effect clears color
                    self.color = None
                    self._trigger_listeners()
            elif data[1] == COMMAND_BRIGHTNESS:
                # Commit pending brightness
                if self.pending_brightness is not None:
                    self.brightness = self.pending_brightness
                    self.pending_brightness = None
                    self._trigger_listeners()
            elif data[1] == COMMAND_COLOR:
                # Commit pending color
                if self.pending_color is not None:
                    self.color = self.pending_color
                    self.pending_color = None
                    # color clears effect
                    self.effect = None
                    self._trigger_listeners()

    def _on_disconnected(self, _old_client: BleakClient):
        if self.client is not _old_client:
            return
        _LOGGER.warning("Device disconnected")

        # not async - can't do much here
        self.client = None
        self._authenticated = False
        self._notifying = False
        if self._handshake_reply is not None and not self._handshake_reply.done():
            self._handshake_reply.set_exception(BleakError("Disconnected during Daybetter handshake"))
        self._trigger_listeners()

    def on_change(self, listener: Listener):
        """Add an event listener for device state change"""

        self.listeners.append(listener)

        return lambda: self.listeners.remove(listener)

    def _trigger_listeners(self):
        """Call all registered event listeners."""
        for listener in list(self.listeners):
            try:
                listener()
            except Exception as e:
                _LOGGER.error("Listener raised exception: %s", e)

    @property
    def connected(self) -> bool:
        return (self.client is not None and self.client.is_connected
                and (not self._profile.requires_handshake or self._authenticated))

    @property
    def rssi(self) -> int | None:
        if self.advertisment_data is None:
            return None
        return self.advertisment_data.rssi
