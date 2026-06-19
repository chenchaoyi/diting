## MODIFIED Requirements

### Requirement: `scan` SHALL print a one-shot sensor snapshot

`scan` SHALL collect a single snapshot from the selected sensors and exit. Flags
`--wifi`, `--ble`, `--lan`, and `--mdns` select sensors; with none, `--wifi` and
`--ble` run (the always-available pair). `--duration D` bounds the collection
window for the streaming sensors (BLE / LAN / mDNS; default a few seconds). With
`--json`, stdout SHALL be one JSON object keyed by sensor (`wifi`, `ble`, `lan`,
`mdns` — only the requested keys present), each value a list of results; without
`--json`, a human table per sensor. Wi-Fi results come from the helper scan; BLE
results are decoded via the registered decoders; LAN and mDNS results are the
latest snapshot from a brief poller sweep. A sensor that is unavailable (e.g.
helper missing, permission denied, no network) SHALL surface a structured error
for that sensor without aborting the others. Exit follows the convention: `0` if
any selected sensor returned data, `1` if none did, `2` on usage error.

#### Scenario: Combined Wi-Fi + BLE snapshot
- **WHEN** the user runs `diting scan --json`
- **THEN** stdout is one JSON object with a `wifi` array and a `ble` array; exit 0

#### Scenario: Single sensor
- **WHEN** the user runs `diting scan --wifi --json`
- **THEN** stdout carries only the `wifi` array

#### Scenario: LAN snapshot
- **WHEN** the user runs `diting scan --lan --json`
- **THEN** stdout is one JSON object whose `lan` value is a list of discovered hosts (or a structured `{"error",...}` when LAN discovery cannot run)

#### Scenario: mDNS snapshot
- **WHEN** the user runs `diting scan --mdns --json`
- **THEN** stdout is one JSON object whose `mdns` value is a list of discovered Bonjour services

#### Scenario: One sensor unavailable
- **WHEN** the user runs `diting scan --json` with Bluetooth permission denied
- **THEN** the `wifi` array is present and the `ble` value is a structured `{"error",...}`; exit follows the convention (0 if any sensor succeeded)

### Requirement: `stream` SHALL emit canonical JSONL on stdout with no other output

`stream` (subsuming the headless role of `monitor`) SHALL produce ONLY the
canonical event-log JSONL stream on stdout — the same schema `analyze` consumes —
with no banner, progress, or decorative text. All status / error messages SHALL
go to stderr. `--duration D` SHALL bound the run; when omitted, the stream runs
until Ctrl+C or SIGTERM. SIGTERM SHALL flush the final event and exit cleanly.

`stream` SHALL accept `--sensors a,b,…` to select which sensors the underlying
capture engine drives, from `wifi`, `latency`, `rf`, `ble`, `lan`, `mdns`, plus
`all` (every available sensor). The default SHALL be `wifi,latency,rf` — the
historical headless set — so an unflagged `stream` is behaviourally unchanged and
never starts BLE scanning or LAN active-probing unasked. An unknown sensor token
SHALL be a usage error (exit 2) naming the bad token. When `ble`, `lan`, or
`mdns` are selected, `stream` SHALL emit their canonical device-discovery events
(BLE seen/left, LAN host seen/left/dhcp-rotation, Bonjour service seen/left) on
the same stdout JSONL stream, and the `session_meta.monitors` manifest SHALL
report the sensors actually wired (not a hard-coded subset).

#### Scenario: Pipe to jq
- **WHEN** the user runs `diting stream | jq 'select(.type=="roam")'`
- **THEN** jq receives only valid JSON lines; nothing breaks the pipeline

#### Scenario: Bounded run
- **WHEN** the user runs `diting stream --duration 10s`
- **THEN** the stream emits canonical JSONL for ~10 s, flushes, and exits 0

#### Scenario: Default sensor set is unchanged
- **WHEN** the user runs `diting stream` with no `--sensors`
- **THEN** the engine drives only Wi-Fi + latency + RF stir, and `session_meta.monitors` reports `ble` and `lan` inactive

#### Scenario: Full sensor set
- **WHEN** the user runs `diting stream --sensors all --duration 30s`
- **THEN** the stream additionally emits BLE / LAN / Bonjour device-discovery events as they occur, and `session_meta.monitors` reports the active sensors

#### Scenario: Unknown sensor token
- **WHEN** the user runs `diting stream --sensors wifi,sonar`
- **THEN** stderr names the unknown `sonar` token and the process exits 2

#### Scenario: Pipe to head closes cleanly
- **WHEN** the user runs `diting stream | head -n 10`
- **THEN** the stream exits cleanly via SIGPIPE after head closes; no zombie process
