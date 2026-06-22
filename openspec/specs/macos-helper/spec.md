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
The helper SHALL respond to `wifi-scan`, `ble-scan`, `bluetooth-status`, and `notify` subcommands. Python invokes the helper as a subprocess and reads JSON or JSONL from stdout (or a temp file for the LaunchServices-mediated `wifi-scan` path); no shared memory, no socket, no file drop. Process termination is the unambiguous "scan finished" / "notification sent" signal.

#### Scenario: Wi-Fi scan
- **WHEN** Python runs `diting-tianer wifi-scan`
- **THEN** the helper performs one CoreWLAN scan, prints one JSON object to stdout (schema-versioned), and exits with code 0

#### Scenario: BLE long-running scan
- **WHEN** Python runs `diting-tianer ble-scan`
- **THEN** the helper streams JSONL advertisement events to stdout indefinitely until Python sends SIGTERM

#### Scenario: Bluetooth permission probe
- **WHEN** Python runs `diting-tianer bluetooth-status`
- **THEN** the helper exits 0 if granted, 3 if denied/unauthorized

#### Scenario: Notification send
- **WHEN** Python runs `diting-tianer notify --title T --body B`
- **THEN** the helper posts a UserNotification under the bundle's identity (icon = diting logo) and exits 0 within 3 seconds, best-effort

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
The helper SHALL resolve a usable password for the target SSID via the following order before showing the AppKit sheet. For open networks (`CWNetwork.supportsSecurity(.none)`) the helper SHALL call `CWInterface.associate(toNetwork:password:nil error:)` without any Keychain interaction. For secured networks the helper SHALL first attempt to read the SSID's password from its own login-keychain entry via `SecItemCopyMatching` against `kSecClass = kSecClassGenericPassword`, `kSecAttrService = "com.chenchaoyi.diting.tianer"`, `kSecAttrAccount = <SSID>`. On a successful read the helper SHALL pass the recovered password explicitly to `CWInterface.associate(toNetwork:password:error:)`. The helper SHALL NOT rely on CoreWLAN's lower layers to silently pull from the System Keychain (empirically that path is reserved for Apple-signed processes with the `com.apple.wifi.system-services` entitlement and returns an authentication error for third-party helpers). The helper SHALL NOT query `kSecAttrService = "AirPort"` (System keychain) — that path is gated by the `authenticate-admin-nonshared` Authorization Services rule which forces an admin-password dialog on every read and does not accept biometric substitution. The helper SHALL prompt the user (via the AppKit sheet defined below) only when the Keychain read returns no data AND no password was piped in on stdin.

#### Scenario: Open network
- **WHEN** the target SSID has security `none`
- **THEN** the helper calls `associate(...password: nil)` and exits 0 with `{"ok": true, "bssid": "...", "keychain_saved": false, "keychain_read": "skipped-open"}`

#### Scenario: Secured network with diting-cached password
- **WHEN** the user previously joined the SSID via diting's sheet and the cached password lives in the login keychain under `kSecAttrService = "com.chenchaoyi.diting.tianer"`
- **THEN** the OS renders a Touch ID / login-password prompt (the access-control gate defined below); on successful gesture the helper recovers the password, calls `associate(...password: <recovered>)`, no sheet is shown, and the helper exits 0 with `{"ok": true, "bssid": "...", "keychain_saved": false, "keychain_read": "diting"}` (no Keychain write because nothing changed)

#### Scenario: Secured network, no cached password, stdin empty
- **WHEN** `SecItemCopyMatching` returns `errSecItemNotFound` AND Python supplied no stdin password
- **THEN** the helper shows the AppKit password sheet and proceeds only after the user submits or cancels; the response carries `keychain_read: "miss"`

#### Scenario: Secured network, user dismisses the Touch ID prompt
- **WHEN** `SecItemCopyMatching` returns `errSecUserCanceled` (user tapped Cancel on the Touch ID dialog or biometric authentication failed and the user dismissed the passcode fallback)
- **THEN** the helper falls through to the AppKit sheet (same path as `errSecItemNotFound`); the response carries `keychain_read: "denied"`. The cached entry remains untouched.

#### Scenario: Secured network, AirPort-service probe is skipped
- **WHEN** the SSID has a password macOS itself saved under `AirPort/<SSID>` in the System keychain (e.g. the user joined this SSID through the menu-bar Wi-Fi panel)
- **THEN** the helper SHALL NOT attempt to read that entry (would force an admin-password dialog every join — confirmed unusable); it treats the lookup as a miss and falls through to its sheet so the user can type once and have the value cached under diting's own service

### Requirement: The `associate` subcommand SHALL render a native AppKit password sheet when prompting
The helper SHALL display a real `NSPanel` whenever it needs to prompt for a password (secured network, no diting-cached entry, no stdin-supplied password). The panel SHALL contain the helper bundle's icon, the prompt text `Enter the password for "<SSID>"`, an `NSSecureTextField`, a "Remember this network" `NSButton` checkbox (default ON), a "Join" default button (Return key), and a "Cancel" button (Esc key). The panel SHALL be made key and brought to the front via `NSApp.activate(ignoringOtherApps: true)`. On Join, the helper SHALL call `CWInterface.associate(toNetwork:password:error:)` with the typed password. On association success with the checkbox ON, the helper SHALL persist the password to the user's login keychain via `SecItemAdd` against `kSecClass = kSecClassGenericPassword`, `kSecAttrService = "com.chenchaoyi.diting.tianer"`, `kSecAttrAccount = <SSID>`, with a `kSecAttrAccessControl` built by `SecAccessControlCreateWithFlags(nil, kSecAttrAccessibleWhenUnlockedThisDeviceOnly, .userPresence, nil)` (see the new ACL requirement below). On `errSecDuplicateItem` the helper SHALL fall back to `SecItemUpdate` against the same query, writing only `kSecValueData` and preserving the existing `kSecAttrAccessControl` from the original add. The helper SHALL NOT write to the System Keychain. The helper SHALL NOT write to `kSecAttrService = "AirPort"` (would conflict with macOS-managed entries). On any Keychain write failure the helper SHALL exit 0 (the join itself worked) with `keychain_saved: false`. Successful writes SHALL set `keychain_saved: true`.

#### Scenario: User joins from the sheet, leaves Remember checked
- **WHEN** the user types the password, leaves "Remember this network" checked, and clicks Join
- **THEN** CoreWLAN associates with the typed password, the helper performs `SecItemAdd` (or `SecItemUpdate` on duplicate) to its login-keychain service namespace with `.userPresence` access control, and exits 0 with `{"ok": true, "bssid": "...", "keychain_saved": true, "keychain_read": "miss"}`

#### Scenario: User joins from the sheet, unchecks Remember
- **WHEN** the user types the password, unchecks "Remember this network", and clicks Join
- **THEN** CoreWLAN associates, the helper SHALL NOT call `SecItemAdd` / `SecItemUpdate`, and the response carries `keychain_saved: false`

#### Scenario: User cancels the sheet
- **WHEN** the user presses Esc / clicks Cancel
- **THEN** the helper exits 6 with `{"error": "user cancelled", "code": "cancelled"}` on stdout; no association attempt is made and no Keychain write occurs

#### Scenario: Wrong password
- **WHEN** the user submits an incorrect password
- **THEN** the helper exits 7 with `{"error": "authentication failed", "code": "auth_failed"}`; the sheet SHALL NOT re-prompt within the same subprocess (Python invokes a fresh helper for retries) and no Keychain write occurs

#### Scenario: Keychain write fails
- **WHEN** the association succeeds but `SecItemAdd` (or the fallback `SecItemUpdate` on duplicate) returns any status other than `errSecSuccess`
- **THEN** the helper SHALL exit 0 (the join itself worked) with `{"ok": true, "bssid": "...", "keychain_saved": false}`; failure SHALL NOT abort the join

#### Scenario: Stale cached password rotates in place
- **WHEN** an SSID's password is rotated on the AP, the helper's cached read returns the stale value, `associate(...password: <stale>)` fails with `auth_failed`, the user re-invokes from the sheet, and `SecItemAdd` returns `errSecDuplicateItem`
- **THEN** the helper SHALL call `SecItemUpdate` with the same query and only `kSecValueData` in the update attributes; the existing `kSecAttrAccessControl` is preserved so the user does NOT re-grant the `.userPresence` ACL

### Requirement: The `associate` subcommand SHALL refuse Enterprise / 802.1X networks without prompting
The helper SHALL exit 5 immediately when the target SSID's `CWNetwork` reports only Enterprise security variants (any of `wpa2Enterprise`, `wpa3Enterprise`, `wpa2WPA3Enterprise`, or other 802.1X-tagged values) and no non-Enterprise alternative. The response SHALL be emitted with `{"error": "<localized hint>", "code": "enterprise_unsupported"}` on stdout. The helper SHALL NOT show the AppKit sheet, SHALL NOT call `associate(...)`, SHALL NOT read from or write to the Keychain, and SHALL NOT pop any system dialog. The hint SHALL tell the user to join from the system Wi-Fi menu once so subsequent joins use the saved credential.

#### Scenario: Enterprise SSID
- **WHEN** the target SSID is `eduroam` and its `CWNetwork` reports `wpa2Enterprise`
- **THEN** the helper exits 5 with the `enterprise_unsupported` code and no association is attempted

#### Scenario: Mixed Personal + Enterprise SSID
- **WHEN** the target SSID supports both `wpa2Personal` and `wpa2Enterprise` (rare but legal)
- **THEN** the helper treats the network as Personal and proceeds with the normal saved-credential resolution path (login-keychain lookup → sheet on miss)

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

### Requirement: Cached Wi-Fi passwords SHALL be stored in the user's login keychain under a diting-owned service with a `.userPresence` access-control flag
The helper SHALL write all cached Wi-Fi passwords to the user's default keychain (the login keychain on every standard macOS install) under `kSecClass = kSecClassGenericPassword`, `kSecAttrService = "com.chenchaoyi.diting.tianer"`, `kSecAttrAccount = <SSID>`. Every `SecItemAdd` SHALL attach a `kSecAttrAccessControl` produced by `SecAccessControlCreateWithFlags(nil, kSecAttrAccessibleWhenUnlockedThisDeviceOnly, .userPresence, nil)`. The `.userPresence` flag resolves to Touch ID, Apple Watch unlock, or the device passcode at runtime — macOS selects the modality based on hardware capabilities and System Settings. The helper SHALL NOT use `.biometryAny` (excludes Macs without a sensor) or `.biometryCurrentSet` (would invalidate the entry when the user adds a new fingerprint). The helper SHALL NOT set `kSecAttrSynchronizable` (no iCloud Keychain sync — Wi-Fi passwords remain on the local Mac). Subsequent reads of the cached entry via `SecItemCopyMatching` trigger the OS-rendered user-presence dialog. The helper SHALL pass `kSecUseOperationPrompt` on every read with a locale-aware reason string sourced from the `LANG` / `LC_ALL` environment (EN: `diting wants to join Wi-Fi "<SSID>"`; ZH: `diting 想要连接 Wi-Fi "<SSID>"`). The cached value's lifetime is tied to the helper's writes (and to the user's Keychain Access.app); the helper SHALL NOT delete entries on its own — including on `errSecUserCanceled` or on `auth_failed`. Stale-password recovery is the user's explicit re-submission via the AppKit sheet, which routes through `SecItemUpdate` per the password-sheet requirement above.

#### Scenario: First successful write attaches `.userPresence`
- **WHEN** the helper writes a freshly-typed password via `SecItemAdd` and the call returns `errSecSuccess`
- **THEN** the entry has `kSecAttrAccessControl` set such that subsequent `SecItemCopyMatching` on this entry will prompt for user presence (Touch ID / passcode) before returning the password material

#### Scenario: Touch ID succeeds, password is recovered
- **WHEN** the helper calls `SecItemCopyMatching` against a `.userPresence`-protected entry and the user authenticates via Touch ID
- **THEN** the call returns `errSecSuccess` with the password Data and the helper proceeds to `associate(toNetwork:password:error:)` silently

#### Scenario: Mac without Touch ID hardware
- **WHEN** the helper calls `SecItemCopyMatching` against a `.userPresence`-protected entry on a Mac mini or similar device without a biometric sensor or paired Apple Watch
- **THEN** macOS renders the login-password (NOT admin-password) prompt; on submission the call returns `errSecSuccess` and the helper proceeds normally

#### Scenario: User cancels the user-presence dialog
- **WHEN** the user taps Cancel on the Touch ID / login-password prompt
- **THEN** `SecItemCopyMatching` returns `errSecUserCanceled`; the helper folds this to a "miss" and falls through to the AppKit sheet — the cached entry SHALL NOT be deleted

#### Scenario: Helper-rebuild cdhash change preserves the ACL
- **WHEN** the contributor rebuilds the helper bundle (`make helper`) which changes the bundle's code-signing hash, then invokes `j` on an SSID with a pre-existing cached entry
- **THEN** the user-presence prompt fires once per read regardless of cdhash (the `.userPresence` ACL is gated on user gesture, not on calling-app identity); the user is NOT forced to re-grant a per-cdhash "Always Allow" the way they would be for ACL-list-protected items

### Requirement: The helper bundle SHALL ship the diting logo as its AppIcon
The helper bundle SHALL include `Contents/Resources/AppIcon.icns` derived from `docs/design/diting-design/assets/logo-mark.svg`. `Info.plist` SHALL declare `CFBundleIconFile=AppIcon`. The icon SHALL be packed by `helper/build.sh` via `iconutil --convert icns` from a checked-in `helper/Resources/AppIcon.iconset/` containing the standard macOS sizes (16/32/64/128/256/512/1024 px at 1x and 2x where applicable). No build-time SVG rasteriser is required; PNG sources live in the repo.

#### Scenario: Bundle has a logo icon in Finder and in TCC prompts
- **WHEN** the user views `~/Library/Application Support/diting/diting-tianer.app` in Finder
- **THEN** the icon shown is the diting logo, not the generic .app placeholder
- **WHEN** macOS surfaces a TCC prompt whose header pulls the bundle icon (Location Services, Notifications)
- **THEN** the prompt thumbnail is the diting logo

#### Scenario: Build produces AppIcon.icns
- **WHEN** a contributor runs `helper/build.sh`
- **THEN** the produced bundle has `Contents/Resources/AppIcon.icns` present
- **AND** the build step does NOT require any tool beyond what macOS ships (`iconutil`, `sips`, etc. — no `librsvg`, no Inkscape)

### Requirement: The helper SHALL request Location, Bluetooth, and Notifications permissions in a sequenced flow at install time
When launched as a GUI app (`open <bundle>`), the helper SHALL request the three TCC permissions in the order Location → Bluetooth → Notifications. Each request SHALL fire only after the previous one's authorization callback resolves to a non-`.notDetermined` state (Allow, Don't Allow, restricted, or denied — any settled state). The user SHALL see at most one macOS TCC prompt on screen at any time during install, on top of the persistent helper status window.

The status window SHALL render three lines (one per permission) and update each line's status text as the corresponding callback resolves. The window SHALL auto-close ~4 seconds after the third permission's state has settled.

The status window SHALL be laid out top-aligned: its content SHALL be pinned to the top of the content view with consistent padding and the window SHALL be sized to fit its content, leaving no large empty region. The window SHALL show, from the top down, the bundle's app icon (the diting logo), a bold title, a secondary-color explanatory paragraph, and one status row per permission. Each status row SHALL carry a leading status glyph whose symbol and color reflect that permission's state — pending (not yet reached), in-progress (awaiting the user's decision, rendered in the diting brand color), granted, or denied/restricted — alongside the permission's status text.

If any permission resolves to denied or restricted, the helper SHALL continue to the next permission rather than aborting the flow, and the status line for the denied permission SHALL include a "open System Settings → Privacy & Security → ..." hint.

#### Scenario: User clicks Allow on all three
- **WHEN** the user runs install.sh and clicks Allow on Location, then Allow on Bluetooth, then Allow on Notifications
- **THEN** macOS shows exactly one prompt at a time, never two simultaneously
- **AND** the status window shows each permission's row turn from in-progress to a granted glyph as it lands, in order Location → Bluetooth → Notifications
- **AND** the window auto-closes ~4 seconds after the third grant

#### Scenario: User denies a permission mid-flow
- **WHEN** the user clicks Don't Allow on Bluetooth
- **THEN** the status window shows the Bluetooth row with a denied glyph and a Settings hint
- **AND** the helper still requests Notifications next (does not abort the flow)
- **AND** the window auto-closes after the Notifications outcome resolves

#### Scenario: Window is legibly laid out
- **WHEN** the helper status window appears
- **THEN** its content is top-aligned with the diting app icon at the top and one status row per permission, each with a leading status glyph
- **AND** there is no large empty region above or below the content

### Requirement: The helper SHALL expose a `notify` subcommand for sending macOS notifications under the bundle's identity
The helper SHALL accept `diting-tianer notify --title <T> --body <B>` and SHALL post a `UNUserNotificationCenter` notification with the given title and body. Because the helper is a bundle with a `CFBundleIdentifier` and an icon, macOS SHALL attach the bundle icon (the diting logo) to the notification thumbnail.

If `UNUserNotificationCenter.requestAuthorization` was not granted prior, the helper SHALL request it once and proceed only if granted; otherwise it SHALL exit silently. The subprocess SHALL exit within 3 seconds regardless of delivery state (best-effort).

#### Scenario: Watchdog fires a notification
- **WHEN** the Python TUI's anomaly watchdog invokes `diting-tianer notify --title diting --body "Latency spike on gateway:..."`
- **THEN** macOS Notification Center shows a notification with title "diting", the watchdog's body text, and the diting-logo icon
- **AND** the helper subprocess exits with code 0 within 3 seconds

#### Scenario: User has revoked Notifications permission
- **WHEN** the user revokes Notifications for the helper in System Settings and the watchdog later invokes `notify`
- **THEN** the helper subprocess exits silently with no error to the caller
- **AND** no notification appears

### Requirement: The helper SHALL expose a `notification-status` probe subcommand

The helper SHALL accept `diting-tianer notification-status`, which SHALL query
`UNUserNotificationCenter.getNotificationSettings` and exit `0` when the bundle's
Notifications authorization is granted (`.authorized` or `.provisional`) and
non-zero otherwise (`.denied` / `.notDetermined` / timeout). It SHALL print no
JSON — it is an exit-code-only probe, mirroring `bluetooth-status` — and SHALL
exit within a few seconds regardless of outcome. This lets the Python side VERIFY
the Notifications grant (not merely request it) so `diting setup` can report a
trustworthy Notifications state.

Because the probe is exit-code-only and adds no field to any JSON response, it
SHALL NOT change the `wifi-scan` or `associate` schema integers. The subcommand
SHALL appear in the helper's `--help` output so the Python side can detect
whether a given (possibly older) helper supports it and degrade gracefully when
it does not.

#### Scenario: Notifications granted
- **WHEN** the bundle has been granted Notifications and `diting-tianer notification-status` runs
- **THEN** it exits 0 with no stdout JSON

#### Scenario: Notifications not granted
- **WHEN** the bundle's Notifications grant is denied or not yet determined
- **THEN** `diting-tianer notification-status` exits non-zero

#### Scenario: Older helper without the probe is detectable
- **WHEN** the Python side runs `diting-tianer --help` against a helper that predates this subcommand
- **THEN** `notification-status` is absent from the help text, and the caller treats the Notifications grant as unverifiable rather than denied

### Requirement: The helper SHALL expose read-only `location-status` and `bluetooth-authorization` probes

The helper SHALL accept `diting-tianer location-status` and `diting-tianer
bluetooth-authorization`, each an exit-code-only probe of the bundle's TCC
authorization that NEITHER prompts the user NOR powers the radio.
`location-status` SHALL determine the Location authorization via the
`CLLocationManager` authorization-change CALLBACK (which fires once the manager
registers with the location daemon), NOT a synchronous read of
`CLLocationManager.authorizationStatus` immediately after construction — that
premature read returns a spurious `.notDetermined` before registration completes
and would report an authorized bundle as not-determined. It SHALL exit `0` when
the status is `authorizedWhenInUse` / `authorizedAlways`, non-zero otherwise, and
SHALL NOT call `requestWhenInUseAuthorization` (assigning a delegate triggers the
callback without prompting). A bounded settle timeout SHALL fall back to reading
the property (registered by then). `bluetooth-authorization` SHALL read
`CBManager.authorization` (the class property, not a live central manager) and
exit `0` when it is `allowedAlways`, non-zero otherwise. Neither SHALL surface a
TCC prompt — they are read-only so a verification poll can run without stacking
prompts on the helper GUI's flow.

These SHALL appear in the helper's `--help` so the Python side can detect support
and degrade gracefully on an older helper. They print no JSON and SHALL NOT
change the `wifi-scan` or `associate` schema integers. The existing `scan` and
`bluetooth-status` subcommands — the FUNCTIONAL checks (unredacted scan;
`.poweredOn`) used by the TUI and BLE readiness — are unchanged.

#### Scenario: Location authorized is reported reliably (no registration-lag false negative)
- **WHEN** the bundle has Location granted and `diting-tianer location-status` runs as a fresh process
- **THEN** it exits 0 (via the authorization callback once registration completes), with no macOS prompt surfaced and no scan performed — it does NOT return notDetermined due to reading the property before the manager registered

#### Scenario: Bluetooth not yet authorized
- **WHEN** the bundle's Bluetooth grant is not determined and `diting-tianer bluetooth-authorization` runs
- **THEN** it exits non-zero, with no macOS Bluetooth prompt surfaced

#### Scenario: Older helper without the probes is detectable
- **WHEN** the Python side runs `diting-tianer --help` against a helper that predates these subcommands
- **THEN** `location-status` / `bluetooth-authorization` are absent from the help text, and the caller falls back to the functional probes

### Requirement: Launching the bundle with Cocoa flags SHALL launch the GUI, not error

The helper SHALL treat only its documented tokens as subcommands (`scan`,
`ble-scan`, `bluetooth-status`, `location-status`, `bluetooth-authorization`,
`notification-status`, `notify`, `associate`, `--help` / `-h`). When the bundle
is launched with a first argument that is NOT a known subcommand but IS a flag
(begins with `-`), the helper SHALL launch its GUI permission window rather than
treat it as an unknown subcommand. This is required because `diting setup` and
the installer open the bundle with `open … --args -AppleLanguages "(<tag>)"` (to
localise the macOS TCC prompts), which injects `-AppleLanguages` as the first
argument; the GUI is the only path that requests the Location / Bluetooth /
Notifications prompts, so it MUST launch on that path. A first argument that is
neither a known subcommand nor a flag (a genuine typo) SHALL still exit non-zero
with an "unknown subcommand" message.

#### Scenario: Opened with -AppleLanguages launches the prompt window
- **WHEN** the bundle is opened with `open --env DITING_LANG=en <bundle> --args -AppleLanguages "(en)"`
- **THEN** the helper launches its GUI and requests the macOS permission prompts (it does NOT exit on an "unknown subcommand")

#### Scenario: A real typo still errors
- **WHEN** the helper is run as `diting-tianer frobnicate`
- **THEN** it prints "unknown subcommand frobnicate" and exits non-zero

#### Scenario: Known subcommands are unaffected
- **WHEN** the helper is run as `diting-tianer location-status`
- **THEN** it runs the read-only Location probe and exits with its status code, with no GUI

