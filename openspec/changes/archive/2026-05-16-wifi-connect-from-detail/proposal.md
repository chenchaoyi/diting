## Why

The Wi-Fi detail modal (opened with `i` / `enter` on a row in the
Nearby BSSIDs panel) is purely a read-only inspector today: it tells
the user everything we know about an AP but offers no way to act on
that knowledge. The closest existing operation is `c` (`force_reroam`),
which power-cycles the radio so the OS re-picks the best BSSID for the
**currently-saved** SSID — useful for sticky-AP cases but unable to
switch the user to a *different* network they can see in the list.

When the user opens detail on a neighbouring SSID — a guest network,
a different lab AP, the office's 5 GHz alternative — and decides
"I want to be on that one", they have to leave the TUI, click the
menubar Wi-Fi icon, hunt the same row visually, and click it. The
information was already in front of them; the action was not.

## What Changes

### Wi-Fi detail (`wifi-detail-modal`) — new join action

- New `j` binding on `WifiDetailScreen` titled "Join this network".
  Opens a yes/no confirmation modal (`Switch to <SSID>?` — explicit
  because switching tears down the current connection and is not what
  the user wants if they tapped `j` by reflex). On confirm, the App
  dispatches an `associate` call to the backend and surfaces the
  result via Textual `notify()`.
- `c` (force re-roam) is unchanged. The two actions are deliberately
  different: `c` says "re-pick the best BSSID for the SSID I'm already
  on", `j` says "move me to *this* SSID".
- Enterprise / 802.1X rows SHALL show `j` as disabled-with-hint:
  pressing it surfaces a one-line notification telling the user to
  use the system Wi-Fi menu (EAP credentials cannot flow through
  `CWInterface.associate(password:)`).
- The Identity section's `(associated)` annotation gains a sibling
  state: `(joining…)` for the ~2-5 s window between `associate` call
  and the next poll picking up the new BSSID.

### macOS helper (`macos-helper`) — new `associate` subcommand

- New subcommand: `diting-tianer associate --ssid <SSID> [--bssid <BSSID>]`.
  Reads optional password from **stdin** (never argv — `ps` would
  otherwise leak it). Exits 0 on success, non-zero with a structured
  JSON error on stderr otherwise (`{"error": "...", "code": "..."}`).
- Resolution order inside the helper:
  1. Open network → `CWInterface.associate(toNetwork:password:nil error:)`.
  2. Secured network, Keychain entry exists for this SSID →
     `CWInterface.associate(toNetwork:password:nil error:)` succeeds
     because CoreWLAN's lower layers pull the saved password
     (this is the "saved password, directly try" path the user asked
     for — it's just the macOS native behaviour).
  3. Secured network, no Keychain entry → helper renders a **native
     `NSPanel` with `NSSecureTextField`** (the helper is already a
     foregroundable `.app`, so this is a real macOS password sheet,
     not a TUI imitation). On submit, helper calls `associate(...)`
     with the typed password and — on success — writes the password
     back to Keychain via `+[CWKeychain setWiFiPassword:forSSID:]`
     so subsequent joins skip the prompt.
  4. Enterprise / 802.1X → helper exits 5 with
     `{"error": "...", "code": "enterprise_unsupported"}` without
     prompting. The Python side renders the system-Wi-Fi-menu hint.
- Exit codes (new for `associate`): 0 ok, 64 bad args, 5
  enterprise unsupported, 6 user cancelled the password sheet, 7
  wrong password / association failed, 8 SSID not currently in
  scan range.
- JSON `schema` on the success path includes the joined BSSID + the
  `keychain_saved: bool` flag so Python can render an accurate
  "saved to Keychain" hint or omit it.

## Capabilities

### New Capabilities
<!-- none — both surfaces already exist as specs -->

### Modified Capabilities
- `wifi-detail-modal`: the modal's keyboard-binding set currently
  binds only `escape`/`i`/`q` (close); the modal SHALL also bind `j`
  to initiate a join of the inspected SSID, gated through a
  confirmation modal.
- `macos-helper`: the "discrete subcommands as the only Python
  integration surface" requirement extends from
  `wifi-scan` / `ble-scan` / `bluetooth-status` / `notify` to also
  include `associate`. Password input SHALL flow via stdin; the
  helper SHALL render the password prompt as a native AppKit panel
  when no Keychain entry exists; Enterprise networks SHALL be
  rejected without prompting.

## Impact

- `helper/Sources/diting-tianer/main.swift`:
  - New `associate` case in the top-level `switch args[1]`.
  - New `runAssociateAndExit(args:)` driver that reads password
    from stdin, calls `CWInterface.associate(toNetwork:password:error:)`,
    and on the no-Keychain path drives an `NSPanel` +
    `NSSecureTextField` sheet on the main run loop (same
    `dispatchMain()` pattern the `scan` subcommand already uses).
  - Reuse existing CoreLocation registration handshake — same
    Location-Services-required gate as `scan`.
- `src/diting/_helper.py`: new `associate(helper_path, ssid, *,
  bssid, password=None) -> AssociateResult` that spawns the helper
  with stdin-piped password and parses the JSON status from stderr.
- `src/diting/macos_backend.py` and `src/diting/backend.py`:
  new `Backend.associate(ssid, bssid)` method (no-op fallback in
  `NullBackend`).
- `src/diting/tui.py`:
  - `WifiDetailScreen.BINDINGS` gains `Binding("j", ...)`.
  - `DitingApp.action_wifi_join()` — dispatches confirmation modal,
    then backend call, then notify.
  - New small `JoinConfirmScreen(ModalScreen)`.
- `src/diting/i18n.py`: new EN keys + ZH translations for the
  confirm prompt, the success / failure / Enterprise / cancelled
  notifications, and the `(joining…)` annotation.
- `tests/`: new unit tests for the parser of the helper's
  `associate` JSON response, a fake-backend hook for the App
  action, and a Textual smoke test that the `j` binding opens the
  confirmation modal but does NOT call associate until the user
  confirms.
- `tests/TESTING.md` (EN + ZH) gains a row per new requirement.
- `README.md` (EN + ZH) hotkey table gains `j` row in the Wi-Fi
  view section.
- Helper schema bump: `associate` is a new subcommand, not a new
  field on an existing response, so the global helper schema
  integer for `wifi-scan` does NOT bump. The `associate` response
  carries its own `"schema": 1` from day one.
- Privacy / security: helper SHALL NOT log the password to stdout,
  stderr, or `os_log`. Stdin reads SHALL be drained into a single
  Swift `String` and that buffer SHALL be zeroed after the
  `associate` call returns.
- Out of scope: BSSID-pinned association (CoreWLAN's
  `associate(toEnterpriseNetwork:...)` allows BSSID hints but
  `associate(toNetwork:password:)` does not — we record BSSID for
  audit logging only). Disconnect / forget-network. Anything that
  modifies the user's saved-network preference order.
