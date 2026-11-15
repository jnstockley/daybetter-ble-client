# P031 and P065 support

## Intent

Support the user's P065 alongside the existing P031 through the same
`DaybetterLedStrip` API, with automatic model detection and no required changes
to existing P031 callers.

## Approaches

- **Automatic model detection (selected by the user):** select a small device
  profile from advertised services, with the device name as a fallback. This
  preserves existing constructor usage and simplifies discovery.
- **Explicit model selection:** simpler detection, but requires each integration
  to identify the model itself. Not selected.

## Design

- Keep the existing P031 UUID constants and default behavior. Add profiles for
  P031 (`c031/e031/a031/f031`) and P065 (`c065/e065/a065/f065`) and expose the
  supported discovery services for callers scanning for either device.
- Detect the profile during `update_device`, preferring advertised service UUIDs
  over the device name. Retain P031 as the compatibility default when neither
  identifies the model. Do not infer support for arbitrary model numbers.
- Route connection service filters, writes, notifications, and disconnects
  through the selected profile.
- For P065, enable notifications and complete the two-step `CCHIP` handshake:
  request the device's value with command `00`, echo its returned payload with
  command `01`, and require a successful response before allowing control.
  Validate response framing and checksum; bound waits and disconnect on failure.
  The observed success payload differs from the request and ends in `01`.
- Verify the P065 color payload and effect payload against the physical device.
  Isolate any extra variant byte in the P065 profile; leave P031 packets intact.
- Initialize connection/handshake state and listeners per instance so controlling
  two devices does not mix their state or callbacks.
- Update the example to discover both models and always disconnect in `finally`.
  Document local setup, discovery, P065 handshake behavior, and tested limits.

## Verification

Use asynchronous unit tests with simulated BLE notifications for detection,
P031 packet compatibility, P065 handshake success/rejection/timeout, reconnect,
cleanup, and instance isolation. Verify installation and packaging. Then use the
library against both nearby devices, distinguishing device acknowledgements
from user-confirmed visible behavior. Test only reversible light settings.

## Scope and limits

No new UI, daemon, automatic reconnect policy, or support for other models.
Do not claim every P065 effect is validated based on a red-color test. The
builder will choose internal profile representation and test utilities.
