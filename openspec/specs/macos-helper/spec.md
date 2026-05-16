# macos-helper Specification

## Purpose

Defines the contract for the Swift helper bundle (`diting-tianer.app`)
that owns the macOS TCC permissions diting needs and exposes a
subprocess interface to the Python TUI. Without the helper, macOS 14.4+
redacts SSID / BSSID in CoreWLAN scans (no Location Services grant for
a Terminal-launched Python process) and refuses to enter
`CBManagerStatePoweredOn` on the BLE side. The helper is the *only*
component that holds those grants and brokers data to Python via stdin
/ stdout.
## Requirements
### Requirement: The helper SHALL ship as an `.app` bundle whose cdhash holds the user's TCC grants
The helper SHALL be installed in-tree at `helper/diting-tianer.app`
and SHALL NOT be moved to `/Applications/` after a TCC grant. macOS
TCC keys grants by code-design hash (cdhash); copying or moving the
bundle changes the cdhash and forces the user to re-grant
Location Services and Bluetooth permissions.

#### Scenario: First-time install
- **WHEN** the user runs `./helper/build.sh` and then `open helper/diting-tianer.app`
- **THEN** macOS shows the Location Services + Bluetooth prompts and the user clicks Allow once each

#### Scenario: Bundle moved to /Applications
- **WHEN** the user copies the bundle to `/Applications/` after granting permission
- **THEN** the copy has a different cdhash and requires fresh grants — diting re-prompts via the helper auto-launch path

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

### Requirement: Output JSON SHALL carry an explicit `schema` integer for the wifi-scan response
The wifi-scan JSON payload SHALL include `"schema": <int>` at top level.
Consumers SHALL accept any schema version and tolerate added fields;
the helper SHALL bump the schema only when fields are removed or
renamed, never when fields are added.

#### Scenario: Older Python reading newer schema
- **WHEN** the bundled Python parses a `schema=5` payload that adds a `xyz` field
- **THEN** the parser ignores `xyz` and consumes every previously-known field

#### Scenario: Field rename (rare)
- **WHEN** the helper renames `country_code` to `cc` in a future release
- **THEN** the schema integer increments and Python emits a "helper too new, please upgrade" error rather than silently producing wrong output

### Requirement: The BLE scan stream SHALL emit one JSON object per advertisement
Each line of `ble-scan` stdout SHALL be a single JSON object terminated
with `\n`. The JSONL stream SHALL be safely tail-able and pipe-friendly:
no embedded newlines, no partial-write framing, no stderr noise on the
hot path. Connected-peripheral-list snapshots SHALL be emitted as
separate JSON objects identified by `"connected_snapshot": true`.

#### Scenario: Tail of helper output
- **WHEN** a user runs `diting-tianer ble-scan | jq .`
- **THEN** every advertisement renders as a valid pretty-printed JSON object

#### Scenario: Pipe to head
- **WHEN** a user runs `diting-tianer ble-scan | head -n 10`
- **THEN** the helper is killed with SIGPIPE after head closes its stdin and does not hang

### Requirement: BLE advertisement objects SHALL plumb the `CBAdvertisementData` dict fields needed by downstream decoders
The helper SHALL emit, for each advertisement received from
CoreBluetooth's `centralManager(_:didDiscover:advertisementData:rssi:)`
callback, the following fields when CoreBluetooth provides them:

- `id` — peripheral UUID
- `rssi_dbm` — int (omitted when CoreBluetooth's 127 sentinel
  appears, or when the value is implausible ≥ 0 dBm)
- `is_connectable` — bool
- `name` — local name when present
- `service_uuids` — list of strings, when present
- `manufacturer_id` + `manufacturer_hex` — when manufacturer-specific
  data is present (≥ 2 bytes)
- `service_data` — `{uuid: hex_string}`, when present (schema-4+)
- `tx_power_dbm` — int, when present (schema-4+)
- `solicited_service_uuids` — list of strings, when present (schema-4+)
- `overflow_service_uuids` — list of strings, when present (schema-4+)
- `type` — Apple Continuity / Microsoft CDP type label, when the
  helper recognises the manufacturer-data byte pattern
- `device_class` — Apple Nearby Info device-class nibble decoded
  ("iPhone" / "iPad" / "Mac" / "HomePod" / "Apple Watch" / "Apple TV")

Fields not present in the advertisement SHALL be omitted from the JSON
object, NOT emitted with null / empty-string sentinels.

#### Scenario: Advertisement with full fields
- **WHEN** an iPhone broadcasts a Nearby Info packet (cid 76, type 0x10)
- **THEN** the JSON object contains `id`, `rssi_dbm`, `is_connectable`, `manufacturer_id=76`, `manufacturer_hex`, `device_class="iPhone"`, and `tx_power_dbm` (when reported)

#### Scenario: Service-only beacon
- **WHEN** an Eddystone beacon broadcasts service-data on FEAA without a manufacturer-specific data field
- **THEN** the JSON object contains `service_uuids=["FEAA"]` and `service_data={"FEAA": "<hex>"}` and OMITS `manufacturer_id` / `manufacturer_hex`

### Requirement: Connected-peripheral snapshots SHALL come from `IOBluetoothDevice.pairedDevices()`, not CoreBluetooth
The helper SHALL enumerate connected peripherals via the legacy
`IOBluetoothDevice` Objective-C bridge, NOT
`CBCentralManager.retrieveConnectedPeripherals(...)`. CoreBluetooth's
roster excludes system-paired keyboards / mice / headphones — exactly
the peripherals users most want to see in the BLE panel.

#### Scenario: Mac with a paired Magic Keyboard and AirPods
- **WHEN** the helper emits a connected snapshot
- **THEN** both the Magic Keyboard and AirPods appear in the snapshot's `ids` list, even though CoreBluetooth would have returned an empty roster

#### Scenario: Connected peripheral identifier format
- **WHEN** the helper emits a connected entry
- **THEN** the `id` field is a colon-separated lowercase BT MAC (`38-09-fb-0b-be-60` style with dashes), NOT a 128-bit per-host UUID

### Requirement: The helper SHALL be auto-detectable from the Python side without configuration
The Python `_helper.find_helper()` SHALL locate the helper bundle
without the user having to set `PATH` or env vars. The function
SHALL search the following locations in order, returning the first
hit:

1. `DITING_HELPER` env var (full path to the bundle OR the binary
   inside it) — escape hatch for contributors testing a non-default
   build location
2. `<repo>/helper/diting-tianer.app` relative to the source root —
   in-place developer build picked up automatically when `diting`
   is run via `uv run` from a repo checkout
3. `/Applications/diting-tianer.app` — back-compat for users who
   moved the bundle into `/Applications` before the in-place flow
   was the recommended developer path
4. `~/Applications/diting-tianer.app` — same back-compat for
   users who installed to their personal Applications folder
5. `~/Library/Application Support/diting/diting-tianer.app` —
   the install location used by the curl-bash one-line installer

Search order MUST keep the in-repo dev build first so contributors
running `uv run diting` from a checkout always pick up their
freshly-`make helper`ed bundle even if they also have the
one-line installer's copy in place.

#### Scenario: Developer with both a repo checkout and a one-line install
- **WHEN** a contributor has both `<repo>/helper/diting-tianer.app` (from `make helper`) and `~/Library/Application Support/diting/diting-tianer.app` (from the curl-bash installer)
- **THEN** `find_helper()` returns the in-repo path; the Application Support copy is shadowed

#### Scenario: End user with only the one-line install
- **WHEN** a user has no repo checkout, no /Applications copy, only `~/Library/Application Support/diting/diting-tianer.app`
- **THEN** `find_helper()` returns the Application Support path

#### Scenario: Pip install without source AND without a one-line install
- **WHEN** diting is installed via `pip install diting` (no source tree) and the helper bundle is not present at any of the five search locations
- **THEN** `find_helper()` returns `None`, and the BLE / Wi-Fi paths fall back to direct CoreWLAN (which produces redacted scan results until the user installs the helper bundle)

#### Scenario: `DITING_HELPER` env override
- **WHEN** `DITING_HELPER=/Volumes/Builds/diting-tianer.app` is set
- **THEN** `find_helper()` returns that path, ignoring every other location

### Requirement: The helper SHALL fail fast and loud on TCC denial
The helper SHALL exit with code 3 and emit a single line
`bluetooth unauthorized` to stderr when it detects that Bluetooth
permission has been denied (e.g. the user clicked Don't Allow on the
prompt). Python treats exit code 3 as the canonical "permission
denied" signal and surfaces a state-specific UI message rather than
a generic error.

#### Scenario: User clicks Don't Allow on Bluetooth prompt
- **WHEN** the user denies the BLE permission and Python spawns the helper
- **THEN** the helper exits 3 immediately, Python's BLE poller transitions to permission_state="denied", and the BLE panel renders "(BLE permission required)" rather than "scanning..."

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

