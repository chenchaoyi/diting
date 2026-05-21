# fix-ble-left-dedup

## Why

A 5.6 h capture session in a dense BLE environment produced 67,548
events — 99.97 % of them BLE — and a 13 MB JSONL file. Breakdown:

| type | count |
|---|---|
| `ble_device_left` | 55,191 |
| `ble_device_seen` | 12,348 |
| everything else | 24 |

Every one of the 12,348 unique identifiers emitted exactly one
`seen` event, but their `left` events ran from 1 to **229** per
identifier. The implementation in `BLEPoller._detect_transitions`
(`src/diting/ble.py:1468-1528`) re-emits `BLEDeviceLeftEvent`
every TTL cycle for an identifier that flaps in and out of
`_devices`:

1. Tick N: advert arrives → `_devices[ident]` populated → seen
   fires, identifier added to `_seen_identifiers`.
2. Tick N+k: TTL elapses → `expire_devices` removes ident →
   `_detect_transitions` emits left.
3. Tick N+k+1: another advert from the same ident (edge-of-range
   device whose adverts the macOS stack briefly dropped) →
   `_devices[ident]` re-populated. `_seen_identifiers` already
   has it, so no fresh seen.
4. Tick N+k+M: TTL elapses again → another left fires.
5. Repeats until the device permanently leaves range.

For one identifier we observed this cycle 229 times. Across the
session it accounts for ~43,000 spurious left events (≈ 78 % of
all left events).

The current spec (`bluetooth-scanning/spec.md`, "Requirement:
BLEPoller SHALL emit transition events") is silent on the
flap-after-left case. The implementation falls through to the
broken behaviour above.

## What changes

- Tighten the `bluetooth-scanning` spec: an identifier emits
  at most **one** `BLEDeviceLeftEvent` per `BLEDeviceSeenEvent`.
  After a `left` has fired for an identifier, subsequent
  re-appearances and re-evictions of the same identifier in the
  same session are silent. (Matches the "bug fix only" scope
  the user picked — preserves the "no debounce" contract for
  the first seen-left pair.)
- Implement the dedup gate in `_detect_transitions` via a new
  `_departed_identifiers: set[str]`.
- Add unit tests covering: flap (seen → left → re-appears →
  evicts again → silent), and the existing one-seen-one-left
  path (still passes).

## Impact

- **JSONL log size** in dense environments drops by roughly the
  ratio observed above — for the captured session, 67,548 → 25,000
  events (-63 %), 13 MB → ~4.8 MB.
- **`diting analyze` cross-session output** stops double-counting
  the same identifier under "top BLE contributors" / daily-trend
  ranking. The top BLE contributors today are dominated by
  flapping identifiers, not by devices that actually came and
  went many times.
- **No new dependencies**, no public API change, no CLI surface
  change. Schema stays at 4.
- **Affected code**: `src/diting/ble.py`, `tests/test_ble.py`.

## Affected code

- `src/diting/ble.py:1468-1528` — `_detect_transitions`
- `src/diting/ble.py:1338` — `_seen_identifiers` declaration
  (companion `_departed_identifiers` added beside it)
- `tests/test_ble.py:1444-1556` — transition tests
