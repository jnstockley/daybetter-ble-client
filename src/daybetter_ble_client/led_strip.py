import asyncio
import logging
from typing import Callable

from bleak import BleakClient
from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData
from bleak.exc import BleakError
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection

from .const import (
    COMMAND_BRIGHTNESS,
    COMMAND_COLOR,
    COMMAND_EFFECT,
    COMMAND_POWER,
    COMMAND_STATUS,
    DEVICE_PROFILES,
    P031,
    SERVICE_GENERIC_ACCESS_PROFILE,
    Effect,
)
from .util import RgbColor, correct_color, modbus

_LOGGER = logging.getLogger(__name__)

Listener = Callable[[], None]
HANDSHAKE_TIMEOUT = 5.0
STATE_TIMEOUT = 5.0


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
        self.device = None
        self.advertisment_data = None
        self.client = None
        self.power = None
        self.color = None
        self.brightness = None
        self.effect = None
        self.pending_power = None
        self.pending_color = None
        self.pending_brightness = None
        self.pending_effect = None
        self.effect_id: int | None = None
        self.raw_status: bytes | None = None
        self.last_state_update: float | None = None
        self.listeners = []
        self._profile = P031
        self._authenticated = False
        self._notifying = False
        self._handshake_reply: asyncio.Future[bytes] | None = None
        self._handshake_command: int | None = None
        self._status_reply: asyncio.Future[None] | None = None
        self._status_disconnected: asyncio.Future[None] | None = None
        self._operation_lock = asyncio.Lock()
        self._connect_lock = asyncio.Lock()

    @property
    def model(self) -> str:
        """Detected model; defaults to P031 until identifying data is available."""
        return self._profile.model

    async def update_device(
        self, device: BLEDevice | None, advertisment_data: AdvertisementData | None
    ):
        """Update this client with a new BLEDevice and AdvertismentData from scanning. Will attempt to connect if applicable"""

        if device is not None and device.address != self.address:
            _LOGGER.warning(
                "Updated device address %s does not match original address %s",
                device.address,
                self.address,
            )

        if self.client is not None:
            await self.disconnect()

        self.device = device
        self.advertisment_data = advertisment_data

        services = (
            {s.lower() for s in advertisment_data.service_uuids}
            if advertisment_data
            else set()
        )
        profile = next(
            (p for p in DEVICE_PROFILES if p.discovery_service in services), None
        )
        if profile is None:
            name = (
                (advertisment_data.local_name if advertisment_data else None)
                or (device.name if device else None)
                or ""
            )
            profile = next(
                (p for p in DEVICE_PROFILES if name.upper().startswith(p.model + "_")),
                None,
            )
        if profile is not None:
            self._profile = profile

        # attempt reconnect with new device
        if device is not None:
            await self.connect()

        self._trigger_listeners()

    async def connect(self):
        """Connect, authenticate if necessary, and obtain an initial snapshot."""
        async with self._connect_lock:
            await self._connect()

    async def _connect(self):
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
                services=[
                    SERVICE_GENERIC_ACCESS_PROFILE,
                    self._profile.control_service,
                ],
            )
        except Exception:
            _LOGGER.exception("Could not connect to %s", self.address)
            self.client = None
            return
        try:
            client = self.client

            async def notified(char, data):
                # A queued notification from a previous session is not current state.
                if self.client is client:
                    await self._on_status_char_update(char, data)

            await client.start_notify(self._profile.status_characteristic, notified)
            self._notifying = True
            if self._profile.requires_handshake:
                await self._authenticate()
            await self.async_refresh_state()
        except BaseException:
            await self.disconnect()
            raise

    async def async_refresh_state(self, timeout: float = STATE_TIMEOUT) -> None:
        """Request a snapshot and wait until it is applied.

        Requires an established connection. Raises BleakError on disconnect or
        write failure and TimeoutError if the operation does not finish within
        timeout seconds, including time queued behind another read or write.
        No background polling or automatic reconnection is started.
        """
        async with asyncio.timeout(timeout):
            async with self._operation_lock:
                if not self.connected:
                    raise BleakError("Cannot refresh state: not connected to device")
                reply: asyncio.Future[None] = asyncio.get_running_loop().create_future()
                disconnected: asyncio.Future[None] = (
                    asyncio.get_running_loop().create_future()
                )
                self._status_reply = reply
                self._status_disconnected = disconnected
                write = asyncio.create_task(
                    self._write_packet(COMMAND_STATUS, b"\x00", client=self.client)
                )
                exchange = asyncio.gather(write, reply)
                try:
                    # A disconnect must wake the caller even if the write stalls.
                    await asyncio.wait(
                        (exchange, disconnected), return_when=asyncio.FIRST_COMPLETED
                    )
                    if disconnected.done():
                        raise BleakError("Disconnected during Daybetter state refresh")
                    await exchange
                finally:
                    self._status_reply = None
                    self._status_disconnected = None
                    exchange.cancel()
                    disconnected.cancel()
                    if not write.done():
                        write.cancel()
                    if not reply.done():
                        reply.cancel()
                    await asyncio.gather(
                        exchange, write, reply, disconnected, return_exceptions=True
                    )

    def _fail_pending(self):
        """Release in-flight exchanges and discard commands from this session."""
        if (
            self._status_disconnected is not None
            and not self._status_disconnected.done()
        ):
            self._status_disconnected.set_result(None)
        for reply in (self._handshake_reply, self._status_reply):
            if reply is not None and not reply.done():
                reply.set_exception(
                    BleakError("Disconnected during Daybetter exchange")
                )
        self.pending_power = None
        self.pending_brightness = None
        self.pending_color = None
        self.pending_effect = None

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

        self._fail_pending()

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

    async def _write_led_control(self, command: int, payload: bytes, pending):
        """Write the given payload to the LED control characteristic.
        Prepends the header and appends checksum to the payload.
        """
        async with self._operation_lock:
            if not self.connected:
                _LOGGER.warning("Cannot write characteristic: not connected to device")
                return
            attribute = {
                COMMAND_POWER: "pending_power",
                COMMAND_BRIGHTNESS: "pending_brightness",
                COMMAND_COLOR: "pending_color",
                COMMAND_EFFECT: "pending_effect",
            }[command]
            setattr(self, attribute, pending)
            try:
                await self._write_packet(command, payload)
            except BleakError as e:
                setattr(self, attribute, None)
                _LOGGER.error("Failed to write characteristic: %s", e)

    async def _write_packet(
        self, command: int, payload: bytes, *, client: BleakClient | None = None
    ):
        if client is None:
            client = self.client
        if client is None or client is not self.client or not client.is_connected:
            raise BleakError("Cannot write packet: connection is no longer current")
        # leading byte + command + length + payload + checksum not included
        length = 3 + len(payload)
        full_payload = bytes([0xA0, command & 0xFF, length & 0xFF]) + payload
        full_payload += modbus(full_payload)  # checksum

        await client.write_gatt_char(
            self._profile.write_characteristic, full_payload, response=True
        )

    async def set_color(self, new_color: RgbColor, color_correction=True):
        """Attempt to configure the current color of the lights. Will not turn on if currently off"""

        r, g, b = new_color
        if color_correction:
            r, g, b = correct_color(new_color)
        # RR GG BB
        payload = bytes([r & 0xFF, g & 0xFF, b & 0xFF]) + self._profile.variant

        # will be committed to self.color when acked
        await self._write_led_control(COMMAND_COLOR, payload, new_color)

    async def set_brightness(self, new_brightness: int):
        """Attempt to configure the brightness of the lights. Value should be between 0 and 100 (0x00 and 0x64)."""
        if not (0 <= new_brightness <= 100):
            _LOGGER.warning("Brightness value %d out of range (0-100)", new_brightness)
            return

        # between 00 and 64
        payload = bytes([new_brightness & 0xFF])
        # will be committed to self.brightness when acked
        await self._write_led_control(COMMAND_BRIGHTNESS, payload, new_brightness)

    async def set_effect(self, effect: Effect):
        """Attempt to put the light into one of the preset effect modes."""
        payload = bytes([effect.value & 0xFF]) + self._profile.variant
        await self._write_led_control(COMMAND_EFFECT, payload, effect)

    async def set_power(self, on: bool):
        """Attempt to turn the lights on or off."""
        # 00 = off, 01 = on
        payload = bytes([0x01 if on else 0x00])
        # will be committed to self.power when acked
        await self._write_led_control(COMMAND_POWER, payload, on)

    async def _on_status_char_update(
        self, _char: BleakGATTCharacteristic, data: bytearray
    ):
        if (
            len(data) < 5
            or data[0] != 0xA1
            or len(data) != data[2] + 2
            or modbus(data[:-2]) != data[-2:]
        ):
            return
        if self._handshake_reply is not None and not self._handshake_reply.done():
            if data[1] == self._handshake_command:
                self._handshake_reply.set_result(bytes(data[3:-2]))
            return
        # Full snapshot, both in response to a read and pushed by the IR remote.
        if data[1] == COMMAND_STATUS:
            if len(data) != 19 or data[3] not in (0, 1) or data[6] > 100:
                return
            self.raw_status = bytes(data[3:-2])
            self.power = data[3] == 0x01
            self.effect_id = data[4]
            self.brightness = data[6]
            try:
                self.effect = Effect(self.effect_id)
            except ValueError:
                self.effect = None
            self.color = (data[9], data[10], data[11]) if self.effect_id == 1 else None
            self.last_state_update = asyncio.get_running_loop().time()
            # A real snapshot supersedes acknowledged estimates from older writes.
            self.pending_power = None
            self.pending_brightness = None
            self.pending_color = None
            self.pending_effect = None
            if self._status_reply is not None and not self._status_reply.done():
                self._status_reply.set_result(None)
            self._trigger_listeners()
            return

        # ack - sent after we send a command - change state and trigger listeners
        # A1 XX 04 01 CRC
        if len(data) == 6 and data[3] == 0x01:
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
                    self.effect_id = int(self.pending_effect)
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
                    self.effect_id = 1
                    self._trigger_listeners()

    def _on_disconnected(self, _old_client: BleakClient):
        if self.client is not _old_client:
            return
        _LOGGER.warning("Device disconnected")

        # not async - can't do much here
        self.client = None
        self._authenticated = False
        self._notifying = False
        self._fail_pending()
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
        return (
            self.client is not None
            and self.client.is_connected
            and (not self._profile.requires_handshake or self._authenticated)
        )

    @property
    def rssi(self) -> int | None:
        if self.advertisment_data is None:
            return None
        return self.advertisment_data.rssi
