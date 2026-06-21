# permission-setup Specification

## Purpose
TBD - created by archiving change installer-permission-setup. Update Purpose after archive.
## Requirements
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

`setup` SHALL verify each grant using READ-ONLY status probes (which neither
prompt the user nor power the radio), so that the ONLY source of TCC prompts is
the opened helper bundle's GUI — which requests the three grants one at a time,
waiting for the user's decision on each. `setup`'s verification poll SHALL NOT
itself trigger a TCC prompt; the user SHALL never see duplicate or stacked
prompts, regardless of how long they take to respond. When the running helper
predates the read-only probes, `setup` MAY fall back to the functional probes
(preserving function on an older helper).

#### Scenario: All required grants land
- **WHEN** the user runs `diting setup` and clicks Allow on Location and Bluetooth
- **THEN** setup reports both granted and exits 0

#### Scenario: A required grant never lands before timeout
- **WHEN** the user runs `diting setup` and never grants Bluetooth within the timeout
- **THEN** setup reports Bluetooth still missing, prints what to do, and exits non-zero

#### Scenario: Slow user sees no stacked prompts
- **WHEN** the user runs `diting setup` and reads each macOS prompt slowly before clicking Allow
- **THEN** only the helper GUI's prompts appear, one at a time; setup's verification poll never adds a second Location or Bluetooth prompt on top

### Requirement: `setup` SHALL recover a previously-denied grant by opening System Settings

`setup` SHALL distinguish a grant that is merely PENDING (not yet answered —
macOS `notDetermined`) from one that is SETTLED-denied (`denied` / `restricted`,
which macOS will not re-prompt), using the read-only probes' distinct exit codes.
While a required grant is pending, `setup` SHALL keep waiting for the helper's
prompt — it SHALL NOT call it denied and SHALL NOT open System Settings. Only
when a required grant reads as settled-denied SHALL `setup` open System Settings
to the exact Privacy pane for that permission (Location Services / Bluetooth /
Notifications) and print step-by-step instructions to enable it, then keep
polling so that enabling it is detected. If opening the pane fails, the
instructions SHALL still print. `setup` SHALL NOT use a fixed grace window to
assume a still-pending grant is denied.

#### Scenario: Settled-denied Location is routed to Settings
- **WHEN** the user previously clicked Don't Allow on Location and runs `diting setup`
- **THEN** setup detects the settled denial, opens System Settings to the Location Services privacy pane, and prints how to enable diting's helper

#### Scenario: A pending grant is not mislabeled as denied
- **WHEN** the helper's grant is `notDetermined` (e.g. a fresh install / new cdhash) and the prompt has not yet been answered
- **THEN** setup keeps waiting for the prompt and does NOT announce a denial or open System Settings

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

