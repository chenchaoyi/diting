## ADDED Requirements

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
