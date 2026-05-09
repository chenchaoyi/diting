# Document the `bluetooth-scanning` capability

## Why

The BLE scanning layer in `src/wifiscope/ble.py` has grown several
layers of resolution / fallback / merging logic over the v0.5–v0.8
arc and the contract is now both load-bearing and subtle:

- Vendor resolution is a 5-step chain (cid → member-UUID →
  service_data UUID → name pattern → carry-forward) and the order is
  *significant*. Re-ordering would silently change which devices show
  vendor names.
- Schema-4 raw passthrough fields (`manufacturer_hex`, `service_data`,
  `tx_power_dbm`, `solicited_service_uuids`, `overflow_service_uuids`)
  are the API surface for the decoder framework. Removing or
  renaming any of them breaks decoders silently.
- The "(anonymous)" vs "(unknown)" placeholder distinction was added
  this week and is now load-bearing for the inspector's
  truly-silent vs actionable-unresolved buckets.
- `BLEHistory` was added for the detail-modal sparkline; its capping
  and pruning behaviour is a real memory invariant on long sessions.

Backfill makes those invariants explicit so a future refactor can't
silently break them.

## What Changes

- Introduce capability `bluetooth-scanning`.
- No code changes — backfill from `src/wifiscope/ble.py` and the
  poller event flow in `src/wifiscope/tui.py`.

## Capabilities

### New Capabilities
- `bluetooth-scanning`: BLE advertisement → `BLEDevice` pipeline,
  vendor resolution chain, anonymous-vs-unknown distinction, schema-4
  raw passthrough plumbing, RSSI smoothing, history capping.

### Modified Capabilities
None.

## Impact

- Affected code: none (documentation-only)
- Affected specs: creates `openspec/specs/bluetooth-scanning/spec.md`
- Cross-cuts with: `macos-helper` (consumes ble-scan stream),
  `ble-decoders` (consumes schema-4 raw fields),
  `ble-detail-modal` (consumes `BLEHistory.get` per device)
- Future impact: any change to the vendor resolution chain order,
  the schema-4 field shape, or the anonymous/unknown semantics
  MUST file a MODIFIED Requirement
