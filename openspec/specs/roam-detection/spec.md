# roam-detection Specification

## Purpose

Defines diting's "should the user re-roam?" scoring — the Roam
score row of the Diagnostics panel and the same-SSID better-candidate
hint that surfaces when a clearly stronger BSSID for the user's
current network is in scan range. macOS does not aggressively roam
off a "good enough" AP, so diting nudges the user when staying
sticky costs them performance.

## Requirements

### Requirement: The current link SHALL get a 0–100 simple score
`_link_score(link, results, baseline)` SHALL produce a `(score,
reasons)` pair where score is an int in 0..100 and reasons is a
short ordered tuple of human-readable strings explaining the
adjustments. The score is a simple guide, not a standard.

The default starts at 50, then:
- RSSI ≥ -55 → +30 (`strong signal`)
- -67 ≤ RSSI < -55 → +20 (`good signal`)
- -75 ≤ RSSI < -67 → +8 (`usable signal`)
- RSSI < -75 → -15 (`weak signal`)
- SNR ≥ 35 dB → +10
- 25 ≤ SNR < 35 → +5
- SNR < 25 → -8 (`low SNR`)
- Plus per-band / per-channel-load adjustments

#### Scenario: Excellent link
- **WHEN** RSSI = -45 dBm, SNR = 50 dB on 5 GHz, channel near-empty
- **THEN** score reaches 90+/100 and reasons read `(strong signal, 5 GHz)`

#### Scenario: Edge of range
- **WHEN** RSSI = -78 dBm
- **THEN** score drops below 50 and reasons start with `weak signal`

### Requirement: Same-SSID better-candidate detection SHALL surface only when ≥ +10 dB stronger
`_best_same_ssid_candidate(results, current)` SHALL return None
unless a non-current BSSID with the same SSID is at least 10 dB
stronger than the current link. Below that threshold the user
should NOT be nudged to switch — the cost of cycling Wi-Fi off/on
exceeds the benefit.

#### Scenario: Slightly stronger same-SSID AP nearby
- **WHEN** current is -65 dBm and another BSSID for the same SSID is -60 dBm (+5 dB)
- **THEN** no candidate is surfaced; the diagnostics row reads "no clearly better same-SSID BSSID"

#### Scenario: Substantially stronger same-SSID AP nearby
- **WHEN** current is -78 dBm and another BSSID for the same SSID is -56 dBm (+22 dB)
- **THEN** the candidate is surfaced; the diagnostics row reads `· better candidate <score>/100 (+22) ch<n> <bssid> (strong signal, 5 GHz)  press c to re-roam`

### Requirement: A surfaced candidate SHALL include its own score and a press-`c` hint
When a candidate IS surfaced, its label SHALL include: the candidate's
own 0–100 score (using the same `_link_score` against the candidate's
RSSI), the dB delta versus current, the candidate's channel and BSSID,
the same reasons phrasing the current link uses, and a "press c to
re-roam" instruction pointing at the global `c` binding.

#### Scenario: Candidate exists, user reads diagnostics
- **WHEN** a candidate is +18 dB at -47 dBm on ch48
- **THEN** the diagnostics row carries `+18` delta, the candidate's score (~ 90+/100), `ch48` and the BSSID, plus the press-c hint

### Requirement: The press-`c` action SHALL force a Wi-Fi off/on cycle
The `c` keybinding SHALL invoke `force_reroam()` on the backend,
which cycles the macOS Wi-Fi radio off then on. This is the same
path as click-Wi-Fi-off / click-Wi-Fi-on in the menu bar — it
re-runs auto-join with Keychain credentials and works for both WPA
personal and 802.1X Enterprise networks. SHALL NOT silently fail; the
user gets a notification confirming the cycle started.

#### Scenario: User accepts the nudge
- **WHEN** the user presses `c` after seeing the candidate
- **THEN** Wi-Fi cycles off → on, the OS auto-joins (typically picking the stronger AP), and the Connection panel updates to the new BSSID within ~5 s

### Requirement: Wording SHALL match the `_health_line` and `_link_score` vocab
The Current link health string and the Roam score reasons SHALL
use a single shared RSSI bucket vocabulary — strong / good / fair /
weak (or strong / good / usable / weak — pick ONE set), used
identically by both surfaces. Mismatched vocab between adjacent
panel rows is a documented historical bug.

#### Scenario: -68 dBm reading
- **WHEN** the user is at -68 dBm
- **THEN** Current link and Roam score reasons describe the same RSSI with the same word — never "fair" on one row and "usable" on the other
