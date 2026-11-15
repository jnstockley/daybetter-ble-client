# daybetter-led-strip

![GitHub License](https://img.shields.io/github/license/grimsteel/daybetter-led-strip)
![GitHub Actions Workflow Status](https://img.shields.io/github/actions/workflow/status/grimsteel/daybetter-led-strip/release.yml)
[![PyPI - Version](https://img.shields.io/pypi/v/daybetter-led-strip)](https://pypi.org/project/daybetter-led-strip)


Python package to control Daybetter RGB LED strips over BLE. Uses [`bleak`](https://bleak.readthedocs.io/en/latest/index.html).

Supports P031 and P065 devices. The model is detected from the advertised
service UUID, with the Bluetooth device name as a fallback. Existing P031
constructor calls and UUID constants remain supported.

## Installation

`daybetter-led-strip` is on PyPI

```sh
$ pip install daybetter-led-strip
```

### Local development

Install this checkout in an isolated environment (with [uv](https://docs.astral.sh/uv/)):

```sh
uv venv --python 3.14 .venv
uv pip install --python .venv/bin/python -e .
source .venv/bin/activate
python -m unittest discover -s tests -v
```

Use the fork checkout for P065 support; the upstream PyPI release does not
include these changes. Enable Bluetooth and allow Bluetooth access for the app
running Python on macOS. Close the phone app before connecting; the strip can
accept only one BLE connection at a time.

## Usage

The `DaybetterLedStrip` constructor only requires the device address (a UUID on
macOS, a MAC address on other platforms). Pass the scanned device and its
advertisement data to `.update_device` for automatic model selection. The
detected model is available as `.model`. If identifying data is unavailable,
the compatibility default is P031. If the device disconnects, it will not
automatically reconnect; call `.update_device` again with a freshly scanned
device, or `.connect` to retry the stored device. P065 authenticates on every
connection, and initialization failures raise an exception after cleanup.

```python
import asyncio
from bleak import BleakScanner
from daybetter_led_strip import DaybetterLedStrip
from daybetter_led_strip.const import SUPPORTED_DISCOVERY_SERVICES

# This snippet runs inside an async function. Pick one target explicitly.
devices = await BleakScanner.discover(timeout=10, return_adv=True)
matches = [(device, data) for device, data in devices.values()
           if any(service in data.service_uuids
                  for service in SUPPORTED_DISCOVERY_SERVICES)]
for device, data in matches:
    print(device.name, device.address)
if not matches:
    raise RuntimeError("No supported strip found")
device, data = matches[0]  # choose the intended strip if several are found
led_strip = DaybetterLedStrip(device.address)
try:
    await led_strip.update_device(device, data)
    if not led_strip.connected:
        raise RuntimeError("Could not connect to strip")
    await led_strip.set_power(True)
    await led_strip.set_color((255, 0, 0))
    await asyncio.sleep(1)
    await led_strip.set_power(False)
finally:
    await led_strip.disconnect()
```

A complete example program is provided in `examples/test.py`.
Run it with `python examples/test.py`. It cycles colors, changes brightness,
and turns the strip off. It requires exactly one supported strip to be
discoverable to avoid changing an unintended device.

This package was created [for use in Home Assistant](https://github.com/grimsteel/homeassistant-daybetter-led-strip), which may explain some of the API choices.

## Protocol

Communication with the LED strip is done over BLE.

The light strip exposes two services: the generic access profile w/ the device name, and a custom "LED control service" (`0xe031`).

During discovery, the device also advertises itself with a third service (`0xc031`) for identification.

P065 uses the equivalent UUIDs `0xc065` (discovery), `0xe065` (control
service), `0xa065` (write), and `0xf065` (status notifications).

### P065 connection initialization

After subscribing to notifications, P065 requires a two-step handshake before
control commands take effect. Send command `0x00` with `CCHIP`; the response
contains `CCHIP` and two device-specific bytes. Echo that complete seven-byte
payload with command `0x01`. A six-byte reply ending in `0x01` indicates success.
The library validates framing and CRC and waits up to five seconds for each
response. It disconnects if initialization fails. Do not hard-code the two
device-specific bytes from another strip.

P065 color commands append `0xff` after the RGB bytes, and effect commands
append `0xff` after the effect ID. P031 payloads retain their existing format.
An acknowledgement only confirms receipt; it does not prove a visible change.

Validation on a physical P065 covered handshake/reconnect, RGB color, brightness,
power, and `FADE_RED_GREEN`, with settings checked through status reads. Other
effect IDs have not been individually tested. P031's original command format is
covered by regression tests; a fresh P031 hardware check could not be completed
during this change because the device was not consistently discoverable.

The LED control service has a read characteristic (`0xf031`) and a write characteristic (`0xa031`). As far as I can tell, the read characteristic cannot actually be read directly. Rather, if notifications are enabled on this service, the device will push updates about its state at various times.

### Write Data Format

Commands written to the write characteristic have the following format. 

1. The byte `0xA0` (referred to in the app source code as "APP_TO_DEVICE")
2. The command ID. (1 byte)
3. The length of the entire message, not including the checksum. (1 byte) `= len(payload) + 3`
4. The payload for this command
5. The little-endian CRC16 MODBUS checksum of the rest of the message.

### Commands

| Command         | ID     | Payload Description                                                                                  |
|-----------------|--------|-----------------------------------------------------------------------------------------------------|
| **Get status**  | `0x10` | `0x00`<br>Results in status payload below being sent on notify                                      |
| **Set power**   | `0x11` | `0x01` (on) or `0x00` (off)                                                                         |
| **Show effect** | `0x12` | One of the effect bytes listed below                                                                |
| **Set brightness** | `0x13` | A byte representing the brightness, from 0 (`0x00`) to 100 (`0x64`). Brightness 0 still has the LEDs slightly on |
| **Set color**   | `0x15` | 3 bytes, in RGB order                                                                               |

Example command (set to red): `A0 15 06 FF 00 00 25 C0`

### Notify/read data format

The payloads received over notify have a similar structure as the write commands:

1. The byte `0xA1` ("DEVICE_TO_APP")
2. Command ID
3. Length of entire message excluding checksum
4. Payload 
5. LE Checksum

### Received "commands"

When any of the above write commands are written to the characteristic successfully, the device responds with a message with the same command ID and `0x01` for the payload.

For instance, the above color command would result in `A1 15 04 01 F1 1C`

When the strip is turned on/off from the IR remote, a message with command ID `0x10` and the payload `00 01 01 64 32 32 ff 31 2d f0 00 00 00 00` (off) or `01 01 01 64 32 32 ff 31 2d f0 00 00 00 00`. The first byte indicates the on/off status, but I don't know what the rest means. It seems unrelated to the color of the light.

Running the "get status" command also results in this being sent.

### Effects

> Note: the brightness can be changed during the following effects. Lower brightnesses result in blinking happening faster, likely because there is a smaller range of brightnesses to interpolate between.

RGB: just red/green/blue

All preset colors: red/green/blue/yellow/teal/purple/white

* `0x02..0x08`: show preset colors
* `0x09`: switch RGB abruptly, no transition
* `0x0A`: switch all preset colors
* `0x0B`: fade between colors quickly
* `0x0C`: fade between colors slowly
* `0x0D`..`0x13`: blink individual preset colors
* `0x14`: fade red/green
* `0x15`: fade red/blue
* `0x16`: fade green/blue
* `0x17`: flash all preset colors
* `0x18`..`0x1E`: flash individual preset colors
* `0x1F`: strobe RGB
* `0x20`: strobe all colors
