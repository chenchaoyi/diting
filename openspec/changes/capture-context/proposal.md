# capture-context

## Why

When an AI reads a diting log and sees no `roam` / `rf_stir` / `latency_spike`,
it can't tell "monitored and quiet" (a healthy signal) from "never monitored"
— so it correctly refuses to say anything about mobility / RF motion / jitter.
And for a static single-BSSID session the log carries no signal *quality* at
all: `link_state` records `ssid/bssid/vendor/security` but drops the RSSI /
noise / SNR / channel / band / PHY the `Connection` already holds. The most
useful facts about a quiet session are simply not written.

## What Changes

- **`session_meta` gains a monitoring-coverage manifest.** A `monitors` block
  declares which signal sources were active for the session (wifi / ble / lan /
  latency / rf_stir) plus the scan cadence, and a `permissions` block records
  the location grant state. This lets a downstream consumer read "no
  latency_spike" as "latency was monitored and clean," not "unknown."
- **The `associated` `link_state` gains steady-state quality.** RSSI, noise,
  SNR (derived), tx-rate, channel, channel-width, band, and PHY mode from the
  live `Connection` are written onto the event. All local-only (added to
  `LOCAL_ONLY_FIELDS`) — they enrich the JSONL but never reach the companion
  wire, so the versioned protocol is untouched.

## Capabilities

### Modified Capabilities

- `event-log`: `session_meta` SHALL carry a monitoring-coverage manifest +
  permission state; the `associated` `link_state` SHALL carry steady-state
  connection quality (local-only).

## Out of scope

- Periodic `link_sample` events + `scan_summary` neighbor context (next change,
  `capture-sampling`).
- analyze consuming these fields into report sections (`analyze-observability`).

## Impact

- `src/diting/event_log.py` — `emit_session_meta` (manifest + permissions);
  `emit_connection_update` associated payload (quality fields).
- `src/diting/companion/protocol/events_schema.py` — extend `LOCAL_ONLY_FIELDS`
  with the quality keys so they're stripped before the wire.
- `src/diting/cli.py` — assemble the manifest (active monitors + permission)
  and pass it to `emit_session_meta`.
- `tests/test_event_log.py` + `tests/TESTING.md` (EN + ZH).
