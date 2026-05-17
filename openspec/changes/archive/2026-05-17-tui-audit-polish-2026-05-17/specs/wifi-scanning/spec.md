## ADDED Requirements

### Requirement: Scan results SHALL be deduplicated by BSSID before reaching consumers
The Python-side scan path (`_helper.scan` for the helper-attributed code path AND `MacOSWiFiBackend.scan`'s direct-CoreWLAN fallback) SHALL collapse multiple rows that share the same lowercase BSSID into one row. On collision the row with the highest `rssi_dbm` wins, treating `None` as `-200`. First-seen order across distinct BSSIDs is preserved. Rows with `bssid=None` (the redacted path) are kept verbatim and do not participate in dedup.

#### Scenario: Helper returns two rows for one BSSID
- **WHEN** `diting-tianer scan` emits two entries with `bssid=40:fe:95:89:c7:e5`, one at `rssi_dbm=-72` and one at `rssi_dbm=-75`
- **THEN** `_helper.scan` returns one `ScanResult` with `bssid="40:fe:95:89:c7:e5"` and `rssi_dbm=-72`

#### Scenario: Two distinct BSSIDs preserved in order
- **WHEN** the helper emits BSSIDs `aa:…:01` then `bb:…:02` then `aa:…:01` again
- **THEN** `_helper.scan` returns two rows in order `[aa:…:01, bb:…:02]`

#### Scenario: Redacted rows are not folded together
- **WHEN** the direct-CoreWLAN fallback produces two rows both with `bssid=None` (TCC redacted, distinct CWNetwork instances)
- **THEN** both rows are preserved in the output list (the dedup keys on the BSSID string; `None` keys are exempt)

## MODIFIED Requirements

### Requirement: Each scanned BSSID SHALL carry RSSI, channel, band, security mode, and BSSID itself
A scan result row SHALL include: `rssi_dbm` (int, negative), `channel` (int), `band` (one of `2.4G`, `5G`, `6G`), `security` (one of `OPEN`, `WPA2`, `WPA3`, `ENT`, `WPA2/WPA3`), `bssid` (lowercase colon-separated MAC), and `ssid` (string, possibly empty for hidden APs). Optional fields: `channel_width_mhz`, `noise_dbm`, `country_code`, `phy_modes`, `tx_rate_mbps`. The associated-interface `Connection` snapshot (separate from scan rows) additionally carries `tx_rate_idle: bool` indicating whether the surfaced `tx_rate_mbps` is a cached value substituted in for an idle-radio poll (see the new `tx_rate` idle-cache requirement below).

#### Scenario: A standard 5 GHz BSSID
- **WHEN** the scan returns a row for "Meituan" on channel 36
- **THEN** the row has `rssi_dbm=<int>`, `channel=36`, `band="5G"`, `security="ENT"`, `bssid="aa:bb:cc:dd:ee:ff"`, `ssid="Meituan"`

#### Scenario: A hidden AP
- **WHEN** the scan returns a row with empty SSID
- **THEN** the row's `ssid` is `""` (empty string), `bssid` is still populated, and the row participates in dedup like any other

## ADDED Requirements

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
