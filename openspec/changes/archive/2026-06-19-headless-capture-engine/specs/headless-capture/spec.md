## ADDED Requirements

### Requirement: A headless capture engine SHALL assemble the full sensor set below the UI

diting SHALL provide a headless `CaptureEngine` that assembles and drives the
project's sensors — Wi-Fi, latency, RF/environment, BLE, LAN, and mDNS/Bonjour —
without any Textual / widget coupling, emitting through a single `EventLogger`.
The engine SHALL accept a selected sensor set and construct only those pollers,
running each as an independent async consumer that drains the poller's
transition events and routes them to the matching `EventLogger.emit_*` method.

The engine is the headless capture path's single assembly point; the TUI MAY
retain its own poller wiring (convergence is not required by this capability).

#### Scenario: Engine drives the requested sensors
- **WHEN** the engine is constructed with sensors `wifi`, `rf`, `ble`
- **THEN** it constructs the Wi-Fi, environment, and BLE pollers (and not the LAN or mDNS pollers) and runs a consumer for each

#### Scenario: No UI coupling
- **WHEN** the engine runs in a process with no Textual app
- **THEN** it emits events purely through the `EventLogger` and never references a widget, panel, or event ring

### Requirement: Headless capture SHALL emit the same canonical JSONL schema as the TUI

The events the engine emits SHALL be byte-compatible with the canonical
event-log schema written by the TUI's `--log` path and consumable by `analyze`
without the reader being able to tell which path produced them. When BLE / LAN /
mDNS sensors are active the engine SHALL emit their device-discovery events —
BLE device seen/left, LAN host seen/left/dhcp-rotation, Bonjour service
seen/left — and SHALL emit `network_change` on a gateway shift, using the same
`emit_*` methods and event types the TUI uses.

#### Scenario: A capture round-trips through analyze
- **WHEN** a headless capture writes JSONL to a file and that file is passed to `diting analyze`
- **THEN** analyze parses every line and produces a report, identically to a TUI `--log` capture of the same events

#### Scenario: Device-discovery events are emitted headless
- **WHEN** a BLE device graduates the presence gate during a headless capture with the `ble` sensor active
- **THEN** a `ble_device_seen` line is written to the stream, identical in shape to the TUI-emitted line

### Requirement: `session_meta.monitors` SHALL report the sensors actually wired

The engine SHALL build the `session_meta` `monitors` manifest from the resolved
sensor set, so each monitor's `active` flag and its parameters (Wi-Fi scan
interval, BLE presence gate, latency targets) reflect what the engine actually
started. A sensor that was requested but could not start SHALL be reported
inactive. The manifest SHALL NOT hard-code a sensor as active or inactive
independent of what ran.

#### Scenario: Manifest reflects the active set
- **WHEN** a headless capture runs with sensors `wifi,latency,rf,ble`
- **THEN** the `session_meta.monitors` manifest reports `ble` active (with its presence gate) and `lan` inactive

#### Scenario: Requested-but-unavailable sensor is inactive
- **WHEN** the `ble` sensor is requested but no helper with a BLE-scan subcommand is available
- **THEN** the `session_meta.monitors` manifest reports `ble` inactive

### Requirement: Each sensor SHALL degrade gracefully without taking down the others

The engine SHALL skip a sensor that cannot start — missing helper, denied
permission, or scene-gated LAN probing off — emitting a one-line stderr note
while the remaining sensors keep running, and the stdout JSONL stream SHALL NOT
be interrupted by the failure. A poller that raises at runtime SHALL end its own
consumer without cancelling the others. LAN active-probing SHALL honour the same
scene / `DITING_LAN_PROBE` gate the TUI honours; with probing off, passive LAN
discovery still runs.

#### Scenario: BLE unavailable, the rest keep streaming
- **WHEN** a capture requests `wifi,ble` but the BLE helper is missing
- **THEN** a one-line note goes to stderr, `ble` is marked inactive in the manifest, and Wi-Fi events continue on stdout

#### Scenario: A runtime poller error is isolated
- **WHEN** one sensor's poller raises mid-capture
- **THEN** its consumer ends, the other sensors keep emitting, and stdout JSONL stays valid

### Requirement: The engine SHALL construct the Bonjour poller before LAN and share it

Because LAN host enrichment reads the Bonjour poller's state, the engine SHALL
construct the Bonjour/mDNS poller before the LAN poller and pass the same
instance into the LAN poller whenever both are active, so LAN keeps its
Bonjour-name enrichment. Latency SHALL be late-bound on the first known gateway
and rebuilt on a gateway change.

#### Scenario: LAN keeps Bonjour enrichment
- **WHEN** a capture runs with both `lan` and `mdns` active
- **THEN** the LAN poller receives the same Bonjour poller instance the engine drives, and LAN hosts can carry Bonjour-derived names

### Requirement: The engine SHALL tear down cleanly and bounded

On cancellation or completion the engine SHALL cancel and await its consumer
tasks, stop the Bonjour and LAN pollers, flush the companion sink and
familiarity store, and close the `EventLogger` — leaving no orphaned task or
unflushed buffer. A `--duration`-bounded capture SHALL exit on its own after the
window.

#### Scenario: Bounded capture exits and flushes
- **WHEN** a `--duration 10s` headless capture reaches its window
- **THEN** the engine cancels its consumers, stops the pollers, flushes the familiarity store, closes the logger, and the process exits 0

#### Scenario: No orphaned tasks after teardown
- **WHEN** the engine finishes a run
- **THEN** no consumer task or child poller task remains running
