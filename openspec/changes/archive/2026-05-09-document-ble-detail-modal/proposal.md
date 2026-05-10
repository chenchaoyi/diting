# Document the `ble-detail-modal` capability

## Why

The detail modal landed this week as Phase A1 of the "user can drill
into one device" feature track. It's a small but load-bearing surface:
keyboard + mouse selection, priority binding to win over scroll,
section ordering, decoded-payload integration, and the RSSI sparkline
all need to stay stable as future phases extend it (Apple AirPods
battery, Eddystone URL launch, history charts).

Without a spec the next contributor would be tempted to:

- Add a row index-based cursor (which would jump devices on snapshot
  resorts — exactly the bug we avoided).
- Render `ad count: 0` for connected peripherals (which previously
  read as a bug to users).
- Drop the priority binding (which would silently break keyboard
  navigation again — the `up`/`down` collision with VerticalScroll
  is non-obvious).
- Skip the (anonymous)/(unknown) distinction in the Identity section.

This spec captures all of those invariants.

## What Changes

- Introduce capability `ble-detail-modal`.
- No code changes — backfill from `BLEDetailScreen` and the
  `action_ble_*` / `_ble_set_selected` methods in `src/wifiscope/tui.py`.

## Capabilities

### New Capabilities
- `ble-detail-modal`: per-device inspect modal — selection by
  identifier, keyboard nav with priority bindings, mouse
  click-to-inspect, section ordering, RSSI sparkline gating,
  distance-estimate labelling.

### Modified Capabilities
None.

## Impact

- Affected code: none (documentation-only)
- Affected specs: creates `openspec/specs/ble-detail-modal/spec.md`
- Cross-cuts with: `bluetooth-scanning` (consumes `BLEDevice` +
  `BLEHistory`), `ble-decoders` (consumes `decode_all` output)
- Future impact: phase A2 (history time-series chart), phase B
  (semantic decoders that emit user-friendly fields), phase C
  (vendor-specific decoders) all extend this modal without
  changing the section ordering. Adding a section MUST file a
  MODIFIED Requirement
