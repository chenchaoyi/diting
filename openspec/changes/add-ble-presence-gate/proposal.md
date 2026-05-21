# add-ble-presence-gate

## Why

The 2026-05-21 audit + the user's own events-modal observation
("没有人路过，但还是有 0s 的匿名 apple 设备不断出现") show that
the A1 contract "no debounce — record every first observation"
generates a continuous stream of single-packet `(anonymous)`
Apple events in any dense RF environment. Their hallmark is
`seen_for_seconds = 0.0` on the paired `BLEDeviceLeftEvent`:
the helper caught one advert from an edge-of-range or transient
source, the device aged out one TTL cycle later, never to
return.

A 5.6 h capture session in this category produced 12,348 unique
identifiers and 67k events. The audit's "bug fix only" option
(fix-ble-left-dedup, #107) already pruned ~43k spurious left
events for the same identifier — but each unique identifier
still emits its one `seen` + one (typically 0s) `left` pair.
The remaining ~24k events for the captured session are still
dominated by these single-packet ghosts.

The user opted for a 5s presence gate as the default — at
least 2-3 consecutive adverts (≈ 5s elapsed time) must be
observed before an identifier graduates to PRESENT and fires
`BLEDeviceSeenEvent`. A device that catches one packet and
vanishes within the gate window emits nothing at all.

## What changes

- `BLEPoller` gains a `presence_gate_s: float = 5.0` constructor
  parameter. An identifier observed for less than `presence_gate_s`
  seconds AND with no helper-given `name` does NOT emit
  `BLEDeviceSeenEvent`; if it ages out before the gate elapses,
  no `BLEDeviceLeftEvent` either.
- **Bypasses:** named devices and connected peripherals skip the
  gate. If the first advert carries a `name` (e.g. `Magic
  Keyboard`, `Z-GM0YXG6A`), or the identifier comes from the
  `_connected` snapshot path, `BLEDeviceSeenEvent` fires
  immediately. The presence-gate only applies to anonymous
  advertising-path observations.
- New CLI flag `--ble-presence-gate <duration>` accepting the
  same `<int><unit>` syntax as `diting analyze --since` (`5s`,
  `15s`, `2m`, `1h`). `0` (or `0s`) restores the original A1
  "record everything" semantics.
- Env var `DITING_BLE_PRESENCE_GATE` mirrors the flag for users
  with a persistent preference, matching the existing
  `DITING_LANG` precedence pattern (CLI flag wins, env fills
  in, then the 5s default).
- Spec: `bluetooth-scanning` MODIFIED requirement — the "no
  debounce SHALL be applied" sentence is replaced with the
  gated semantics + bypass rules.

## Impact

- **Default UI experience:** the events panel stops scrolling
  with `(匿名) Apple, Inc.  ·  0s` flicker. Real walk-bys
  (≥ 5-30 s contact) still register. Named / paired devices
  surface on the first advert as today.
- **JSONL log:** same dedup applies at emission time — the
  log stays in sync with the events panel. Cross-session
  aggregations in `diting analyze` no longer count short-flicker
  identifiers in "top BLE contributors".
- **`record everything` use cases** (security research,
  AirTag-spotting, stalkerware detection, debugging a specific
  brief advertiser) opt-in by setting `--ble-presence-gate 0`
  or `DITING_BLE_PRESENCE_GATE=0`. The contract is preserved,
  just not default.
- **Spec change is non-breaking for tests of the bypass paths:**
  every existing test that exercises a named device or connected
  peripheral still passes because of the bypass. The existing
  test of TTL-eviction-emits-left will need to assert the device
  was named (so it actually emits a seen first).
- **No new dependency, no schema bump.** Field shapes unchanged.

## Affected code

- `src/diting/ble.py:1293-1349` — `BLEPoller.__init__` adds
  `presence_gate_s`, new `_pending_seen` map
- `src/diting/ble.py:1468-1528` — `_detect_transitions` adds the
  pending-then-graduate state machine
- `src/diting/cli.py` — `--ble-presence-gate` flag parsing
  + `DITING_BLE_PRESENCE_GATE` env var
- `src/diting/tui.py:5664-5700` — `DitingApp.__init__` gains
  `ble_presence_gate_s` param; threads through to `BLEPoller`
  construction at `tui.py:5866`
- `tests/test_ble.py` — new tests for the four gate semantics
  (default 5s suppresses, 0 disables, named bypass, connected
  bypass)
- `tests/test_cli.py` — flag parsing tests

## Out of scope

- **RPA rotation dedup.** A separate change. A static nearby
  iPhone rotates its Continuity address every ~15 min; each
  rotation lasts long enough to graduate through any reasonable
  gate, so the presence gate alone does NOT suppress these.
  See follow-up: anonymous-vendor coalescing by (vendor, ±10 dBm
  RSSI window) for the events stream. Out of scope here so the
  PR stays focused on a single semantic shift.
