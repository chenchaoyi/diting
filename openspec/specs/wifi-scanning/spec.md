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
A scan result row SHALL include: `rssi_dbm` (int, negative), `channel` (int), `band` (one of `2.4G`, `5G`, `6G`), `security` (one of `OPEN`, `WPA2`, `WPA3`, `ENT`, `WPA2/WPA3`), `bssid` (lowercase colon-separated MAC), and `ssid` (string, possibly empty for hidden APs). Optional fields: `channel_width_mhz`, `noise_dbm`, `country_code`, `phy_modes`, `tx_rate_mbps`. The associated-interface `Connection` snapshot (separate from scan rows) additionally carries `tx_rate_idle: bool` indicating whether the surfaced `tx_rate_mbps` is a cached value substituted in for an idle-radio poll (see the new `tx_rate` idle-cache requirement below).

Every BSSID the backend emits — scan rows AND the `Connection`
snapshot, regardless of which source produced it (CoreWLAN scan,
helper scan, CoreWLAN interface, or the SCDynamicStore
`CachedScanRecord` fallback) — SHALL be normalized to the canonical
form: lowercase, colon-separated, each octet zero-padded to two hex
digits. macOS formats some surfaces without octet padding (the
SCDynamicStore cached record renders `0b` as `b`); un-normalized
spellings make the same radio two identities downstream (duplicate
Nearby rows, phantom roams, split familiarity history). Normalization
SHALL be fail-soft: a string that does not parse as six hex octets is
passed through lowercased, never raised on.

#### Scenario: A standard 5 GHz BSSID
- **WHEN** the scan returns a row for "Meituan" on channel 36
- **THEN** the row has `rssi_dbm=<int>`, `channel=36`, `band="5G"`, `security="ENT"`, `bssid="aa:bb:cc:dd:ee:ff"`, `ssid="Meituan"`

#### Scenario: A hidden AP
- **WHEN** the scan returns a row with empty SSID
- **THEN** the row's `ssid` is `""` (empty string), `bssid` is still populated, and the row participates in dedup like any other

#### Scenario: Un-padded fallback BSSID is one identity with its scan row
- **WHEN** the SCDynamicStore fallback reports the current BSSID as `40:fe:95:8a:3c:b` and the scan list contains `40:fe:95:8a:3c:0b`
- **THEN** both normalize to `40:fe:95:8a:3c:0b` and the Nearby list shows one row for that radio, not two

### Requirement: When the helper is unavailable, scan results SHALL be REDACTED rather than missing
diting SHALL surface the redacted-scan state explicitly with the
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

### Requirement: The `MacOSWiFiBackend` SHALL cache the last non-zero `tx_rate_mbps` per association and surface it as an "(idle)" value when the radio reports 0
On every poll where the associated `(ssid, bssid)` is unchanged, the backend SHALL remember the most recent non-zero `tx_rate_mbps`. If a subsequent poll on the same association reports `0` (or `None`) for `transmitRate()`, the backend SHALL surface the cached value AND set `Connection.tx_rate_idle = True`. On a non-zero poll the backend SHALL clear the flag and surface the current rate verbatim. The cache SHALL be invalidated whenever the associated `(ssid, bssid)` changes (a roam to a different BSSID, association loss, reassociation to a new SSID).

#### Scenario: Idle frame after a 144 Mbps frame on the same AP
- **WHEN** poll N returns `transmitRate()=144_000_000` and poll N+1 returns `transmitRate()=0` for the same `(ssid, bssid)`
- **THEN** poll N's `Connection` has `tx_rate_mbps=144.0`, `tx_rate_idle=False`; poll N+1's `Connection` has `tx_rate_mbps=144.0`, `tx_rate_idle=True`

#### Scenario: Roam to a new BSSID drops the cache
- **WHEN** poll N is on `bssid_a` with `tx_rate=144`, poll N+1 is on `bssid_b` with `transmitRate()=0`
- **THEN** poll N+1's `Connection` has `tx_rate_mbps=None` and `tx_rate_idle=False` (no cached value to substitute in — the cache was scoped to `bssid_a`)

#### Scenario: First poll on a fresh association with rate=0
- **WHEN** the first poll after associate / launch reports `transmitRate()=0` and there is no prior non-zero observation
- **THEN** `Connection.tx_rate_mbps=None`, `tx_rate_idle=False` (the flag is only set when a real cached value is being substituted in; surfacing `n/a` is still the right answer when nothing has ever been observed)

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

