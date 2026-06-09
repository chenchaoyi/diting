# analyze-observability — design

## Decisions

- **Three new summaries on `Report` (appended, defaulted).** `CoverageSummary`
  (the `monitors` manifest + `permissions` + a `signal_events` count map),
  `ConnectionQualitySummary` (rssi p50/min/max, snr p50, channel/band/phy/
  security/ssid/bssid, sample count), `NeighborSummary` (neighbor /co-channel/
  current_channel + sample count). All `None` when the source data is absent,
  so older logs and short sessions render unchanged.
- **Negative-space is computed in render, from structured data.** `analyze`
  stores the manifest + a `{signal: observed_event_count}` map; the renderer
  produces the localized verdict ("monitored, 0 events → …"). This keeps the
  prose out of the dataclass (so it localizes cleanly EN/ZH) and the mapping in
  one place: `latency → {latency_spike, loss_burst}`, `rf_stir → {rf_stir}`,
  `wifi → {roam}`, `ble → {ble_device_seen}`, `lan → {lan_host_*}`.
- **Quality distribution from both sources.** RSSI / SNR samples come from every
  `link_state.quality` AND `link_sample.quality`; the steady channel / band /
  PHY / security / ssid / bssid are taken from the last associated reading.
  Percentiles reuse the existing `_percentile` helper. Omitted when no quality
  was logged.
- **Neighbors from the last non-null `scan_summary`.** Latest reading is the
  headline (neighbor + co-channel + channel); sample count conveys how many
  passes backed it.
- **Renders gate on presence, like the cross-session blocks.** Each section
  renders only when its summary is non-None, so a pre-observability log (or a
  `--json`-only consumer) is unaffected. The LLM prompt gains one line telling
  the model to read the coverage section so "no events" is interpreted as
  "monitored & quiet."
- **Localization follows `--lang`** (the LLM document already does). Section
  headers / labels go through `t()` with ZH entries (audit guard enforces
  parity); technical tokens (event-type names, band strings) stay verbatim.

## Risks / Trade-offs

- [Manifest may be absent on old logs] → every section is None-gated; absence =
  the pre-change report.
- [Negative-space could mislead if a monitor was active but produced no events
  for a real reason] → the verdict states the fact ("monitored, 0 events") and a
  cautious interpretation, never an assertion; this mirrors the existing
  insight tone.
