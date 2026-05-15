# wifi-detail-modal Specification

## Purpose
TBD - created by archiving change wifi-bonjour-detail-modals. Update Purpose after archive.
## Requirements
### Requirement: Wi-Fi list rows SHALL be selectable by BSSID, stable across snapshots
The App SHALL track a single `_wifi_selected_key: str | None` keyed by
a stable identifier derived from the scan row: lowercase BSSID with
all separators stripped when CoreWLAN exposes the BSSID; the synthetic
fallback `f"{ssid}#{channel}"` (or `f"#{channel}"` for hidden SSIDs)
when BSSID is `None`. Each snapshot's render SHALL highlight the row
whose key matches the selection. If the selected AP drops out of the
snapshot, the selection SHALL clear to `None` — the cursor MUST NOT
silently jump to a different row.

#### Scenario: Cursor stable through re-sort
- **WHEN** the user selects an AP `Plaza-Wi-Fi (-58 dBm)` and another AP's RSSI improves enough to bump it above
- **THEN** the highlight stays on `Plaza-Wi-Fi`, even though its row index changed

#### Scenario: Selected AP leaves the scan
- **WHEN** the user selects a BSSID that disappears from the next scan
- **THEN** the next render clears the selection (no ghost cursor on a row that doesn't exist)

#### Scenario: BSSID redacted by TCC, two rows share same SSID + channel
- **WHEN** Location Services is denied so every row's BSSID is `None`, and two physical APs broadcast `eduroam` on channel 36
- **THEN** the synthetic key `eduroam#36` collides, and the highlight stays on whichever row sorts first; modal-open re-resolves the key against the current snapshot

### Requirement: Keyboard navigation SHALL bind `up` / `down` / `enter` / `i` in the Wi-Fi view
The App SHALL bind `up`/`down` to move selection (priority=True so
they fire before `VerticalScroll`'s built-in scroll handler) and
`enter`/`i` to open the Wi-Fi detail modal for the current selection.
All bindings SHALL be no-ops outside the Wi-Fi view.

#### Scenario: Wi-Fi view, user presses down
- **WHEN** the user is in Wi-Fi view and presses ↓
- **THEN** selection moves to the next scan row, highlight follows

#### Scenario: BLE view, user presses down
- **WHEN** the user is in BLE view
- **THEN** `action_wifi_select_next` is a no-op (BLE's binding handles selection instead)

#### Scenario: First press with no prior selection
- **WHEN** the user has not yet moved the cursor in Wi-Fi view and presses `i`
- **THEN** the modal opens for the first scan row in panel order (currently-associated AP if present, otherwise the strongest-RSSI row)

### Requirement: Mouse click on a Wi-Fi scan row SHALL select-and-inspect in one gesture
A click on any data row in the Wi-Fi scan list SHALL set selection to
that row and open the detail modal in the same gesture. Clicks on
header / connection / environment / spacer rows SHALL be no-ops.
Coordinates SHALL be translated via Textual's
`event.get_content_offset(body)` so border / padding / scroll are
handled correctly.

#### Scenario: Click on a scan row
- **WHEN** the user clicks on the third scan row
- **THEN** the row highlight moves there and the detail modal opens for that AP

#### Scenario: Click on the scan-panel header "Nearby BSSIDs (12) · Sort: AP"
- **WHEN** the user clicks on the header line
- **THEN** nothing happens (no modal opens, selection unchanged)

### Requirement: The modal SHALL render every `ScanResult` field, grouped into sections, plus context drawn from session state
The modal layout SHALL be a vertical sequence of sections, in this order, with sections omitted when their data is absent:

1. **Identity** — SSID (or `(hidden)` for empty broadcast), BSSID (or `(redacted by TCC)`), AP name from `aps.yaml` when present, OUI-derived vendor when BSSID is available
2. **Radio** — channel + band label (2.4 / 5 / 6 GHz), channel width MHz, PHY mode, security, MCS index, NSS
3. **Signal** — RSSI dBm, noise dBm, SNR (computed when both present)
4. **Signal history** — sparkline of the last ~hour of RSSI samples for this BSSID drawn from `EnvironmentMonitor`'s per-BSSID ring, plus a one-line stability label (`σ X dB · stable / active`) using the same σ-band classification the diagnostics panel renders. Section SHALL be omitted when `EnvironmentMonitor` has fewer than 2 samples for this BSSID or when no monitor reference was supplied to the modal.
5. **Beacon IE** — BSS load %, BSS station count, 802.11r/k/v support flags. Section omitted entirely when none of these fields is present (older helper schema, CoreWLAN-only path).
6. **Same physical AP** — when `NetworkInventory`'s grouping clusters this BSSID with sibling BSSIDs under one physical AP, list those siblings with their channel / band / latest RSSI from the current scan. Section SHALL be omitted when the cluster is singleton.
7. **Roam history** — filter the App's event ring for roam events whose `previous_bssid` or `new_bssid` matches this BSSID; render the most recent 10 entries newest-first as `<HH:MM:SS> · [same-AP | cross-AP] · <from> → <to>`. Section SHALL be omitted when no matching events exist in the ring.
8. **Recommendation** — when the `clearly-better same-SSID candidate` rule (the same rule the diagnostics panel's "Roam score" line uses) identifies a stronger alternative AND the inspected row is the currently-associated BSSID, render `consider switching to <BSSID> on <band> · +N dB`. Section SHALL be omitted otherwise.
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

### Requirement: Modal close SHALL be Esc / `i` / `q`, and SHALL NOT mutate selection
The modal SHALL bind `escape`, `i`, and `q` to close. Closing SHALL
NOT clear `_wifi_selected_key` — the user expects the highlighted row
to remain highlighted. Reopening with `i` without other key presses
SHALL show the same row.

#### Scenario: User opens modal, reads, closes, reopens
- **WHEN** the user presses `i` → reads → Esc → `i`
- **THEN** the second `i` opens the modal for the same AP

### Requirement: AP-name lookup SHALL come from the user's `aps.yaml` only
The Identity section's AP-name row SHALL be derived from the
`aps.yaml` inventory the user maintains locally, NOT from any
external lookup. SHALL be absent when no entry matches the BSSID.

#### Scenario: BSSID matches an aps.yaml entry
- **WHEN** the user inspects an AP whose BSSID is mapped in `aps.yaml` to "kitchen ceiling"
- **THEN** the Identity section shows `AP name: kitchen ceiling`

#### Scenario: No aps.yaml match
- **WHEN** the user inspects an AP not listed in `aps.yaml`
- **THEN** the Identity section omits the AP-name row entirely

### Requirement: While the modal is open, `up` / `down` SHALL track selection live
The TUI SHALL advance the underlying Wi-Fi selection when the user
presses `up` / `down` while `WifiDetailScreen` is on the screen
stack, AND the modal body MUST re-render to track the new row's
`ScanResult` data. The user SHALL be able to walk the scan list
without closing and reopening the modal each time.

#### Scenario: User opens modal, presses ↓
- **WHEN** the modal is open on the associated AP and the user presses ↓
- **THEN** the underlying selection advances to the next scan row AND the modal body shows that row's SSID / BSSID / channel / RSSI

#### Scenario: User walks the list, then closes
- **WHEN** the user presses ↓ × 3 inside the modal then `Esc`
- **THEN** the modal closes, the panel highlight is on the row the modal was last showing, and the next `i` reopens the modal on that same row

### Requirement: The footer SHALL document the close keys in the active locale
The modal SHALL render a footer `Esc / i to close` (English) or its
ZH translation, using the same `t()` lookup as the rest of the TUI.

#### Scenario: ZH locale
- **WHEN** `DITING_LANG=zh` and the user opens the Wi-Fi detail modal
- **THEN** the footer reads `Esc / i 关闭`

