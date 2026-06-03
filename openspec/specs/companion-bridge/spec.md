# companion-bridge Specification

## Purpose
TBD - created by archiving change add-companion-bridge. Update Purpose after archive.
## Requirements
### Requirement: Companion forwarding is opt-in and off by default
diting SHALL NOT send any event off-device until the user has explicitly
paired a companion. With no pairing configured, the event sink SHALL be inert
and no network egress SHALL occur for companion purposes. Even when paired,
forwarding SHALL be suppressible for a single run without unpairing — via the
`DITING_COMPANION=0` environment variable OR the `--no-companion` flag — so the
user can self-test without spamming the paired phone; the self-test capture
harness SHALL force this suppression.

#### Scenario: Unpaired run sends nothing
- **WHEN** diting runs without companion pairing configured
- **THEN** no event is encrypted or transmitted and no relay request is made

#### Scenario: Explicit enable required
- **WHEN** the user has not completed pairing
- **THEN** the `--companion` surface reports "not paired" and offers to start pairing rather than silently activating

#### Scenario: Paired run muted for self-test
- **WHEN** diting runs while paired but with `--no-companion` (or `DITING_COMPANION=0`)
- **THEN** the sink is not built, no event is forwarded to the relay, and the on-disk pairing is left intact

### Requirement: Pairing generates a channel and renders a QR in the TUI
The pairing flow SHALL generate a fresh channel id and a fresh symmetric key,
render a scannable QR encoding the `companion-protocol` pairing payload in the
terminal, and persist the resulting pairing state. v1 SHALL support a single
paired device.

#### Scenario: Pairing produces a scannable code
- **WHEN** the user starts pairing
- **THEN** diting displays a QR encoding version, channel id, base64 key, and relay URL that a consumer can scan to attach

#### Scenario: Re-pairing replaces the prior device
- **WHEN** the user pairs a new device while one is already paired
- **THEN** a new channel id + key are generated and the prior pairing is superseded

### Requirement: Pairing state is persisted git-ignored with a public template
The pairing state (channel id, key, relay URL) SHALL be written to a local file
that is git-ignored, mirroring how `aps.yaml` is handled, and the repository
SHALL ship a public `*.example` template carrying no real secrets.

#### Scenario: Secret never enters version control
- **WHEN** pairing completes and the state file is written
- **THEN** the file path is covered by `.gitignore` and only the `*.example` template is tracked

### Requirement: The event sink taps the existing fan-out without altering it
The sink SHALL observe the same events the TUI already routes through
`events_ring.push` / `emit_*` / `_maybe_notify`, consuming the `event-log`
JSONL shape, and SHALL NOT change the existing event vocabulary, ordering, or
the behaviour of the EventRing, logger, or macOS notifier.

#### Scenario: Sink is additive
- **WHEN** companion forwarding is active
- **THEN** the TUI's on-screen events, the JSONL log, and macOS notifications behave exactly as they would without the sink

### Requirement: Push-worthiness reuses the watchdog gate
The sink SHALL decide which events are worth forwarding by first applying a
salience gate, then reusing the `_watchdog.py` severity thresholds and silence
window. The salience gate SHALL drop any event whose stamped `salience` tier is
below a configurable minimum (default `low`, so only `noise`-tier events such as
habitual arrivals and departures are suppressed); when an event carries no
`salience` field the gate is a no-op pass-through, so unpaired / pre-store push
behaviour is unchanged. After the salience gate, the existing rf_stir-confidence
threshold and the per-(type, target) silence window apply as before, so
low-signal, high-volume events (e.g. routine `ble_device_seen`) still coalesce.

#### Scenario: Habitual arrival is suppressed by salience
- **WHEN** a `ble_device_seen` stamped `salience` `noise` (a habitual device) is offered
- **THEN** it is not forwarded to the companion

#### Scenario: Missing salience does not suppress
- **WHEN** an otherwise push-worthy event carries no `salience` field
- **THEN** the salience gate passes it through to the existing watchdog gates unchanged

#### Scenario: Silenced category is suppressed
- **WHEN** an event arrives within the watchdog silence window for its category
- **THEN** it is coalesced or suppressed rather than producing a separate push

### Requirement: Forwarded events are sealed under the paired key
Before transmission, the sink SHALL serialise the event to its `event-log`
JSONL object and seal it with secretbox under the paired channel key, producing
a `companion-protocol` envelope with the next monotonic sequence number. The
plaintext SHALL never leave the process unencrypted. The sink SHALL strip
desktop-local-only fields — those not part of the `companion-protocol` event
vocabulary, currently `familiarity` and `salience` — from the payload before
sealing, so the wire stays within the validated protocol schema and a strict
consumer does not reject the event. (Carrying these across the wire is a
deferred, version-coordinated change.)

#### Scenario: Egress is always ciphertext
- **WHEN** a push-worthy event is forwarded
- **THEN** the bytes sent to the relay are a sealed envelope, never the JSONL plaintext

#### Scenario: Local-only fields do not cross the wire
- **WHEN** a seen event carrying `familiarity` and `salience` fields is forwarded
- **THEN** the sealed envelope's plaintext omits both, leaving only `companion-protocol` vocabulary fields so the mobile consumer accepts it

### Requirement: The relay client queues offline and flushes on reconnect
The sink SHALL post envelopes to the relay and, when the relay is unreachable
(Mac offline), SHALL enqueue them locally and flush in sequence order once
connectivity returns, preserving ordering and not losing events within the
queue's bounded capacity.

#### Scenario: Offline events flush in order
- **WHEN** the Mac loses connectivity, several push-worthy events occur, and connectivity later returns
- **THEN** the queued envelopes are delivered to the relay in ascending sequence order

#### Scenario: Bounded queue reports drops honestly
- **WHEN** the offline queue reaches capacity before reconnecting
- **THEN** the overflow is dropped with a recorded, user-visible indication rather than silently lost

### Requirement: The companion surface is explicit and discoverable
diting SHALL expose companion control via a `--companion` CLI surface and/or a
TUI toggle, reusing `--notify` semantics where sensible, and SHALL surface
current pairing and connectivity state (paired / not paired, relay reachable /
queued).

#### Scenario: Status is observable
- **WHEN** the user inspects the companion surface
- **THEN** it reports whether a device is paired and whether the relay is currently reachable or events are queued

#### Scenario: Pairing from inside the TUI
- **WHEN** the user presses the companion key in the running TUI
- **THEN** a modal renders the pairing QR (generating a pairing if none exists yet), and forwarding begins on the running app without a restart

