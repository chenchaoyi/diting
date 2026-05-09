# Document the `event-log` capability

## Why

The JSONL writer is the second-most consumed integration surface
after the TUI itself — users pipe `wifiscope monitor` into Home
Assistant, into Loki / Promtail, into shell `jq` filters. The wire
format and crash semantics are stable but pinned only by the
`EventLogger` class and a couple of test cases. The locale-stable
English keys / ensure_ascii=False / local-TZ-ISO timestamp / atexit
flush invariants all carry user-facing consequences (a Chinese SSID
mojibake'd into the log is a real user complaint, not a theoretical
one).

## What Changes

- Introduce capability `event-log`.
- No code changes — backfill from `src/wifiscope/event_log.py` and
  the writer's call sites in `tui.py` / `cli.py`.

## Capabilities

### New Capabilities
- `event-log`: JSONL writer contract — flush-after-every-event
  durability, atexit cleanup, locale-stable schema, local-TZ
  timestamps, `connection_update` log-only event type.

### Modified Capabilities
None.

## Impact

- Affected code: none (documentation-only)
- Affected specs: creates `openspec/specs/event-log/spec.md`
- Cross-cuts with: `events` (defines what events look like in
  memory), `analyze` (consumes the JSONL stream), `cli` (wires
  `--log` and `wifiscope monitor`)
- Future impact: any change to JSONL key names, timestamp format,
  or flush behaviour MUST file a MODIFIED Requirement
