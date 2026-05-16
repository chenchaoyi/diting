## ADDED Requirements

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
