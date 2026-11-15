import asyncio
import logging

from bleak import BleakScanner

from daybetter_ble_client import DaybetterLedStrip
from daybetter_ble_client.const import SUPPORTED_DISCOVERY_SERVICES

_LOGGER = logging.getLogger(__name__)


async def run():
    logging.basicConfig(level=logging.INFO)

    # Scan for either model and retain advertisements for automatic detection.
    devices = await BleakScanner.discover(timeout=10, return_adv=True)
    matches = [
        (device, data)
        for device, data in devices.values()
        if any(
            service in data.service_uuids for service in SUPPORTED_DISCOVERY_SERVICES
        )
    ]
    if len(matches) != 1:
        _LOGGER.error(
            "Expected one supported strip, found %d. Run with only the target strip available.",
            len(matches),
        )
        for device, _ in matches:
            _LOGGER.info("Available strip: %s (%s)", device.name, device.address)
        return

    device, data = matches[0]
    led_strip = DaybetterLedStrip(device.address)

    def on_change():
        _LOGGER.info(
            "Model: %s | Power: %s | Color: %s | Brightness: %s | Connected: %s | RSSI: %s",
            led_strip.model,
            led_strip.power,
            led_strip.color,
            led_strip.brightness,
            led_strip.connected,
            led_strip.rssi,
        )

    unsubscribe = led_strip.on_change(on_change)
    try:
        await led_strip.update_device(device, data)
        if not led_strip.connected:
            raise RuntimeError("Could not connect to strip")
        await led_strip.set_power(True)
        for color in ((255, 0, 0), (0, 255, 0), (0, 0, 255)):
            await led_strip.set_color(color)
            await asyncio.sleep(1)
        await led_strip.set_brightness(10)
        await asyncio.sleep(1)
        await led_strip.set_power(False)
    finally:
        unsubscribe()
        await led_strip.disconnect()


if __name__ == "__main__":
    asyncio.run(run())
