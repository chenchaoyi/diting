# event-log delta — capture-sampling

## ADDED Requirements

### Requirement: The writer SHALL emit periodic `link_sample` events while associated
While the host is associated, the writer SHALL emit `link_sample` events at a
bounded cadence (default floor 60 s) carrying the nested `quality` object (the
same shape `link_state` uses: RSSI / noise / SNR / tx-rate / channel / width /
band / PHY) plus the current `bssid`. This yields a quality distribution over a
session rather than the single join-time snapshot. `link_sample` is a local-only
event type — emitted through a sink-only path that bypasses the companion
observer, so it never reaches the versioned wire. Calls that arrive before the
cadence floor elapses SHALL be dropped (throttled).

#### Scenario: link_sample is throttled to the cadence floor
- **WHEN** the connection consumer calls the sample emitter on every poll for a steady association
- **THEN** at most one `link_sample` is written per cadence window, each with a `quality` object and the current `bssid`

#### Scenario: link_sample never reaches the companion wire
- **WHEN** a `link_sample` is emitted with the companion observer attached
- **THEN** the observer is not invoked for it (sink-only); only the JSONL records it

### Requirement: The writer SHALL emit `scan_summary` events with neighbor and co-channel counts
On scan passes (throttled to the same cadence floor), the writer SHALL emit a
`scan_summary` event recording `neighbor_count` (visible BSSIDs in the pass) and
`co_channel_count` (how many of them share the current connection's channel,
null when not associated / channel unknown) plus `current_channel`. This gives
interference context that roam events cannot. `scan_summary` is local-only
(sink-only emit, never pushed).

#### Scenario: scan_summary records neighbor and co-channel counts
- **WHEN** a scan pass sees N BSSIDs and the host is associated on channel C
- **THEN** a (throttled) `scan_summary` is written with `neighbor_count == N`, `current_channel == C`, and `co_channel_count` equal to the number of BSSIDs on channel C

#### Scenario: scan_summary is local-only
- **WHEN** a `scan_summary` is emitted with the companion observer attached
- **THEN** the observer is not invoked (sink-only); only the JSONL records it
