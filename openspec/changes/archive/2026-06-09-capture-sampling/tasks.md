# capture-sampling — tasks

## 1. Test plan first

- [x] 1.1 TESTING.md rows (EN) — link_sample throttled + nested quality +
      local-only; scan_summary neighbor/co-channel + local-only
- [x] 1.2 Mirror in docs/zh/TESTING.md
- [x] 1.3 Tests: link_sample throttles to one per window; bypasses observer;
      scan_summary counts + co-channel; bypasses observer

## 2. Implement

- [x] 2.1 `_emit_local` (sink-only, skips observers + salience stamp)
- [x] 2.2 `emit_link_sample(conn, *, now, interval_s=60)` — throttled, nested
      quality, only while associated; `_last_link_sample` state
- [x] 2.3 `emit_scan_summary(*, neighbor_count, co_channel_count,
      current_channel, now, interval_s=60)` — throttled; `_last_scan_summary`
- [x] 2.4 `_run_monitor`: track current channel; call both emitters from the
      Connection / Scan consumers
- [x] 2.5 TUI consumer: same calls

## 3. Verify

- [x] 3.1 `uv run pytest` (companion conformance — protocol untouched)
- [x] 3.2 run `diting monitor` briefly → link_sample + scan_summary present,
      not pushed to companion
- [x] 3.3 `tui_snapshot --mode regression`
- [x] 3.4 `openspec validate --specs --strict` + the change
