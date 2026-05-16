## MODIFIED Requirements

### Requirement: The helper SHALL expose discrete subcommands as the only Python integration surface
The helper SHALL respond to `wifi-scan`, `ble-scan`,
`bluetooth-status`, `notify`, and `associate` subcommands. Python
invokes the helper as a subprocess and reads JSON or JSONL from
stdout; no shared memory, no socket, no file drop. Process
termination is the unambiguous "subcommand finished" signal.

#### Scenario: Wi-Fi scan
- **WHEN** Python runs `diting-tianer wifi-scan`
- **THEN** the helper performs one CoreWLAN scan, prints one JSON object to stdout (schema-versioned), and exits with code 0

#### Scenario: BLE long-running scan
- **WHEN** Python runs `diting-tianer ble-scan`
- **THEN** the helper streams JSONL advertisement events to stdout indefinitely until Python sends SIGTERM

#### Scenario: Bluetooth permission probe
- **WHEN** Python runs `diting-tianer bluetooth-status`
- **THEN** the helper exits 0 if granted, 3 if denied/unauthorized

#### Scenario: Associate to a scanned SSID
- **WHEN** Python runs `diting-tianer associate --ssid <SSID>` with stdin piped (possibly empty)
- **THEN** the helper attempts a CoreWLAN association, prints one JSON object to stdout indicating success / failure, and exits with a code that distinguishes success / Enterprise-unsupported / user-cancelled / auth-failed / SSID-not-found

## ADDED Requirements

### Requirement: The `associate` subcommand SHALL accept the password on stdin, never on argv
The `associate` subcommand SHALL read at most one line from stdin
as the candidate password. Stdin SHALL be closed by the parent
before the helper begins association. The helper SHALL NOT log
the password, write it to stderr, emit it in any JSON payload, or
include it in any `os_log` / `NSLog` call. The password buffer
SHALL be zeroed before subprocess exit. The subcommand SHALL
reject any password supplied as a command-line argument.

#### Scenario: Empty stdin
- **WHEN** Python pipes an empty stdin to `diting-tianer associate --ssid Cafe-Guest`
- **THEN** the helper interprets that as "no caller-supplied password" and proceeds to the Keychain / AppKit-sheet resolution chain

#### Scenario: Password on stdin
- **WHEN** Python pipes `hunter2\n` to `diting-tianer associate --ssid Cafe-Guest`
- **THEN** the helper uses that password directly in the CoreWLAN `associate(toNetwork:password:error:)` call and never echoes it to any output stream

#### Scenario: Password on argv (mis-use)
- **WHEN** anyone runs `diting-tianer associate --ssid Cafe-Guest --password hunter2`
- **THEN** the helper exits 64 with an error message about unsupported flags; no association is attempted

### Requirement: The `associate` subcommand SHALL attempt the saved-credential path before prompting
On a secured network the helper SHALL first call
`CWInterface.associate(toNetwork:password:nil error:)`. macOS's
Wi-Fi stack pulls the SSID's saved password from the System
Keychain when one exists, so this call succeeds without user
interaction for previously-joined networks. The helper SHALL
prompt the user (via the AppKit sheet defined below) only when
this call fails with a "password required" / authentication
error AND no password was piped in on stdin.

#### Scenario: Open network
- **WHEN** the target SSID has security `none`
- **THEN** the helper calls `associate(...password: nil)` and exits 0 with `{"ok": true, "bssid": "...", "keychain_saved": false}`

#### Scenario: Secured network with saved password
- **WHEN** the user previously joined the SSID and macOS holds its password in the System Keychain
- **THEN** the helper's `associate(...password: nil)` call succeeds, no sheet is shown, and the helper exits 0 with `{"ok": true, "bssid": "...", "keychain_saved": false}` (no Keychain write because nothing changed)

#### Scenario: Secured network, no saved password, stdin empty
- **WHEN** the SSID has no Keychain entry and Python supplied no stdin password
- **THEN** the helper shows the AppKit password sheet and proceeds only after the user submits or cancels

### Requirement: The `associate` subcommand SHALL render a native AppKit password sheet when prompting
The helper SHALL display a real `NSPanel` whenever it needs to prompt for a password (secured network, no Keychain entry, no stdin-supplied password). The panel SHALL contain the helper bundle's icon, the prompt
text `Enter the password for "<SSID>"`, an `NSSecureTextField`,
a "Remember this network" `NSButton` checkbox (default ON), a
"Join" default button (Return key), and a "Cancel" button (Esc
key). The panel SHALL be made key and brought to the front via
`NSApp.activate(ignoringOtherApps: true)`. On Join, the helper
SHALL call `CWInterface.associate(toNetwork:password:error:)`
with the typed password. On success with the checkbox ON, the
helper SHALL write the password to the System Keychain via
`+[CWKeychain setWiFiPassword:forSSID:]` and SHALL report
`keychain_saved: true` in its JSON response.

#### Scenario: User joins from the sheet, leaves Remember checked
- **WHEN** the user types the password, leaves "Remember this network" checked, and clicks Join
- **THEN** CoreWLAN associates with the typed password, the helper writes to Keychain, and the helper exits 0 with `{"ok": true, "bssid": "...", "keychain_saved": true}`

#### Scenario: User joins from the sheet, unchecks Remember
- **WHEN** the user types the password, unchecks "Remember this network", and clicks Join
- **THEN** CoreWLAN associates, the helper SHALL NOT write to Keychain, and the response carries `keychain_saved: false`

#### Scenario: User cancels the sheet
- **WHEN** the user presses Esc / clicks Cancel
- **THEN** the helper exits 6 with `{"error": "user cancelled", "code": "cancelled"}` on stdout; no association attempt is made

#### Scenario: Wrong password
- **WHEN** the user submits an incorrect password
- **THEN** the helper exits 7 with `{"error": "authentication failed", "code": "auth_failed"}`; the sheet SHALL NOT re-prompt within the same subprocess (Python invokes a fresh helper for retries)

#### Scenario: Keychain write fails (private API unavailable)
- **WHEN** the association succeeds but `+[CWKeychain setWiFiPassword:forSSID:]` returns an error or nil
- **THEN** the helper SHALL exit 0 (the join itself worked), with `{"ok": true, "bssid": "...", "keychain_saved": false}`

### Requirement: The `associate` subcommand SHALL refuse Enterprise / 802.1X networks without prompting
The helper SHALL exit 5 immediately when the target SSID's `CWNetwork` reports only Enterprise security variants (any of `wpa2Enterprise`, `wpa3Enterprise`, `wpa2WPA3Enterprise`, or other 802.1X-tagged values) and no non-Enterprise alternative. The response SHALL be emitted
with `{"error": "<localized hint>", "code":
"enterprise_unsupported"}` on stdout. The helper SHALL NOT show
the AppKit sheet, SHALL NOT call `associate(...)`, and SHALL NOT
pop any system dialog. The hint SHALL tell the user to join from
the system Wi-Fi menu once so subsequent joins use the saved
credential.

#### Scenario: Enterprise SSID
- **WHEN** the target SSID is `eduroam` and its `CWNetwork` reports `wpa2Enterprise`
- **THEN** the helper exits 5 with the `enterprise_unsupported` code and no association is attempted

#### Scenario: Mixed Personal + Enterprise SSID
- **WHEN** the target SSID supports both `wpa2Personal` and `wpa2Enterprise` (rare but legal)
- **THEN** the helper treats the network as Personal and proceeds with the normal `associate(password: nil)` path

### Requirement: The `associate` subcommand SHALL fail loudly when the SSID is not in scan range
The helper SHALL refuse to attempt association for SSIDs not
present in a fresh CoreWLAN scan, on the assumption that the
Python caller derived the SSID from a stale scan the helper has
no record of. The helper SHALL exit 8 with `{"error": "...",
"code": "ssid_not_found"}`.

#### Scenario: SSID disappeared between scan and join
- **WHEN** Python opens detail on `Plaza-Wi-Fi`, the AP shuts down, the user confirms join 30 s later, and the helper's pre-flight scan no longer sees the SSID
- **THEN** the helper exits 8 with `ssid_not_found` and no associate call is made

### Requirement: The `associate` response SHALL carry a schema integer independent of the `wifi-scan` schema
The `associate` subcommand's JSON response SHALL include
`"schema": <int>` at top level. The integer SHALL be independent
of the `wifi-scan` schema (a bump on one SHALL NOT force a bump
on the other) and SHALL bump only when fields are removed or
renamed.

#### Scenario: Python parses a future associate response with new fields
- **WHEN** Python (older) parses a `schema=1` response that adds a `link_speed_mbps` field in a future helper version
- **THEN** Python ignores the unknown field and reads the known fields normally
