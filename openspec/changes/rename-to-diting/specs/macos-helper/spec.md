## MODIFIED Requirements

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
The helper SHALL respond to `wifi-scan`, `ble-scan`, `bluetooth-status`
subcommands. Python invokes the helper as a subprocess and reads JSON
or JSONL from stdout; no shared memory, no socket, no file drop.
Process termination is the unambiguous "scan finished" signal.

#### Scenario: Wi-Fi scan
- **WHEN** Python runs `diting-tianer wifi-scan`
- **THEN** the helper performs one CoreWLAN scan, prints one JSON object to stdout (schema-versioned), and exits with code 0

#### Scenario: BLE long-running scan
- **WHEN** Python runs `diting-tianer ble-scan`
- **THEN** the helper streams JSONL advertisement events to stdout indefinitely until Python sends SIGTERM

#### Scenario: Bluetooth permission probe
- **WHEN** Python runs `diting-tianer bluetooth-status`
- **THEN** the helper exits 0 if granted, 3 if denied/unauthorized

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

### Requirement: The helper SHALL be auto-detectable from the Python side without configuration
The Python `_helper.find_helper()` SHALL locate the helper bundle
under `helper/diting-tianer.app/Contents/MacOS/diting-tianer`
relative to the diting source root (editable install) or the
installed package path (pip install). The user SHALL NOT need to set
`PATH` or env vars for the helper to be found.

#### Scenario: Editable install
- **WHEN** diting is installed via `uv pip install -e .`
- **THEN** `find_helper()` returns the path to the in-tree helper bundle

#### Scenario: Pip install without source
- **WHEN** diting is installed via `pip install diting` and the helper bundle is not present
- **THEN** `find_helper()` returns `None`, and the BLE / Wi-Fi paths fall back to direct CoreWLAN (which produces redacted scan results until the user runs `diting-build-helper`)
