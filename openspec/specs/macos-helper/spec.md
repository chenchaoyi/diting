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

