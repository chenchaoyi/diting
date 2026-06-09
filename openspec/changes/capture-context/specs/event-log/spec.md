# event-log delta — capture-context

## ADDED Requirements

### Requirement: `session_meta` SHALL carry a monitoring-coverage manifest
The `session_meta` event SHALL include a `monitors` object and a `permissions`
object so downstream tools can tell "monitored and quiet" from "never
monitored." `monitors` SHALL map each signal source diting can observe (at
least `wifi`, `ble`, `lan`, `latency`, `rf_stir`) to an object whose `active`
boolean states whether that source was running this session; cadence / target
extras (e.g. `scan_interval_s`, `targets`) MAY be included. `permissions` SHALL
record the location-grant state (`granted` / `denied` / `fallback`). Older logs
that lack these objects remain valid — absence means "coverage unknown."

#### Scenario: session_meta declares active monitors
- **WHEN** a session runs with Wi-Fi + BLE + latency monitoring
- **THEN** the `session_meta` line carries `monitors.wifi.active == true`, `monitors.ble.active == true`, `monitors.latency.active == true`, and a `permissions.location` value

#### Scenario: an inactive monitor is recorded as such
- **WHEN** LAN active-probing is off for the session (e.g. public scene)
- **THEN** `monitors.lan.active` is `false`, so a downstream reader knows LAN silence is "not probed," not "nothing there"

### Requirement: The `associated` `link_state` SHALL carry steady-state connection quality
When the writer emits an `associated` `link_state`, it SHALL include the
steady-state signal quality from the live `Connection` (when available) under a
single nested `quality` object — at least RSSI (dBm), noise (dBm), SNR (dB,
derived from rssi − noise), tx-rate, channel, channel-width, band, and PHY mode.
The `quality` object SHALL be local-only: `quality` is listed in
`LOCAL_ONLY_FIELDS` so the companion sink strips it before sealing, exactly as
`security` is handled. A nested object (rather than bare `rssi_dbm` etc.) is
required so it does NOT collide with the legitimate wire `rssi_dbm` field on
`ble_device_seen`. The quality enriches the JSONL but never reaches the
companion wire, so the versioned protocol is unchanged. A quality sub-field
absent from the connection is omitted.

#### Scenario: associated link_state records signal quality in the JSONL
- **WHEN** diting associates and the connection reports RSSI / channel / band
- **THEN** the JSONL `associated` `link_state` line carries a `quality` object with `rssi_dbm`, `channel`, `channel_band` (and `snr_db` when noise is known)

#### Scenario: the quality object never reaches the companion wire
- **WHEN** that same `link_state` payload is offered to the companion sink
- **THEN** the sealed wire payload contains no `quality` key (it's in `LOCAL_ONLY_FIELDS`), and the wire `rssi_dbm` on `ble_device_seen` is unaffected
