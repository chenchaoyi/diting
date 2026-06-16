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
queue's bounded capacity. A single flush SHALL send at most a bounded batch of
envelopes so the per-call blocking time is bounded by the batch size rather than
the backlog depth; the periodic flush driver SHALL keep draining successive
batches while events remain queued, so a large backlog drains incrementally
across cycles rather than in one all-or-nothing burst. Bounding the batch SHALL
NOT change ordering, the bounded-queue drop-oldest behavior, or the
sustained-failure (`relay unreachable`) accounting.

#### Scenario: Offline events flush in order
- **WHEN** the Mac loses connectivity, several push-worthy events occur, and connectivity later returns
- **THEN** the queued envelopes are delivered to the relay in ascending sequence order

#### Scenario: Bounded queue reports drops honestly
- **WHEN** the offline queue reaches capacity before reconnecting
- **THEN** the overflow is dropped with a recorded, user-visible indication rather than silently lost

#### Scenario: A single flush is bounded by the batch size
- **WHEN** more envelopes are queued than the configured flush batch and one flush runs with that batch limit
- **THEN** it sends at most the batch's worth of envelopes, in ascending sequence order, and leaves the remainder queued for the next flush

#### Scenario: A large backlog drains across successive periodic flushes
- **WHEN** a backlog larger than one batch is queued and the relay is reachable
- **THEN** repeated periodic flushes drain the backlog to empty across multiple cycles, each cycle sending at most one batch, with no events lost or reordered

### Requirement: The companion surface is explicit and discoverable
diting SHALL expose companion control via a `--companion` CLI surface and/or a
TUI toggle, reusing `--notify` semantics where sensible, and SHALL surface
current pairing and connectivity state (paired / not paired, relay reachable /
queued).

The TUI subtitle chip SHALL distinguish a transiently-queued backlog from a
sustained delivery failure: when several consecutive flush attempts deliver
nothing (threshold: 3 — about 9 s at the periodic flush interval), the queued
chip SHALL carry a `relay unreachable` annotation. The first successful send
SHALL clear the annotation. A flush against an empty queue SHALL NOT count
toward the threshold either way.

#### Scenario: Status is observable
- **WHEN** the user inspects the companion surface
- **THEN** it reports whether a device is paired and whether the relay is currently reachable or events are queued

#### Scenario: Pairing from inside the TUI
- **WHEN** the user presses the companion key in the running TUI
- **THEN** a modal renders the pairing QR (generating a pairing if none exists yet), and forwarding begins on the running app without a restart

#### Scenario: Sustained flush failure names itself
- **WHEN** events are queued and 3 consecutive flush attempts deliver nothing
- **THEN** the subtitle chip renders the queued count with a `relay unreachable` annotation

#### Scenario: A transient blip does not flash the warning
- **WHEN** a single flush attempt fails and the next one delivers
- **THEN** the chip shows the plain queued count throughout, and never the unreachable annotation

#### Scenario: Recovery clears the annotation
- **WHEN** the unreachable annotation is showing and a flush then delivers at least one envelope
- **THEN** the annotation is dropped on the next chip render

### Requirement: Insight + threat events SHALL be forwarded, salience-gated
The companion sink SHALL forward `insight` events (including the `critical`
threat tier) rather than treating them as desktop-local. Forwarding SHALL ride
the existing salience gate: with the default minimum (`low`), `info`-severity
insights (salience `low`) are dropped while `note` / `warn` / `critical`
(salience `notable` / `high`) forward. The per-(type, target) silence window
SHALL key an insight on its `code`, so distinct insight codes debounce
independently. The existing local-only field strip (`familiarity`, `salience`)
SHALL still apply to insight payloads before sealing.

#### Scenario: A threat is forwarded
- **WHEN** a `critical` `insight` (e.g. `evil_twin`) is offered to the sink while paired
- **THEN** it is sealed and enqueued (its salience `high` clears the gate)

#### Scenario: An info insight is not forwarded
- **WHEN** an `info` `insight` (salience `low`) is offered and the minimum salience is the default
- **THEN** the sink does not forward it

#### Scenario: Distinct insight codes are not coalesced together
- **WHEN** two insights with different `code`s are offered within one silence window
- **THEN** both forward (the window is keyed per code)

### Requirement: The local-only strip SHALL include the security cipher
The sink's local-only field strip SHALL include `security` (alongside
`familiarity` and `salience`), so the connection cipher stamped on associated
`link_state` events never crosses the companion wire while remaining available
to the desktop threat engine and the JSONL log.

#### Scenario: security is stripped before sealing
- **WHEN** an associated `link_state` carrying a `security` field is forwarded
- **THEN** the sealed envelope's plaintext omits `security`, leaving only `companion-protocol` `link_state` vocabulary fields

### Requirement: The relay SHALL expose a count-only channel presence endpoint
The relay SHALL track, per channel, the set of distinct recently-active
pullers and expose the count via `GET /v1/channel/{id}/presence`,
authenticated with the same channel bearer token as the other channel
endpoints. The authenticated phone pull (`GET /v1/channel/{id}`) — the
existing heartbeat — SHALL upsert a presence entry keyed by an opaque,
per-channel, non-reversible hash of the connection (never a stored
device identity), with a fixed TTL of at least twice the mobile pull
cadence. The presence endpoint SHALL return `{active, ttl_s, as_of}` —
the count of pullers seen within the TTL window, the window width, and
a timestamp — and nothing identifying. It SHALL be read-only (it SHALL
NOT itself register a puller, so a desktop polling it never inflates the
count), idempotent, and SHALL reject a bad/absent token exactly as the
other channel reads do.

#### Scenario: A pull registers presence
- **WHEN** a phone performs an authenticated `GET /v1/channel/{id}` and the desktop then `GET /v1/channel/{id}/presence`
- **THEN** the presence response reports `active` ≥ 1 with `ttl_s` and `as_of`, and no device identity

#### Scenario: Presence decays after the TTL
- **WHEN** no pull occurs within the TTL window
- **THEN** the presence count returns to 0

#### Scenario: Repeat pulls from one puller do not inflate the count
- **WHEN** the same puller pulls several times within the window
- **THEN** it counts once, not once per pull

#### Scenario: Polling presence does not register a puller
- **WHEN** only `GET /v1/channel/{id}/presence` is called (no `/pull`)
- **THEN** `active` stays 0 — the presence read never counts itself

#### Scenario: Presence requires the channel token
- **WHEN** `GET /v1/channel/{id}/presence` is called with a wrong or absent bearer token
- **THEN** the relay responds 403 / 401 as the other channel reads do, with no count

### Requirement: The pairing screen SHALL show a connected-count line
The desktop pairing screen SHALL poll the relay presence endpoint while
open and render one connected-count line under the QR, above the key
hints, in the mono face used for diting data. Zero SHALL be a plainly
shown state, never hidden; an error or timeout SHALL show an explicit
"can't confirm" state rather than a stale or fabricated number. The
states (connected count / zero / error) SHALL carry distinguishing
colour and SHALL be available in both English and Chinese. The relative
age of the count SHALL track the endpoint's `as_of`.

#### Scenario: Phones connected
- **WHEN** the presence endpoint reports `active` ≥ 1 while the pairing screen is open
- **THEN** the screen shows a connected-count line (e.g. `N devices connected` / `N 台设备已连接`) with its relative age

#### Scenario: No phones connected
- **WHEN** the presence endpoint reports `active` = 0
- **THEN** the screen shows an explicit zero state (`No devices connected` / `暂无设备连接`), not a hidden or blank line

#### Scenario: Presence unavailable
- **WHEN** the presence poll errors or times out
- **THEN** the screen shows a "can't confirm" state (`Can't confirm connections` / `无法确认连接数`), never a stale or guessed number

