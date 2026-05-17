## ADDED Requirements

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

If any permission resolves to denied or restricted, the helper SHALL continue to the next permission rather than aborting the flow, and the status line for the denied permission SHALL include a "open System Settings → Privacy & Security → ..." hint.

#### Scenario: User clicks Allow on all three
- **WHEN** the user runs install.sh and clicks Allow on Location, then Allow on Bluetooth, then Allow on Notifications
- **THEN** macOS shows exactly one prompt at a time, never two simultaneously
- **AND** the status window shows `1/3 Location · granted`, `2/3 Bluetooth · granted`, `3/3 Notifications · granted` as each lands
- **AND** the window auto-closes ~4 seconds after the third grant

#### Scenario: User denies a permission mid-flow
- **WHEN** the user clicks Don't Allow on Bluetooth
- **THEN** the status window shows `2/3 Bluetooth · denied` with a Settings hint
- **AND** the helper still requests Notifications next (does not abort the flow)
- **AND** the window auto-closes after the Notifications outcome resolves

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

## MODIFIED Requirements

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
