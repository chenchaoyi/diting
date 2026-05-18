## ADDED Requirements

### Requirement: The Connection panel SHALL hide the Max field when CoreWLAN reports `Max < Tx`
The connection-panel renderer SHALL detect the case where `Connection.tx_rate_mbps > Connection.max_link_speed_mbps` — a known CoreWLAN flakiness on macOS 26 where `maximumLinkSpeed()` returns a stale / under-reported value while `transmitRate()` returns the current (higher) PHY rate. In that case the renderer SHALL surface the Tx half alone as `Tx <rate> Mbps`, omitting the trailing ` / <smaller> Mbps`. The "Tx and Max use different CoreWLAN APIs and may diverge" footnote SHALL remain — when Max is plausibly conservative-but-not-wrong (Max ≥ Tx, or Max is None), the row continues to render both numbers.

The behaviour SHALL be purely renderer-side: `Connection.max_link_speed_mbps` is unchanged at the model layer; only the `Tx / Max` row visually omits Max when the inconsistency is detected.

#### Scenario: macOS 26 reports Tx 286 / Max 229
- **WHEN** `transmit_rate_mbps=286.0` and `max_link_speed_mbps=229` on the same `Connection`
- **THEN** the rendered Tx / Max row reads `Tx 286.0 Mbps` (no `/ 229 Mbps` suffix); the `(idle)` annotation logic and the row label are unchanged

#### Scenario: Max greater than or equal to Tx renders both
- **WHEN** `transmit_rate_mbps=144.0` and `max_link_speed_mbps=867` (the typical healthy case)
- **THEN** the rendered Tx / Max row reads `Tx 144.0 Mbps  /  867 Mbps`

#### Scenario: Max unknown renders Tx alone
- **WHEN** `max_link_speed_mbps is None` (CoreWLAN selector unavailable on older macOS)
- **THEN** the rendered row reads `Tx <rate> Mbps  /  n/a` — pre-existing behaviour, unchanged
