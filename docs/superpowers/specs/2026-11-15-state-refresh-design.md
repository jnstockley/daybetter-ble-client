# Device state refresh

Implement the library changes requested after the state-sync investigation.
HA owns polling frequency; the library owns one bounded read operation.

## Approach

Expose `await strip.async_refresh_state(timeout=5.0)` and request initial state
after notification setup and P065 authentication. Read command `10 00` through
the active model's write characteristic. Do not add a background polling task.
A connect that cannot obtain initial state fails after releasing its transport.
Callers retry connection explicitly, as before.

Decode the 14-byte status payload: power at 0, preset at 1, brightness at 3,
and RGB at 6–8. The P031 reference parser in icub3d/dotfiles/helpers/ledstrip.py
documents these offsets; previous local P065 hardware checks independently
exercised power, brightness, effect and RGB at those offsets. This is evidence
for a shared layout, not a fresh hardware validation of either model.
Preset 1 denotes static RGB; known preset IDs map to Effect, unknown IDs remain
available through `effect_id`. Only static mode exposes `color`; raw status is
available for diagnostics. Do not attempt to invert lossy gamma correction.

Reject wrong direction, length, CRC, power and brightness before updating state.
Apply snapshots atomically and notify once. Serialize reads and control writes,
bound the write and response wait together, and fail pending reads immediately
on manual or remote disconnect. Ignore notifications from replaced transports.
Initialize cached and pending state per instance and clear pending commands on
disconnect. Expose `last_state_update` as a monotonic timestamp for status reads;
acknowledgements do not count as device snapshots.

## Constraints and verification

Keep Python 3.11–3.15, existing imports, dependency bounds and MIT attribution.
All tests remain offline. Cover both profiles, mode changes, malformed packets,
refresh timeout/write failure, cancellation, concurrency, reconnect, and stale
notifications. Run both suites, branch coverage >=95%, lint and package checks.
HA integration changes and live Bluetooth validation are outside this change.
