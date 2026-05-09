# Document the `events` capability

## Why

The unified event vocabulary is wifiscope's diagnostic spine — the
TUI's events strip, the modal browser, the JSONL log, and the
analyzer all read from it. The five-event schema (`roam`, `rf_stir`,
`latency_spike`, `loss_burst`, `link_state`) is settled but has never
been pinned: a future contributor adding a sixth type, or renaming a
field, could silently break the analyzer's heuristics or
shell-pipeline filters users have built on top of `wifiscope monitor
| jq`. Backfill captures the contract.

## What Changes

- Introduce capability `events`.
- No code changes — backfill from `src/wifiscope/events.py` and the
  ring-buffer / JSONL writer behaviour.

## Capabilities

### New Capabilities
- `events`: the five-event vocabulary, the in-memory ring buffer,
  and the locale-stable JSONL serialisation contract.

### Modified Capabilities
None.

## Impact

- Affected code: none (documentation-only)
- Affected specs: creates `openspec/specs/events/spec.md`
- Cross-cuts with: `link-health` (emits `latency_spike` /
  `loss_burst`), `environment-monitor` (emits `rf_stir`),
  `event-log` (writes the JSONL stream), `analyze` (reads it back)
- Future impact: adding a new event type or renaming a JSONL field
  MUST file a MODIFIED Requirement
