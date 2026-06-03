# Design — threat detections

## Reuse the insight pipeline; add a `critical` severity

A threat is a `critical`-severity `insight` with a security `code`. This reuses
the whole Phase-2 pipeline — the `InsightEvent` type, `emit_insight`, the JSONL
shape, the EventRing/modal, the watchdog notifier — with three small additions:

- `salience`: `critical` → `high` (alongside `warn`).
- `_watchdog.maybe_notify`: notify on `severity ∈ {note, warn, critical}`.
- TUI `_format_insight_event`: `critical` → a `[THREAT]` label in bold red
  (vs `[INSIGHT]` for note/warn); `format_insight_summary` gains the threat
  one-liners.

No new event type, no new wire surface. Threats are desktop-local (the `insight`
type is not in the companion push set), surfaced via macOS notification + the
TUI + JSONL.

## A sibling ThreatEngine

`src/diting/threats.py` mirrors `InsightEngine`: `observe(payload)` folds the
enriched wire payloads into bounded state, `collect(now)` returns the fired
threat insights with a per-(code, target) cooldown. It is kept separate from
`InsightEngine` so the security logic is isolated and independently testable;
it imports the shared `_parse_ts` helper. The TUI constructs both engines,
registers both as logger observers, and the existing collect timer drains both.

`observe` never raises and ignores its own `insight` output.

## Detectors

### evil_twin (point-in-time, queued in observe)
State: `_ssid_vendors: dict[ssid, set[vendor]]`. On an association/roam to an
SSID (an `associated` `link_state` with `ssid`+`vendor`, or a `roam` using its
`new_ssid`/`ssid` + `new_vendor`): if the SSID already has ≥1 recorded vendor
and the incoming non-None vendor is new for it → queue an `evil_twin` threat
`{ssid, known_vendor, new_vendor, bssid}`. Then record the vendor. The first
vendor for an SSID never fires. Rationale: a legitimate multi-AP network is
near-always one hardware vendor; a different OUI under the same SSID is the
classic impersonation tell. Cooldown keyed `(evil_twin, ssid)`.

### deauth_storm (rate, evaluated in collect)
State: `_disassoc: deque[datetime]` of `link_state` disassociations. In
`collect`, count those within a *tight* window (`_storm_window_s`, default
90 s); ≥ `_storm_min` (default 4) → `deauth_storm` `critical`
`{count, window_s}`. Deliberately tighter + higher than the operational
`repeated_disassociates` insight (600 s / 3) so the two convey different things
(flaky link vs attack pattern). Honest: inferred from association state, not
observed 802.11 deauth frames.

### follows_you (cross-epoch, evaluated in collect)
State: `_epoch: int` (advanced by each `network_change`), and
`_device_epochs: dict[identifier, set[int]]` for BLE `ble_device_seen` whose
`familiarity` is `first_time`/`occasional` (an unfamiliar device). In `collect`,
any identifier present in ≥ 2 distinct epochs → `follows_you`
`{identifier, locations}`. Cooldown keyed `(follows_you, identifier)`. Only an
*unfamiliar* device that persisted while the user changed networks fires — a
habitual device (the user's own) never does.

## Why these signals are authoritative

- evil_twin keys on the OUI-derived **vendor** + **BSSID**, never the SSID as a
  trust anchor (the SSID is precisely what the attacker forges).
- deauth_storm keys on disassociation **timing**.
- follows_you keys on the rotation-folded **device identity** + the
  **network_change** epoch boundary, never a BLE/host display name.

## Alternatives considered

- **A separate `ThreatEvent` type.** Rejected: threats are insights at the top
  of the severity scale; reusing `insight` + `critical` avoids a parallel event
  type, ring branch, and (eventually) a second wire type.
- **evil_twin from passive scan results.** Deferred: the event stream carries
  only the associated BSSID, not the full scan, so we detect twins the user
  actually lands on (the dangerous case). A passive "twin present in scan"
  detector would need a scan-results feed.
- **security_downgrade now.** Deferred: needs the connection cipher on the wire
  (a proper `companion-protocol` field + version bump), not a stripped local
  field — doing it right is its own paired change.
