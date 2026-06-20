## ADDED Requirements

### Requirement: `diting setup` SHALL drive and verify the helper's TCC grants

`diting setup` SHALL locate (or build) the Swift helper, open its `.app` bundle
so macOS surfaces the Location → Bluetooth → Notifications prompts, and then
verify the outcome by probing each grant. It SHALL block-and-verify the two
grants required for core function — Location (Wi-Fi scan list) and Bluetooth
(BLE view) — polling until both are granted or a bounded timeout elapses, and
SHALL drive the Notifications prompt as best-effort (never blocking on it).
`setup` SHALL print live per-permission status as each grant lands. It SHALL NOT
claim to grant permissions itself — macOS requires the user's Allow click; setup
only drives the prompts and verifies.

#### Scenario: All required grants land
- **WHEN** the user runs `diting setup` and clicks Allow on Location and Bluetooth
- **THEN** setup reports both granted and exits 0

#### Scenario: A required grant never lands before timeout
- **WHEN** the user runs `diting setup` and never grants Bluetooth within the timeout
- **THEN** setup reports Bluetooth still missing, prints what to do, and exits non-zero

### Requirement: `setup` SHALL recover a previously-denied grant by opening System Settings

`setup` SHALL treat a required grant that is still missing after the bundle was
opened and a short grace window elapsed — the signature of a settled denial,
which macOS will not re-prompt — as denied, and SHALL open System Settings to
the exact Privacy pane for that permission (Location Services / Bluetooth /
Notifications) and print step-by-step instructions to enable it. If opening the
pane fails, the instructions SHALL still print.

#### Scenario: Denied Location is routed to Settings
- **WHEN** the user previously clicked Don't Allow on Location and runs `diting setup`
- **THEN** setup opens System Settings to the Location Services privacy pane and prints how to enable diting's helper

### Requirement: `setup` SHALL be non-blocking when non-interactive

`setup` SHALL treat the run as non-interactive when stdout is not a TTY, or
`--json` is given, or `DITING_SETUP_NONINTERACTIVE` is set. In that mode it SHALL
probe the current grant state ONCE, SHALL NOT open the bundle or block, and SHALL
report the per-permission state plus what the user must do. This keeps CI /
piped installs and agent invocations fast.

#### Scenario: Non-TTY run does not block
- **WHEN** `diting setup` runs with stdout piped to a file
- **THEN** it probes once, prints the current per-permission state, and exits without opening the bundle or waiting

#### Scenario: `--json` run does not block
- **WHEN** an agent runs `diting setup --json`
- **THEN** stdout is one JSON object with the per-permission state and the process does not block

### Requirement: `setup --json` SHALL emit a machine-readable permission state

With `--json`, `setup` SHALL print exactly one JSON object to stdout carrying a
per-permission state for `location`, `bluetooth`, and `notifications` (each at
least a boolean-or-unknown granted flag), and an overall readiness flag. stdout
SHALL carry only the JSON; prose / instructions SHALL go to stderr; keys SHALL be
locale-stable English. When the running helper cannot verify Notifications (an
older helper without the probe), the `notifications` state SHALL be reported as
unknown rather than a false negative.

#### Scenario: JSON state is parseable
- **WHEN** an agent runs `diting setup --json`
- **THEN** stdout is one JSON object with `location`, `bluetooth`, `notifications`, and an overall readiness flag, and `jq .` parses it cleanly

#### Scenario: Notifications unverifiable on an old helper
- **WHEN** `diting setup --json` runs against a helper without the notification-status probe
- **THEN** the `notifications` state is reported as unknown, not denied

### Requirement: `setup` SHALL handle a missing or unusable helper gracefully

`setup` SHALL print a clear, actionable message and exit non-zero — never a
crash or traceback — when no helper can be located or built, or the helper is
not inside an `.app` bundle (so the macOS prompts cannot be triggered). The
message SHALL name the problem and how to fix it.

#### Scenario: No helper present
- **WHEN** `diting setup` runs on a host where the helper bundle is absent and cannot be built
- **THEN** setup prints how to install / build the helper and exits non-zero without a traceback
