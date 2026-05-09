# Document the `wifi-scanning` capability

## Why

Wi-Fi scanning is wifiscope's original raison d'être and the data
substrate every other diagnostic capability builds on (current link,
roam scoring, environment monitor, events). The contract is implicit
in `src/wifiscope/macos_backend.py`, the helper's `wifi-scan`
subcommand, and the redaction-handling fan-out across `tui.py`. The
existing `docs/specs/v0.7.0-network-ground-truth-and-environment-monitor.md`
describes one-shot release goals but doesn't anchor the long-lived
contract for what a scan row promises.

## What Changes

- Introduce capability `wifi-scanning`.
- No code changes — backfill from `src/wifiscope/macos_backend.py`,
  `helper/Sources/wifiscope-helper/main.swift` (the `wifi-scan`
  subcommand), and `src/wifiscope/poller.py`.

## Capabilities

### New Capabilities
- `wifi-scanning`: CoreWLAN-driven scanning, beacon IE plumbing,
  redaction handling, throttle compliance, current-BSSID merge.

### Modified Capabilities
None.

## Impact

- Affected code: none (documentation-only)
- Affected specs: creates `openspec/specs/wifi-scanning/spec.md`
- Cross-cuts with: `macos-helper` (provides `wifi-scan` subcommand),
  `link-health` (consumes Connection from scan), `roam-detection`
  (scores against scan results), `environment-monitor` (per-AP RSSI σ
  baseline derived from the scan stream)
- Future impact: any change to scan field shape, redaction handling,
  or throttle behaviour MUST file a MODIFIED Requirement
