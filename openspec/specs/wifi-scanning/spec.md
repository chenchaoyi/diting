# wifi-scanning Specification

## Purpose

Defines the contract for unredacted Wi-Fi scanning on macOS — what the
TUI knows about each visible BSSID, where the data comes from, and how
the system degrades when permissions / IE data are missing. The
scanner sits at the bottom of the diagnostic stack; the Diagnostics
panel, the events log, and the analyzer all assume the scan output
matches this contract.
## Requirements
### Requirement: Each scanned BSSID SHALL carry RSSI, channel, band, security mode, and BSSID itself
A scan result row SHALL include: `rssi_dbm` (int, negative), `channel`
(int), `band` (one of `2.4G`, `5G`, `6G`), `security` (one of `OPEN`,
`WPA2`, `WPA3`, `ENT`, `WPA2/WPA3`), `bssid` (lowercase
colon-separated MAC), and `ssid` (string, possibly empty for hidden
APs). Optional fields: `channel_width_mhz`, `noise_dbm`,
`country_code`, `phy_modes`, `tx_rate_mbps`.

#### Scenario: A standard 5 GHz BSSID
- **WHEN** the scan returns a row for "Meituan" on channel 36
- **THEN** the row has `rssi_dbm=<int>`, `channel=36`, `band="5G"`, `security="ENT"`, `bssid="aa:bb:cc:dd:ee:ff"`, `ssid="Meituan"`

#### Scenario: A hidden AP
- **WHEN** the scan returns a row with empty SSID
- **THEN** `ssid` is `""` and the panel renders `(hidden)`

### Requirement: When the helper is unavailable, scan results SHALL be REDACTED rather than missing
Diting SHALL surface the redacted-scan state explicitly with the
placeholder `(redacted)` and a one-liner pointing the user at
`helper/diting-tianer.app`, and SHALL NOT pretend the scan
returned nothing or fail silently. On macOS 14.4+, a Terminal-launched
Python process cannot earn Location Services TCC and CoreWLAN scans
return rows with `ssid=None` and `bssid=None`.

#### Scenario: First-run user without granted helper
- **WHEN** diting launches and the helper is uninstalled or
  ungranted
- **THEN** the scan panel renders rows with `(redacted)` SSID/BSSID and the diagnostics row points the user at the helper bundle

### Requirement: Beacon IE keys (`bss_load_pct`, supports_802_11r/k/v) SHALL be optional and additive
Beacon IE fields SHALL be absent from rows produced by older helpers,
and the TUI SHALL render their absence as a dim `—` (not as 0). Newer
helper bundles emit on each scan row: `bss_load_pct` (channel
utilisation 0–100), `bss_station_count` (int), `supports_802_11r`
(bool, fast roaming), `supports_802_11k` (bool, neighbour reports),
`supports_802_11v` (bool, BSS transition management).

#### Scenario: Older helper without IE fields
- **WHEN** the helper produced an output without the `bss_load_pct` field
- **THEN** the Nearby BSSIDs row renders the IE column as `—` rather than `0%`

#### Scenario: Modern helper with IE fields
- **WHEN** `bss_load_pct=42` is reported
- **THEN** the row's IE column shows `42%` and the diagnostics panel may flag busy channels accordingly

### Requirement: Scan refresh SHALL respect CoreWLAN's documented throttle
The poller SHALL run scans on a ≥ 7 s cadence by default and SHALL
NOT issue back-to-back scans within the CoreWLAN throttle window
(~5 s) even on user-pressed `r` rescan — the second press is a no-op
with a status hint. CoreWLAN throttles aggressively-spammed scans by
returning stale or empty results.

#### Scenario: User rapid-presses rescan
- **WHEN** the user presses `r` twice within 2 s
- **THEN** only the first press triggers a fresh scan; the second is suppressed with a status notice, no flickering empty list

#### Scenario: Throttled empty result
- **WHEN** CoreWLAN returns 0 BSSIDs because the previous scan completed within the throttle window
- **THEN** the panel keeps the previous (non-empty) cached results visible, NOT replaces them with an empty list

### Requirement: BSSIDs without any scan data SHALL never appear in the Nearby list
A BSSID with `rssi_dbm = None` or implausible values SHALL be filtered
from the Nearby BSSIDs list. RSSI sentinels (≥ 0 dBm or < -200 dBm)
indicate a CoreWLAN bug or driver glitch and the row would otherwise
sort to the top of the list as a "very strong" ghost.

#### Scenario: Sentinel RSSI from CoreWLAN
- **WHEN** CoreWLAN reports a row with `rssi=127` (the documented "no reading" sentinel)
- **THEN** the row is dropped before it reaches the panel

### Requirement: The `current` BSSID SHALL be merged into the scan results even if scan omits it
The poller SHALL inject a synthetic row matching the connected
`Connection.bssid` into the scan list whenever CoreWLAN's scan
omits it, marked `current`, so the panel's "current" highlight
always has a row to point at. CoreWLAN scan results occasionally
omit the user's own associated BSSID because the radio is busy
with the active link.

#### Scenario: Scan misses the associated AP
- **WHEN** the scan returns 8 BSSIDs but none match the current `Connection.bssid`
- **THEN** the Nearby list shows 9 rows — the 8 scanned plus a synthetic "current" row populated from the Connection panel's data

