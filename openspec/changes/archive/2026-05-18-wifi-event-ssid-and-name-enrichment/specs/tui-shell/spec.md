## ADDED Requirements

### Requirement: Wi-Fi-anchored event lines SHALL surface the affected SSID alongside the BSSID / AP-name
The Events panel's renderer for `RoamEvent` and `RFStirEvent` SHALL include the associated SSID (carried by the event itself) as part of the event line:

- `RoamEvent`: when `previous_ssid == new_ssid` (the common case — band switch within an ESS, or inter-AP roam keeping the same network) the line SHALL render a single `SSID: <name>` segment after the BSSID arrow. When the SSIDs differ the line SHALL render `SSID: <prev> → <new>` using the same arrow glyph as the BSSID pair. When both SSIDs are `None` OR both are `""` (hidden) the SSID segment SHALL be omitted entirely; `SSID: n/a` SHALL NOT appear.
- `RFStirEvent`: when `ssid` is a non-empty string the line SHALL append `· SSID <name>` after the location body. When `ssid` is `None` or `""` the segment SHALL be omitted.

AP-name rendering is unchanged: it continues to come from `format_bssid` (roam line) and `event.location` (rf_stir line), both of which read `aps.yaml` via `NetworkInventory`. SSID context is additive — a fully-populated `aps.yaml` keeps showing the friendly AP name, and an empty inventory keeps showing the cluster label / raw BSSID; both cases gain the SSID segment for free.

i18n: the new wrapper strings (`SSID: {ssid}`, `SSID: {prev} → {new}`, `SSID {ssid}`) SHALL be added to the EN + ZH catalogs.

#### Scenario: Roam between band siblings on the same SSID
- **WHEN** the event ring contains a `RoamEvent` with `previous_ssid="tedo"` and `new_ssid="tedo"`
- **THEN** the rendered line carries `SSID: tedo` exactly once, after the BSSID arrow segment

#### Scenario: Roam across two distinct SSIDs
- **WHEN** the event has `previous_ssid="home"` and `new_ssid="office"`
- **THEN** the rendered line carries `SSID: home → office`

#### Scenario: Roam with both SSIDs unknown (TCC redacted)
- **WHEN** the event has `previous_ssid=None` and `new_ssid=None`
- **THEN** the rendered line OMITS the SSID segment; the BSSID arrow segment renders unchanged

#### Scenario: Hidden SSID on both sides
- **WHEN** the event has `previous_ssid=""` and `new_ssid=""` (CoreWLAN returns empty string for hidden SSIDs)
- **THEN** the rendered line OMITS the SSID segment; empty strings are not surfaced as `SSID: `

#### Scenario: RF stir with a known SSID
- **WHEN** the event has `ssid="tedo_5G"` and `location="?af:5e:9d"`
- **THEN** the rendered line reads `?af:5e:9d 处 RF 扰动 σ 4.8 dB · 中 · SSID tedo_5G` (positions of i18n decorations may vary; the `SSID tedo_5G` segment is present)

#### Scenario: RF stir without an SSID
- **WHEN** the event has `ssid=None`
- **THEN** the rendered line is unchanged from the legacy (pre-enrichment) shape — the trailing `· SSID …` segment is absent
