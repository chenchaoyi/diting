# Document the `ble-decoders` capability

## Why

The decoder framework landed this week (along with iBeacon, Eddystone,
Apple Continuity, Microsoft CDP, and RuuviTag decoders). Pinning the
contract NOW — before more decoders pile in — makes future
contributions cheap: a new vendor decoder is a 30-line file with a
known shape, not a UI patch. The "register-as-decorator + protocol-
namespaced keys + never-raise" pattern is a load-bearing convention;
without a spec it would erode within a few PRs.

The MS CDP / Apple Continuity decoders also encode an explicit
"don't claim semantics for bits where public docs disagree" stance.
That's a deliberate restraint — without spec'ing it, future decoder
PRs would creep in plausible-but-fragile bit interpretations and
silently mislead users on iOS / Windows version transitions.

## What Changes

- Introduce capability `ble-decoders`.
- No code changes — backfill from `src/wifiscope/decoders/` and
  the modal's decoded-payload section in `src/wifiscope/tui.py`.

## Capabilities

### New Capabilities
- `ble-decoders`: per-protocol decoder registry, namespaced output
  schema, exception-safe execution, the five bundled decoders
  (iBeacon, Eddystone, Apple Continuity, Microsoft CDP, RuuviTag),
  and the "no semantic claims on shifty bits" restraint.

### Modified Capabilities
None.

## Impact

- Affected code: none (documentation-only)
- Affected specs: creates `openspec/specs/ble-decoders/spec.md`
- Cross-cuts with: `bluetooth-scanning` (provides the schema-4 raw
  fields the decoders consume), `ble-detail-modal` (consumes
  `decode_all` output for the Decoded payload section)
- Future impact: adding a new decoder is now a no-spec-change PR
  (the framework contract permits it). REMOVING a decoder, changing
  output namespacing, or relaxing the never-raise rule MUST file a
  MODIFIED Requirement
