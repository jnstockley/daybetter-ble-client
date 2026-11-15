# Device state refresh implementation plan

**Goal:** Populate initial device state and allow HA to request later snapshots.

**Architecture:** One awaitable read, serialized with control writes, using the
existing model profiles and notification callback. No background timer.

**Spec:** ../specs/2026-11-15-state-refresh-design.md

## Tasks

- [x] Add offline parser tests for complete snapshots, static/effect/unknown
  modes, invalid values, lengths and CRC. Watch failures; implement validation
  and atomic state updates in `src/daybetter_ble_client/led_strip.py`.
- [x] Add offline tests for `async_refresh_state(timeout=5.0)`, initial state on
  connection, overlapping reads/writes, timeout including stalled writes,
  cancellation, manual/remote disconnect, reconnect and stale callbacks. Watch
  failures; implement bounded waits and cleanup. Extend transport fake to emit
  a documented static status response; update packet-order expectations.
- [x] Document API, status layout, raw RGB semantics and hardware limits in
  README. Run `scripts/test.sh`, `scripts/lint.sh`, build and strict metadata
  checks. Review diff for lifecycle regressions and record verification.

## Verification

- Parser tests first failed on missing brightness/RGB updates and accepted corrupt
  packets; refresh tests first failed on the missing API and initial snapshot.
- Independent review reproduced disconnect after response but before write
  completion, and a deferred write reaching a replacement client. Regression
  tests failed, then passed after adding a separate disconnect signal and binding
  refresh writes to their originating transport.
- `scripts/test.sh`: 103 library/release tests plus 7 example tests pass on Python
  3.15; 99.58% branch-inclusive library coverage. Python 3.11 offline suite also
  passes (103 tests, 3 subtests).
- `scripts/lint.sh`: Python, shell and YAML checks pass.
- Wheel and sdist build, strict Twine metadata checks and installed artifact
  smoke tests outside the checkout pass for version 1.0.0.
- Hardware was not accessed.
