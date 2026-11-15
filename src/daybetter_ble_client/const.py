from dataclasses import dataclass
from enum import IntEnum, unique

from bleak.uuids import normalize_uuid_16

# includes Device Name characteristic
SERVICE_GENERIC_ACCESS_PROFILE = normalize_uuid_16(0x1800)
# read
CHAR_DEVICE_NAME = normalize_uuid_16(0x2A00)

SERVICE_LED_CONTROL = normalize_uuid_16(0xE031)
# write
CHAR_LED_CONTROL = normalize_uuid_16(0xA031)
# "read", notify
CHAR_LED_STATUS = normalize_uuid_16(0xF031)

# Advertised service
SERVICE_DISCOVERY = normalize_uuid_16(0xC031)


@dataclass(frozen=True)
class DeviceProfile:
    model: str
    discovery_service: str
    control_service: str
    write_characteristic: str
    status_characteristic: str
    requires_handshake: bool = False
    variant: bytes = b""


P031 = DeviceProfile(
    "P031", SERVICE_DISCOVERY, SERVICE_LED_CONTROL, CHAR_LED_CONTROL, CHAR_LED_STATUS
)
P065 = DeviceProfile(
    "P065",
    normalize_uuid_16(0xC065),
    normalize_uuid_16(0xE065),
    normalize_uuid_16(0xA065),
    normalize_uuid_16(0xF065),
    True,
    b"\xff",
)
DEVICE_PROFILES = (P031, P065)
SUPPORTED_DISCOVERY_SERVICES = tuple(p.discovery_service for p in DEVICE_PROFILES)

# GATT command ID
COMMAND_BRIGHTNESS = 0x13
COMMAND_EFFECT = 0x12
COMMAND_POWER = 0x11
COMMAND_COLOR = 0x15


@unique
class Effect(IntEnum):
    # Show preset colors
    SHOW_RED = 0x02
    SHOW_GREEN = 0x03
    SHOW_BLUE = 0x04
    SHOW_YELLOW = 0x05
    SHOW_TEAL = 0x06
    SHOW_PURPLE = 0x07
    SHOW_WHITE = 0x08

    # Switch colors abruptly
    SWITCH_RGB = 0x09
    SWITCH_ALL_PRESET_COLORS = 0x0A

    # Fade between colors
    FADE_COLORS_QUICK = 0x0B
    FADE_COLORS_SLOW = 0x0C

    # Blink individual preset colors
    BLINK_RED = 0x0D
    BLINK_GREEN = 0x0E
    BLINK_BLUE = 0x0F
    BLINK_YELLOW = 0x10
    BLINK_TEAL = 0x11
    BLINK_PURPLE = 0x12
    BLINK_WHITE = 0x13

    # Fade between two colors
    FADE_RED_GREEN = 0x14
    FADE_RED_BLUE = 0x15
    FADE_GREEN_BLUE = 0x16

    # Flash all preset colors
    FLASH_ALL_PRESET_COLORS = 0x17

    # Flash individual preset colors
    FLASH_RED = 0x18
    FLASH_GREEN = 0x19
    FLASH_BLUE = 0x1A
    FLASH_YELLOW = 0x1B
    FLASH_TEAL = 0x1C
    FLASH_PURPLE = 0x1D
    FLASH_WHITE = 0x1E

    # Strobe effects
    STROBE_RGB = 0x1F
    STROBE_ALL_COLORS = 0x20
