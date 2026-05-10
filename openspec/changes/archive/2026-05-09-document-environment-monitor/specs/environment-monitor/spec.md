# environment-monitor Specification

## Purpose

Defines the RF-stir detector — wifiscope's "something changed in the
RF environment around me" signal. Computes per-BSSID rolling RSSI
standard deviation, compares short window vs long-window adaptive
baseline, fires `RFStirEvent` on threshold crossing. The Diagnostics
panel's Environment line, the events ring, and the σ baseline modal
all read from this module.

## Requirements

### ADDED Requirement: σ thresholds SHALL be defined as named constants, not magic numbers
The detector SHALL expose its trigger constants as module-level
names: `DEFAULT_BASELINE_WINDOW_S` (300 s), `DEFAULT_SPIKE_WINDOW_S`
(5 s), `DEFAULT_SPIKE_RATIO` (2.5), `DEFAULT_SPIKE_MIN_DB` (3.0),
`DEFAULT_COOLDOWN_S` (8.0), `DEFAULT_REARM_DB` (1.5). The TUI's STIR
legend SHALL read the ratio + min-dB from these constants at render
time so the displayed values cannot drift from the firing logic.

#### Scenario: Lowering the spike ratio
- **WHEN** a contributor changes `DEFAULT_SPIKE_RATIO` from 2.5 to 2.0
- **THEN** the events modal's STIR legend automatically renders `... > baseline ×2.0 ...`, no separate copy edit needed

### ADDED Requirement: A spike fires only when current σ exceeds BOTH the ratio AND the absolute floor
A `RFStirEvent` SHALL fire iff `current_sigma > baseline_sigma × DEFAULT_SPIKE_RATIO` AND `current_sigma > DEFAULT_SPIKE_MIN_DB`.
Either condition alone SHALL NOT fire. This pairs together because
the ratio test alone produces false positives at low absolute σ
(e.g. σ=0.4 dB tripled is still in noise floor), and the absolute
floor alone produces false positives in noisy stable environments
(e.g. an AP that always sits at σ=3.5 dB).

#### Scenario: Quiet hallway, σ jumps from 0.4 to 1.5 dB
- **WHEN** σ is 1.5 (above 0.4 × 2.5 = 1.0) but below the 3.0 absolute floor
- **THEN** no event fires (absolute floor not met)

#### Scenario: Always-noisy AP at σ = 3.5 dB
- **WHEN** σ stays at 3.5 (above the floor) but baseline is also ~3.5 (ratio not met)
- **THEN** no event fires

### ADDED Requirement: Each AP SHALL be classified into one of three fusion modes
At each tick the detector SHALL classify each visible BSSID into a
fusion mode based on its RSSI:

- `co_located` — RSSI ≥ -65 dBm. The user is physically near this
  AP; high-information stir signal.
- `spatial_channel` — -85 dBm ≤ RSSI < -65 dBm. Distant AP whose
  air-time still contributes to local channel utilisation.
- `ignored` — RSSI < -85 dBm. Too weak to draw conclusions from;
  σ is dominated by floor noise.

The mode label SHALL appear in the per-AP σ baseline table and in
each emitted `RFStirEvent.mode` field.

#### Scenario: Walking from desk to kitchen
- **WHEN** an AP's RSSI drops from -55 to -90 over 30 s
- **THEN** the AP transitions from `co_located` → `spatial_channel` → `ignored`, the baseline table updates the mode column, and stir-event firing follows the per-mode threshold

### ADDED Requirement: A cooldown SHALL prevent the same AP from spamming events
After a stir event fires for a given AP, the detector SHALL suppress
further events from that AP for `DEFAULT_COOLDOWN_S` (8 s) AND
SHALL require σ to drop below `DEFAULT_REARM_DB` (1.5 dB) before
re-arming. This combination prevents one large stir from re-firing
on each subsequent tick while the spike is still elevated.

#### Scenario: Sustained 30-second stir
- **WHEN** σ jumps to 12 dB and stays there for 30 s
- **THEN** exactly ONE `RFStirEvent` fires; the cooldown + rearm guards prevent duplicates

#### Scenario: Two separate disturbances 20 s apart
- **WHEN** a stir at t=0 returns to σ < 1.5 by t=10, then a fresh stir at t=20
- **THEN** two separate events fire (rearm satisfied between them)

### ADDED Requirement: Calibration SHALL be loadable from a user-recorded baseline file
The detector SHALL accept a calibration file mapping BSSID → known
empty-room σ baseline. `load_calibration` SHALL load it; the
`wifiscope calibrate` subcommand SHALL produce one. Calibrated
baselines SHALL take precedence over the adaptive baseline for the
first `DEFAULT_BASELINE_WINDOW_S` after launch — until the rolling
window has enough samples to be statistically meaningful.

#### Scenario: Fresh launch with prior calibration
- **WHEN** the user has recorded `~/.wifiscope/calibration.json` and starts wifiscope
- **THEN** the detector uses the calibrated baseline immediately, can fire stir events in the first 30 s of the session

#### Scenario: First-ever launch, no calibration
- **WHEN** the user has never run `wifiscope calibrate`
- **THEN** the detector silently falls back to adaptive-baseline-only and the first 5 minutes of the session are "warming up" — events can fire but baselines are still settling

### ADDED Requirement: Wording SHALL frame stir as "something changed", never as a presence claim
Every user-visible string emitted by this module SHALL describe
correlation, never causation. The Environment line uses "stable" /
"active" / "very active" tiers; events use "RF stir at <location>"
with confidence labels. SHALL NOT use words like "person detected",
"motion", "occupancy", "intruder". A passing person, a rebooting
neighbour AP, and a OS-driven background scan all produce identical
σ spikes.

#### Scenario: User asks "is this presence detection?"
- **WHEN** they read the Environment line and the events strip
- **THEN** every label says "stir" / "active" / "RF disturbance" — neutral correlation language, no presence claim
