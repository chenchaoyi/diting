# Tasks — document environment-monitor

## 1. Spec backfill — no implementation
- [x] 1.1 Spec extracted from `src/wifiscope/environment.py` (the constants block, `EnvironmentMonitor`, `_APState`, `RFStirEvent`, `load_calibration`, `write_calibration`).
- [x] 1.2 Cross-checked thresholds against the events-modal STIR legend (now constant-driven, see `ble-decoders` archive's predecessor work).

## 2. Optional polish (not blocking archive)
- [x] 2.1 Help / Basics modals reference the "correlation, never causation" wording principle so users understand why the labels stay neutral.
- [x] 2.2 README "Environment monitor" section gains a one-liner pointing to `openspec/specs/environment-monitor/spec.md`.
