# capture-context — design

## Decisions

- **Manifest lives in `session_meta`, not per-event.** Coverage is session-wide
  context, so it rides the existing header — no per-event overhead. Shape:
  ```json
  "monitors": {
    "wifi":    {"active": true, "scan_interval_s": 5.0},
    "ble":     {"active": true, "presence_gate_s": 5.0},
    "lan":     {"active": true},
    "latency": {"active": true, "targets": ["gateway", "wan"]},
    "rf_stir": {"active": true}
  },
  "permissions": {"location": "granted"}
  ```
  `active` is the load-bearing field (monitored vs not); cadence/targets are
  best-effort extras. Values are what the CLI knows at startup; `latency` is
  marked active because the monitor always spins up gateway/WAN probing once a
  gateway is known. Older logs simply lack `monitors` — consumers treat absence
  as "unknown coverage," which is the pre-change behavior.
- **Quality rides a nested local-only `quality` object.** RSSI / noise / SNR /
  tx-rate / channel / channel-width / band / PHY go under a single `quality`
  object on the `associated` `link_state`, and `quality` (the one key) is added
  to `LOCAL_ONLY_FIELDS` so the companion sink strips it before sealing — the
  pattern `security` already uses. A **nested** object is deliberate: the bare
  names would collide with the legitimate wire `rssi_dbm` on `ble_device_seen`
  (adding `rssi_dbm` to `LOCAL_ONLY_FIELDS` would strip it from BLE events too).
  The JSONL keeps `quality`; the wire never sees it; the protocol fixtures /
  manifest are byte-unchanged. SNR = `rssi_dbm - noise_dbm` when both present.
- **`None` written through, not skipped.** Matches the existing event schema —
  consumers distinguish "not known" from "not measured." A quality field absent
  from the connection is omitted (not measured); a present-but-null stays null.
- **No companion / protocol change.** `session_meta` is never pushed (no
  pushable salience), and the quality keys are local-only. The companion
  fixtures and `manifest.json` are untouched — verified by the protocol
  conformance tests still passing.

## Risks / Trade-offs

- [Manifest drifts from reality] → `active` reflects what the CLI actually wired
  up at startup; a test asserts the manifest matches the monitors the monitor
  loop starts. It's best-effort context, not a contract.
- [Quality fields leak to companion] → covered by `LOCAL_ONLY_FIELDS` + the
  sink's strip step; a test asserts a sealed link_state payload carries none of
  the quality keys.
