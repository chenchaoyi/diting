# capture-sampling — design

## Decisions

- **Throttle inside the EventLogger, compute in the consumer.** `emit_link_sample`
  and `emit_scan_summary` hold their own last-emit timestamps and drop calls
  that arrive before `interval_s` (default 60 s) elapses — so both the `monitor`
  and TUI consumers can call them every poll without flooding the log, and the
  cadence lives in one place. The consumer supplies the data (the connection for
  the sample; neighbor / co-channel counts for the summary).
- **Local-only via `_emit_local`.** Both new types are written through a
  sink-only path that skips the observer fan-out, so the companion sink never
  sees them — no salience gating to rely on, no chance of an unknown type
  reaching `validate_event`, no protocol change. They exist purely in the JSONL.
- **`link_sample` reuses the nested `quality` shape.** `{type:"link_sample",
  ts, bssid, quality:{rssi_dbm, …}}` — same `quality` object `link_state`
  carries, so a consumer reads quality uniformly. Emitted only while associated
  (no point sampling a dead link).
- **`scan_summary` shape.** `{type:"scan_summary", ts, neighbor_count,
  co_channel_count, current_channel}`. `neighbor_count` = visible BSSIDs in the
  pass; `co_channel_count` = how many share the current connection's channel
  (0 / null when not associated or channel unknown). The consumer computes both
  from the `ScanUpdate` results + the tracked current channel.
- **Cadence is best-effort, not guaranteed.** 60 s is a sampling floor, not a
  scheduler — samples ride existing poll/scan ticks, so the real spacing is
  `max(60 s, tick interval)`. Good enough for a distribution; avoids a dedicated
  timer task.

## Risks / Trade-offs

- [Log-size growth] → ~60 link_samples/hour + ~60 scan_summaries/hour is
  trivial next to the BLE event volume; the 60 s floor keeps it bounded.
- [Co-channel needs the current channel] → tracked from the latest
  ConnectionUpdate; when unknown (unassociated / no channel), `co_channel_count`
  is null and the consumer still logs neighbor_count.
- [Duplication across monitor + TUI consumers] → the throttle + payload build
  live in EventLogger; each consumer just calls the emitter, so the logic isn't
  copied.
