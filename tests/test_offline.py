"""Check that accidentally using a real BLE entry point fails closed."""

import bleak
import pytest

# This runs while pytest imports the module, before any autouse test fixture.
# The inert backend also keeps the regression safe if session protection breaks.
with pytest.raises(pytest.fail.Exception, match="Real Bluetooth"):
    bleak.BleakClient("collection-probe", backend=lambda *args, **kwargs: None)


@pytest.mark.parametrize("constructor", [bleak.BleakClient, bleak.BleakScanner])
def test_bluetooth_constructors_are_blocked(constructor):
    # An inert backend makes this regression safe even before the guard exists.
    kwargs = {"backend": lambda *args, **kwargs: None}
    args = ("offline-device",) if constructor is bleak.BleakClient else ()
    with pytest.raises(pytest.fail.Exception, match="Real Bluetooth"):
        constructor(*args, **kwargs)
