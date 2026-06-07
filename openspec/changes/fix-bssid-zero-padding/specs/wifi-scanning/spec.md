# wifi-scanning delta — fix-bssid-zero-padding

## MODIFIED Requirements

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
