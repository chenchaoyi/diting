# analyze delta — analyze-observability

## ADDED Requirements

### Requirement: analyze SHALL synthesize a monitoring-coverage / negative-space section
The analyzer SHALL read `session_meta.monitors` + `permissions` and report, for
each *active* monitor, how many events of its kind occurred — and when that
count is zero, state that the signal was monitored and quiet rather than
unknown (e.g. "latency probed, 0 spikes/bursts → link stable"; "rf_stir active,
0 events → static environment"). A monitor that was not active SHALL be marked
"not observed," distinct from "monitored & quiet." This section SHALL appear in
the terminal report, the `--for-llm` document, and `--json`, and the analyst
prompt SHALL reference it so the model reads silence correctly. Logs without a
`monitors` manifest SHALL render as before (section omitted).

#### Scenario: zero events under an active monitor reads as "monitored & quiet"
- **WHEN** a log's `session_meta` marks `latency.active == true` and the log has no `latency_spike` / `loss_burst` events
- **THEN** the coverage section reports latency as monitored with zero spikes — framed as a stable-link signal, not "unknown"

#### Scenario: an inactive monitor is "not observed"
- **WHEN** `session_meta` marks `lan.active == false`
- **THEN** the coverage section marks LAN "not observed," NOT "nothing on the LAN"

### Requirement: analyze SHALL report steady-state connection quality
The analyzer SHALL aggregate the `quality` objects from `link_state` and
`link_sample` events into a connection-quality summary — at least RSSI p50 /
min / max, SNR p50, and the steady channel / band / PHY / security — and render
it in the terminal report, the `--for-llm` document, and `--json`. When no
`quality` data is present (older logs), the summary SHALL be omitted.

#### Scenario: connection quality reports an RSSI distribution
- **WHEN** a session logged several `link_sample` quality readings
- **THEN** the connection-quality section reports RSSI p50 (with min / max) and the steady channel / band, so a static session conveys signal strength

### Requirement: analyze SHALL report neighbor / co-channel context
The analyzer SHALL read `scan_summary` events into a neighbor summary — neighbor
count, co-channel count, and the current channel — and render it in the report,
the `--for-llm` document, and `--json`. Absent `scan_summary` data SHALL omit
the section.

#### Scenario: neighbor section conveys interference context
- **WHEN** the log's `scan_summary` events show N neighbors with M on the current channel
- **THEN** the neighbors section reports N neighbors / M co-channel, giving interference context even when no roam occurred
