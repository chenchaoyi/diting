# Document the `environment-monitor` capability

## Why

The RF-stir detector is a load-bearing diagnostic — it sources the
Environment line of the Diagnostics panel, the Events strip's
[STIR] entries, and the per-AP σ baseline modal. The spike-detection
threshold logic (ratio AND absolute, with cooldown + rearm) was
arrived at empirically; getting any of the four constants wrong
flips the false-positive rate. The "correlation, never causation"
wording is a deliberate ethical stance — without spec'ing it, future
contributors might describe stir as motion / presence detection,
which the signal does not support.

## What Changes

- Introduce capability `environment-monitor`.
- No code changes — backfill from `src/wifiscope/environment.py`
  and the rendering call sites in `tui.py`.

## Capabilities

### New Capabilities
- `environment-monitor`: σ rolling-baseline detector, three-tier
  fusion mode classification, ratio-AND-floor spike rule, cooldown
  + rearm anti-flap, calibration loading, the
  correlation-not-causation wording invariant.

### Modified Capabilities
None.

## Impact

- Affected code: none (documentation-only)
- Affected specs: creates `openspec/specs/environment-monitor/spec.md`
- Cross-cuts with: `events` (emits `RFStirEvent`), `wifi-scanning`
  (consumes the scan stream as RSSI input), `tui-shell`
  (renders the Environment line + the σ baseline modal)
- Future impact: any change to the threshold constants, fusion-mode
  RSSI cuts, or the wording stance MUST file a MODIFIED Requirement
