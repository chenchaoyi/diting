# design — add-ble-presence-gate

## State machine

Per-identifier, per-session:

```
INIT ── first advert, anonymous ──> PENDING
INIT ── first advert, named OR _connected ──> PRESENT (immediate seen)
PENDING ── (now - first_seen) ≥ gate, still in _devices ──> PRESENT
            └─ emit BLEDeviceSeenEvent with original first_seen timestamp
PENDING ── identifier evicted before gate elapses ──> INIT-silent
            └─ no seen, no left; drop quietly
PRESENT ── TTL eviction ──> DEPARTED
            └─ emit BLEDeviceLeftEvent
DEPARTED ── advert re-arrives OR re-evicts ──> DEPARTED (silent)
            └─ handled by fix-ble-left-dedup (#107)
```

PENDING is the new state. The transition INIT-silent is the new
"silent drop": an identifier heard once that vanishes before the
gate matures leaves no trace in the events log.

## Why named devices bypass

A first-packet advert that arrives with `name` set is almost
always a real device with stable identity (`Magic Keyboard`,
`AirPods Pro`, `Z-GM0YXG5J`, `ccy iPhone 15 Pro Max`). Suppressing
its `seen` event for 5 s would make the events panel feel laggy
on familiar peripherals — the user does see them in the BLE list
immediately (snapshot path), but the event log would only register
them on the second tick. Inconsistency between the two surfaces
is a worse user experience than a slightly noisier log on rare
events.

Anonymous adverts (just `vendor` + RSSI, no name, no service
UUIDs) are the noisy ones. Apply the gate there.

Connected peripherals — entries from the helper's
`retrieveConnectedPeripherals` snapshot — are by definition
already bonded. They've passed every reasonable confidence check.
Bypass.

## Timestamp choice on graduated seen events

When a PENDING identifier graduates, the emitted
`BLEDeviceSeenEvent.timestamp` SHALL be the **original first-seen
time**, not the gate-elapsed wall-clock time. Rationale:

- The JSONL `ts` field claims to be "when did the device appear".
  Lying about that breaks `diting analyze`'s hour-of-day and
  day×hour aggregations.
- The events panel sorts by event timestamp; the seen line
  lands in its chronological position even though we emit
  ~5 s later than wall-clock.
- `seen_for_seconds` on the eventual left event is computed
  from `last_seen - first_seen` on the BLEDevice — already
  honest, already separate from emission time.

## Why not graduate by advert count instead of time

Two reasons elapsed time wins:

1. **User-comprehensible config.** `5s` and `15s` map to a user's
   intuition of "how long was the device around". `3 adverts` does
   not — the user has to know typical advert intervals.
2. **Time is sensor-invariant.** Different BLE devices advertise
   at different rates (1 Hz typical, but Apple Nearby fires
   bursts then quiets down). A time gate cuts cleanly across
   advertise-rate variance; a count gate would favour
   high-rate-spammy advertisers.

## Where to plumb the option

CLI flag + env var, no config file. Three reasons:

- Matches the project's existing pattern (`DITING_LANG`, `DITING_LOG`).
- Config files imply a config-loading subsystem diting doesn't
  have today; adding one for a single knob is over-engineering.
- Users with a persistent preference can `export
  DITING_BLE_PRESENCE_GATE=0` in their shell rc; one-off runs
  can pass `--ble-presence-gate 30s`.

CLI flag wins over env var (per `i18n.detect_default_lang`'s
precedence — CLI explicit > env > default).

## Edge cases

**A pending identifier whose entry's `name` becomes populated
later (later adverts with scan-response that carries the name).**
The BLEPoller's `_apply_helper_line` rebuilds the BLEDevice via
`_build_device`, which preserves name from `prior` if present.
If the *first* helper line had no name but the *second* did,
`_devices[ident].name` is now non-null. On the next tick's
`_detect_transitions`, the gate sees a name and graduates the
identifier immediately. Good.

**An identifier in PENDING when the user stops diting.** The
device exited PENDING via INIT-silent (no events emitted). No
JSONL line written. The user's interpretation: "diting didn't
see this device" — which matches the gate's intent.

**A long-running session where an identifier flap-bounces.**
First advert at t=0 → PENDING. TTL-evicted at t=35 (no seen
emitted, no left emitted, drops from _pending_seen). At t=120
the same identifier shows up again. Treated as a brand-new
INIT (it's no longer in any of {pending, seen, departed}).
Gate restarts from t=120. Consistent.

## Default value rationale

5 s = 2-3 standard 1-2 Hz BLE advert intervals. Kills:

- Single-packet detection (the user's exact complaint)
- 1-2 packet bursts from edge-of-range identifiers
- Apple Continuity RPA edge flickers (which typically need
  several seconds of audibility before staying in range)

Preserves:

- Walk-bys (5-30 s of contact, multi-packet)
- Static nearby devices (constantly broadcasting)
- AirPods passing through the room (8-15 s typical)
- The user's own pocketed iPhone (15-min-stable identifier)

Configurable up to user's environment. A home audit might use
`0s` for completeness; an office in a tower would benefit from
`30s` or higher.

## What we explicitly do NOT change

- The BLE list / `_devices` map. PENDING identifiers still
  appear in the BLE panel (snapshot rendering is unchanged).
  Only the events stream is gated.
- The connected-peripheral path. Unchanged.
- The `BLEDeviceLeftEvent` dedup from fix-ble-left-dedup.
  Still correct: once seen has fired (post-graduation), the
  first left fires on TTL eviction; subsequent re-evictions
  are silent.
- The JSONL schema. No new fields, no new types.
- The analyzer. Aggregations consume the same JSONL records;
  fewer records = cleaner ranking, but no API change.
