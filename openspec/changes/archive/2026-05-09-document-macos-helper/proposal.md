# Document the `macos-helper` capability

## Why

The Swift helper bundle is wifiscope's foundation — every other
capability (Wi-Fi scanning, BLE scanning, BLE detail modal, link
health, decoders) depends on it owning the macOS TCC permissions and
brokering data over a subprocess pipe. The contract is currently
implicit in `helper/Sources/wifiscope-helper/main.swift` (~1000 lines
of Swift) plus tribal knowledge ("don't move the bundle to
`/Applications/`", "schema 3 is current", "exit code 3 means denied").
Backfilling lets a future Linux / Android / Windows port reproduce
the bundle's contract verbatim and protects the existing helper from
accidental regressions during refactors.

## What Changes

- Introduce capability `macos-helper`.
- No code changes — pure backfill from `helper/Sources/wifiscope-helper/main.swift`,
  `src/wifiscope/_helper.py`, and the `helper/build.sh` install path.

## Capabilities

### New Capabilities
- `macos-helper`: Swift helper bundle — TCC ownership, subprocess
  contract, JSON / JSONL output schemas, install / cdhash invariant.

### Modified Capabilities
None.

## Impact

- Affected code: none (documentation-only)
- Affected specs: creates `openspec/specs/macos-helper/spec.md` on archive
- Cross-cuts with: `wifi-scanning` (consumes `wifi-scan` subcommand),
  `bluetooth-scanning` (consumes `ble-scan` JSONL stream),
  `ble-decoders` (consumes the schema-4 raw passthrough fields)
- Future impact: any change to the helper's subprocess interface,
  schema integers, or TCC requirements MUST file a MODIFIED Requirement
  against this capability before merging
