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

### Requirement: The Wi-Fi detail modal SHALL bind `j` to initiate a join of the inspected SSID
The `j` key SHALL invoke a join of the AP currently rendered in `WifiDetailScreen` while the modal is on the screen stack.
The binding SHALL appear in the modal's footer / help surface
alongside the close keys. Pressing `j` SHALL NOT immediately
call the backend; it SHALL push a `JoinConfirmScreen`
confirmation modal whose yes/no default focus is `no`. The
underlying scan-list highlight and `_wifi_selected_key` SHALL NOT
be mutated by `j`, the confirm modal, or its cancellation.

#### Scenario: User opens detail on a non-current SSID and presses j
- **WHEN** the user is associated to `home-5GHz`, opens detail on `cafe-guest`, and presses `j`
- **THEN** a confirmation modal appears reading `Switch to cafe-guest?` with default focus on `Cancel`

#### Scenario: User opens detail on the currently-associated SSID and presses j
- **WHEN** the user opens detail on the SSID they are already on and presses `j`
- **THEN** the confirmation modal still appears (the user may be deliberately forcing a re-associate); confirming runs the same `associate` path

#### Scenario: User cancels the confirmation
- **WHEN** the user presses `Esc` or focuses `Cancel` and presses `Enter`
- **THEN** the confirm modal closes, no backend call is made, and the underlying detail modal is unchanged

### Requirement: The join action SHALL surface its outcome via Textual `notify()`
On confirmation, the App SHALL dispatch the `Backend.associate(
ssid, bssid)` call asynchronously and SHALL render one Textual
`notify()` per outcome class. The notification text SHALL be
locale-aware via the `t()` lookup and SHALL distinguish: success
(with `keychain_saved` hint when true), authentication failure
(wrong password), user cancellation of the OS password sheet,
Enterprise refusal (with the "join from system Wi-Fi menu"
hint), SSID-not-found, and other / unknown errors. Notification
severity SHALL be `information` for success, `warning` for
cancellation, and `error` for authentication failures,
Enterprise refusal, and unknown errors.

#### Scenario: Successful join, Keychain unchanged
- **WHEN** the helper reports `{"ok": true, "bssid": "...", "keychain_saved": false}`
- **THEN** the App emits `notify("Joined cafe-guest", severity="information")`

#### Scenario: Successful join, password newly written to Keychain
- **WHEN** the helper reports `{"ok": true, "bssid": "...", "keychain_saved": true}`
- **THEN** the App emits a notify that mentions the Keychain save (so the user knows the password is now remembered)

#### Scenario: Authentication failure
- **WHEN** the helper exits 7 with `auth_failed`
- **THEN** the App emits an error-severity notify telling the user the password was rejected

#### Scenario: Enterprise refusal
- **WHEN** the helper exits 5 with `enterprise_unsupported`
- **THEN** the App emits an error-severity notify telling the user to join from the system Wi-Fi menu once

#### Scenario: User cancelled the OS password sheet
- **WHEN** the helper exits 6 with `cancelled`
- **THEN** the App emits a warning-severity notify (no error sound), the user is back on the modal as if nothing happened

### Requirement: The detail modal SHALL render a transient `(joining…)` annotation between confirm and the next poll
After the user confirms a join, the App SHALL set an
`_app_joining_to: tuple[str, datetime]` ("SSID, deadline ~10 s")
that the detail modal renders as a sibling state to
`(associated)` in the Identity section heading and in the modal's
title bar. The annotation SHALL clear when (i) the next 1 Hz
`Connection` poll's BSSID matches the joined SSID (success
observed), or (ii) the helper subprocess reports failure
(immediate clear), or (iii) the 10 s deadline expires (give up
on the optimistic annotation, leaving the real association state
as ground truth).

#### Scenario: Successful join reflected by next poll
- **WHEN** the user confirms the join and 2 s later the poller reports `Connection(ssid=cafe-guest)`
- **THEN** the `(joining…)` annotation disappears and the Identity section reads `(associated)` against `cafe-guest`

#### Scenario: Helper reports auth failure immediately
- **WHEN** the helper exits 7 with `auth_failed` ~1 s after confirm
- **THEN** the `(joining…)` annotation clears before the error notify renders

#### Scenario: 10 s elapse with no poll match (e.g. helper hung / poller paused)
- **WHEN** 10 s pass without either a matching poll or a helper failure event
- **THEN** the annotation clears unconditionally; the modal goes back to whatever the real connection state is

### Requirement: The modal footer SHALL document the `j` binding alongside close keys
The footer rendered by `WifiDetailScreen` SHALL document `j` as
the join key in addition to the existing close keys (`Esc / i`).
When the inspected network is Enterprise / 802.1X, the footer
SHALL additionally indicate that `j` is unavailable on this row
and direct the user to the system Wi-Fi menu. The hint SHALL go
through `t()` for ZH translation.

#### Scenario: Personal-network footer
- **WHEN** the user opens detail on a WPA2-Personal AP in EN locale
- **THEN** the footer reads `Esc / i to close · j to join`

#### Scenario: Enterprise-network footer
- **WHEN** the user opens detail on an Enterprise SSID
- **THEN** the footer reads `Esc / i to close · j: join — Enterprise networks must be joined from the system Wi-Fi menu`

#### Scenario: ZH locale
- **WHEN** `DITING_LANG=zh` is set
- **THEN** both the personal and Enterprise footer variants SHALL render in their ZH translations from `i18n.py`

### Requirement: The join confirmation modal SHALL be keyboard-navigable and non-blocking
The `JoinConfirmScreen` SHALL bind `Esc` to cancel, `y` to
confirm, `n` to cancel, `tab` / `shift+tab` to move focus
between buttons, and `Enter` to activate the focused button.
While the confirmation modal is open, the rest of the App's
state (scans, poll, event ring) SHALL keep updating. The
modal SHALL NOT block the Textual event loop.

#### Scenario: Confirm with keyboard
- **WHEN** the user presses `j` then `y`
- **THEN** the confirmation closes and the join is dispatched

#### Scenario: Cancel with keyboard
- **WHEN** the user presses `j` then `n`, or `j` then `Esc`
- **THEN** the confirmation closes, no join is dispatched, and the underlying detail modal regains focus

### Requirement: The join confirmation modal SHALL warn the user that the switch is not hitless
The `JoinConfirmScreen` body SHALL render an explicit one-line warning that the current Wi-Fi connection will be torn down and that all open TCP connections (SSH, video calls, file transfers) bound to the current IP will be reset. The expected gap SHALL be quantified (typical ~2-5 s for WPA2-Personal, longer for Enterprise / 802.1X). The warning text SHALL be locale-aware via `t()` and SHALL be present on every invocation of the modal — including when the user invokes `j` on the currently-associated SSID — so the consent the modal collects is informed.

#### Scenario: Warning is visible on every confirm
- **WHEN** the user presses `j` on any SSID, current or not
- **THEN** the confirmation modal body includes the gap warning text in addition to the `Switch to <SSID>?` prompt

#### Scenario: ZH locale gap warning
- **WHEN** `DITING_LANG=zh` and the user opens the confirmation
- **THEN** the warning renders in its ZH translation from `i18n.py` and the gap quantification is preserved

