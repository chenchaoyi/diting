## MODIFIED Requirements

### Requirement: Calibration SHALL be loadable from a user-recorded baseline file
The detector SHALL accept a calibration file mapping BSSID → known
empty-room σ baseline. `load_calibration` SHALL load it; the
`diting calibrate` subcommand SHALL produce one. Calibrated
baselines SHALL take precedence over the adaptive baseline for the
first `DEFAULT_BASELINE_WINDOW_S` after launch — until the rolling
window has enough samples to be statistically meaningful.

#### Scenario: Fresh launch with prior calibration
- **WHEN** the user has recorded `~/.diting/calibration.json` and starts diting
- **THEN** the detector uses the calibrated baseline immediately, can fire stir events in the first 30 s of the session

#### Scenario: First-ever launch, no calibration
- **WHEN** the user has never run `diting calibrate`
- **THEN** the detector silently falls back to adaptive-baseline-only and the first 5 minutes of the session are "warming up" — events can fire but baselines are still settling
