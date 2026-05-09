# Document the `link-health` capability

## Why

Active link probing is the second-most-load-bearing capability after
scanning — the events ring, the JSONL analyzer, the diagnostic-row
"is the link healthy?" status, and the failure-mode messaging all
depend on the contract `LatencyPoller` produces. The "WAN n/a (DNS
== gateway)" handling is non-obvious and was already a real gap on
home networks; the rolling-window monotonic-clock fix landed in
0.7.0; the network-change-resets-probes invariant landed during the
overnight log work. None of this is captured anywhere except in
code comments.

## What Changes

- Introduce capability `link-health`.
- No code changes — backfill from `src/wifiscope/latency.py` and the
  `_link_diagnostic_line` rendering in `src/wifiscope/tui.py`.

## Capabilities

### New Capabilities
- `link-health`: gateway/WAN ICMP+TCP probing, rolling-window
  aggregates, monotonic-clock eviction, network-change reset,
  latency-spike / loss-burst / unreachable event emission.

### Modified Capabilities
None.

## Impact

- Affected code: none (documentation-only)
- Affected specs: creates `openspec/specs/link-health/spec.md`
- Cross-cuts with: `wifi-scanning` (consumes Connection for gateway
  IP), `events` (consumes the spike/loss events), `event-log`
  (logs them as JSONL)
- Future impact: any change to the rolling-window length, probe
  cadence, or event thresholds MUST file a MODIFIED Requirement
