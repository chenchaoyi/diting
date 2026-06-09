# capture-context — tasks

## 1. Test plan first

- [x] 1.1 TESTING.md rows (EN) — session_meta manifest + permissions;
      associated link_state quality fields; quality stripped before wire
- [x] 1.2 Mirror in docs/zh/TESTING.md
- [x] 1.3 Tests: emit_session_meta writes monitors+permissions; associated
      link_state carries rssi/channel/band(+snr); companion sink strips them

## 2. Implement

- [x] 2.1 `LOCAL_ONLY_FIELDS` += quality keys (rssi_dbm, noise_dbm, snr_db,
      tx_rate_mbps, channel, channel_width_mhz, channel_band, phy_mode)
- [x] 2.2 `emit_session_meta(monitors=…, permissions=…)` writes the manifest
- [x] 2.3 `emit_connection_update` associated payload gains quality (both the
      first-poll synthetic and the transition branch); SNR = rssi − noise
- [x] 2.4 `cli._run_monitor` assembles the manifest (active monitors + cadence +
      permission) and passes it to emit_session_meta

## 3. Verify

- [x] 3.1 `uv run pytest` (incl. companion conformance — protocol untouched)
- [x] 3.2 run `diting monitor` briefly → session_meta has monitors, link_state
      has quality; companion fixtures unchanged
- [x] 3.3 `tui_snapshot --mode regression`
- [x] 3.4 `openspec validate --specs --strict` + the change
