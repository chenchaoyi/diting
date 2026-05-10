# Tasks — document roam-detection

## 1. Spec backfill — no implementation
- [x] 1.1 Spec extracted from `src/wifiscope/tui.py` (`_link_score`, `_best_same_ssid_candidate`, `_health_line`, `action_reroam`, `_score_line`).
- [x] 1.2 Cross-checked vocab consistency against the recent ZH-audit fix (the "fair / usable" alignment work).

## 2. Optional polish (not blocking archive)
- [x] 2.1 The `_link_score` and `_health_line` RSSI bucket tables get a comment cross-linking to the spec's vocab-consistency requirement.
- [x] 2.2 README "Roaming" section explains why the +10 dB threshold is the surface-or-not cut.
