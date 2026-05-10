# Document the `inventory` capability

## Why

The AP-attribution chain in `network.py` is deceptively complex
(four resolution paths in order, with cluster labels as the
graceful fallback) and has changed twice since v0.6.0 — once to add
the mid-four-octet rule for vendors that don't follow same-prefix
conventions, once to add the cluster-label stability invariant. The
`aps.yaml` schema is documented in `aps.example.yaml` but the
resolution semantics (override-wins, format-normalisation,
case-folding) are buried in code. Backfill makes those contracts
explicit.

## What Changes

- Introduce capability `inventory`.
- No code changes — backfill from `src/wifiscope/network.py`.

## Capabilities

### New Capabilities
- `inventory`: aps.yaml loading, four-path AP-name resolution,
  cluster-label stability, OUI-vendor lookup, BSSID format
  normalisation.

### Modified Capabilities
None.

## Impact

- Affected code: none (documentation-only)
- Affected specs: creates `openspec/specs/inventory/spec.md`
- Cross-cuts with: `wifi-scanning` (consumes resolved AP names in
  the panel), `bluetooth-scanning` (uses `lookup_ap_vendor` for
  connected-peripheral OUI), `roam-detection` (compares same-SSID
  candidates by AP name)
- Future impact: any change to the resolution-path order or
  cluster-label algorithm MUST file a MODIFIED Requirement
