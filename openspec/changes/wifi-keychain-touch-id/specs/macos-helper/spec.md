## MODIFIED Requirements

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

## ADDED Requirements

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
