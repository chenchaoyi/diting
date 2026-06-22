## Why

`location-status` read `CLLocationManager().authorizationStatus` synchronously in
a short-lived process. CoreLocation reports `.notDetermined` until the manager
REGISTERS with the location daemon (a moment after creation), so a fresh probe
process reading the property immediately returns a spurious `.notDetermined`
even when the bundle is actually authorized. Result: after the user granted
Location, `diting setup` kept reading "not determined" and sat on
"Location: waiting" forever. (Bluetooth's `CBManager.authorization` is a class
property with no registration step, so it read correctly — which is why the
v2.0.3 install showed `Bluetooth: granted` but `Location: waiting`.)

Separately, `setup`'s verification poll runs the three probes serially, each a
disclaimed subprocess (~2 s of re-exec overhead), so a poll cycle was slow.

## What Changes

- `location-status` reads the grant via the `CLLocationManager` authorization
  CALLBACK (`locationManagerDidChangeAuthorization`), which fires once the manager
  has registered with the REAL status — not a synchronous property read. It still
  never calls `requestWhenInUseAuthorization` (assigning a delegate triggers the
  callback without prompting), so it remains prompt-free. A bounded settle
  timeout falls back to reading the property (by then registered).
- `permission.probe` runs the Location / Bluetooth / Notifications probes
  CONCURRENTLY, so a poll cycle's wall-clock is the slowest single probe instead
  of their sum.

## Capabilities

### Modified Capabilities
- `macos-helper`: `location-status` SHALL reflect the bundle's true Location
  authorization (read via the registration callback, not a premature synchronous
  property read), so it never reports a granted bundle as `notDetermined`.

## Impact

- `helper/Sources/diting-tianer/main.swift` — `runLocationStatusProbe` uses a
  `CLLocationManagerDelegate` callback + settle timeout; no prompt; exit codes
  unchanged. Helper rebuild → ships in the next patch release.
- `src/diting/permission.py` — `probe()` runs the three probes via a
  `ThreadPoolExecutor` (snappier poll). No behaviour change to the result shape.
- Tests: `test_setup.py` (probe still returns status strings; concurrency is
  transparent). Helper-side verified by hand. Update `tests/TESTING.md` (EN + ZH).
