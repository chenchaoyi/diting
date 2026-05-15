## MODIFIED Requirements

### Requirement: The modal SHALL render every `ScanResult` field, grouped into sections, plus context drawn from session state
The modal layout SHALL be a vertical sequence of sections, in this order, with sections omitted when their data is absent:

1. **Identity** — SSID (or `(hidden)` for empty broadcast), BSSID (or `(redacted by TCC)`), AP name from `aps.yaml` when present, OUI-derived vendor when BSSID is available
2. **Radio** — channel + band label (2.4 / 5 / 6 GHz), channel width MHz, PHY mode, security, MCS index, NSS
3. **Signal** — RSSI dBm, noise dBm, SNR (computed when both present)
4. **Signal history** — sparkline of the last ~hour of RSSI samples for this BSSID drawn from `EnvironmentMonitor`'s per-BSSID ring, plus a one-line stability label (`σ X dB · stable / active / noisy`) using the same σ-band classification the diagnostics panel renders. Section SHALL be omitted when `EnvironmentMonitor` has fewer than 2 samples for this BSSID or when no monitor reference was supplied to the modal.
5. **Beacon IE** — BSS load %, BSS station count, 802.11r/k/v support flags. Section omitted entirely when none of these fields is present (older helper schema, CoreWLAN-only path).
6. **Same physical AP** — when `NetworkInventory`'s grouping clusters this BSSID with sibling BSSIDs under one physical AP, list those siblings with their channel / band / latest RSSI from the current scan. Section SHALL be omitted when the cluster is singleton.
7. **Roam history** — filter the App's event ring for roam events whose `from_bssid` or `to_bssid` matches this BSSID; render the most recent 10 entries newest-first as `<HH:MM:SS> · [same-AP | cross-AP] · <from> → <to>`. Section SHALL be omitted when no matching events exist in the ring.
8. **Recommendation** — when the `clearly-better same-SSID candidate` rule (the same rule the diagnostics panel's "Roam score" line uses) identifies a stronger alternative, render `consider switching to <BSSID> on <band> · +N dB`. Section SHALL be omitted when no clearly-better candidate exists or when this row is itself the clearly-better one.
9. **Activity** — country code (when present), first seen / last seen as "Xs ago"

Connection-state context (whether this row is currently associated, when applicable) SHALL appear as an inline annotation on the Identity section, not a separate section.

#### Scenario: Open modal on the currently-associated AP
- **WHEN** the user inspects the row that matches the active `Connection.bssid`
- **THEN** the Identity section shows the SSID + BSSID + AP-name + vendor + an `(associated)` annotation; all other sections render with the latest scan values

#### Scenario: Open modal on a row with BSSID redacted
- **WHEN** the user inspects a row whose BSSID is `None`
- **THEN** the Identity section shows BSSID as `(redacted by TCC — grant Location Services for full data)`; the vendor row is absent; Signal history / Same physical AP / Roam history / Recommendation sections are all omitted (no BSSID = no keys to filter on)

#### Scenario: Open modal on an old-schema scan row
- **WHEN** the user inspects a row whose helper response predates schema 3 (no beacon-IE diagnostics)
- **THEN** the Beacon IE section is absent entirely; other sections render normally

#### Scenario: Open modal on a freshly-discovered BSSID
- **WHEN** the user inspects a row that has been visible for less than ~5 seconds (so EnvironmentMonitor has 0 or 1 samples)
- **THEN** the Signal history section is omitted; the Signal section still renders the single available RSSI sample

#### Scenario: Open modal on the 5 GHz radio of an `aps.yaml`-named AP
- **WHEN** the user inspects the 5 GHz BSSID of `2F-客厅` and the same AP's 2.4 GHz radio is also in the latest scan
- **THEN** the Same physical AP section lists the 2.4 GHz sibling with its channel / band / RSSI

#### Scenario: Open modal on a BSSID with this-session roam events
- **WHEN** the user has roamed to this BSSID three times in the current session
- **THEN** the Roam history section renders 3 rows in newest-first order with `[same-AP]` or `[cross-AP]` markers

#### Scenario: Open modal when a clearly-better alternative is visible
- **WHEN** the user is associated to a -75 dBm BSSID and the scan list also contains a same-SSID BSSID at -52 dBm
- **THEN** the Recommendation section renders `consider switching to <BSSID> on <band> · +23 dB` against the stronger row
