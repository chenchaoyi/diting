## Context

`CLLocationManager().authorizationStatus` is unreliable when read immediately in a
fresh CLI process: the manager hasn't registered with the location daemon, so it
returns `.notDetermined`. The functional `scan` path avoided this by keeping the
manager alive across retries; the read-only probe did not. `CBManager.authorization`
(a class property) and `UNUserNotificationCenter.getNotificationSettings` (async
callback) don't have this issue.

## Decisions

### D1 — Read Location via the authorization callback
`runLocationStatusProbe` assigns a `CLLocationManagerDelegate`; the docs guarantee
`locationManagerDidChangeAuthorization` fires when the manager is created (after
registration) AND on changes — WITHOUT calling `requestWhenInUseAuthorization`, so
no prompt. The probe waits through an initial `.notDetermined`, exits on the first
settled status, and a bounded (~4 s) timeout falls back to reading the property
(registered by then). An authorized bundle resolves quickly via the callback; a
genuinely not-determined bundle hits the timeout and exits 4.

  Alternative: keep the synchronous read but add a fixed sleep. Rejected — the
  callback is the canonical, faster-on-the-happy-path signal.

### D2 — Probe concurrently
`permission.probe` runs the three probes on a `ThreadPoolExecutor(max_workers=3)`.
Each is an independent subprocess; the GIL doesn't matter (they block on the
child). Poll wall-clock ≈ slowest probe (Location) instead of the sum.

## Risks / Trade-offs

- [The notDetermined case still takes ~timeout seconds] → Acceptable: that's the
  "waiting for the user" state; once granted, the callback resolves fast. The
  concurrency keeps the other two probes from adding to it.
- [GUI inter-prompt latency is unchanged] → That wait (CoreLocation registration
  + CoreBluetooth power-on between the helper's sequential prompts) is
  macOS-inherent and out of scope; this change only fixes the probe + poll speed.

## Verification

Rebuilt locally: `location-status` on a not-determined bundle exits 4 (via the
delegate/timeout path) with no prompt; `bluetooth-authorization` unchanged.

## Open Questions
- None.
