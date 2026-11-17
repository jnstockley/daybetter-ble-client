"""Build real discovery objects across supported Bleak versions."""

from inspect import signature

from bleak.backends.device import BLEDevice


def make_device(address: str, name: str | None, details: object) -> BLEDevice:
    # Bleak 0.21 requires RSSI here; newer releases keep it in AdvertisementData.
    kwargs = {"rssi": -66} if "rssi" in signature(BLEDevice).parameters else {}
    return BLEDevice(address, name, details, **kwargs)
