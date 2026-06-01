# companion-protocol Specification

## Purpose
TBD - created by archiving change add-companion-bridge. Update Purpose after archive.
## Requirements
### Requirement: Protocol is versioned and back-compatible
The protocol SHALL carry an explicit integer major version (`v1`) in the
pairing payload and in every relay request path. A peer SHALL tolerate an
envelope or pairing payload stamped with a version it recognises, and SHALL
refuse — with a clear, non-crashing error — a version it does not recognise.
A newer producer SHALL NOT change the meaning of an existing `v1` field;
additive fields only, mirroring the macOS-helper schema rule.

#### Scenario: Consumer receives a known version
- **WHEN** a consumer pulls an envelope stamped `v1` and the consumer supports `v1`
- **THEN** it decrypts and processes the envelope normally

#### Scenario: Consumer receives an unknown future version
- **WHEN** a consumer supporting only `v1` encounters a payload stamped `v2`
- **THEN** it abstains from processing that payload and surfaces a "newer protocol" notice without crashing or dropping its cursor

### Requirement: Event payload reuses the pinned JSONL schema
The plaintext inside an envelope SHALL be exactly one diting event object as
defined by the `events` / `event-log` JSONL line schema — English keys,
local-TZ ISO-8601 timestamps with offset, `None`-valued fields omitted, empty
tuples serialised as `[]`. This capability SHALL NOT introduce an alternate
event vocabulary, field renaming, or re-typing.

#### Scenario: Round-trip preserves the event object
- **WHEN** a producer seals a `ble_device_seen` event and a consumer opens it
- **THEN** the recovered object is byte-equivalent to the JSONL line the `event-log` writer would have produced for that event

#### Scenario: Unknown event type is preserved, not dropped
- **WHEN** a consumer opens an envelope whose event `type` it does not yet render
- **THEN** it retains the raw object (for the report file and forward compatibility) rather than discarding it

### Requirement: Envelope seals each event with authenticated encryption
Each relayed item SHALL be an envelope carrying: protocol version, channel id,
a monotonically increasing per-channel sequence number, a producer timestamp,
a nonce, and a ciphertext. The ciphertext SHALL be the event plaintext sealed
with libsodium secretbox (XSalsa20-Poly1305) under the channel's pre-shared
symmetric key. The relay and APNs SHALL never receive the plaintext or the key.

#### Scenario: Tampered ciphertext is rejected
- **WHEN** a consumer opens an envelope whose ciphertext or nonce has been altered in transit
- **THEN** secretbox authentication fails and the consumer discards that envelope without surfacing fabricated event data

#### Scenario: Wrong key cannot decrypt
- **WHEN** a relay operator or LAN peer obtains stored envelopes without the channel key
- **THEN** no plaintext event field (BSSID, SSID, device name, IP) is recoverable from the stored bytes

### Requirement: Cursor gives ordered, gap-evident, at-least-once delivery
Per channel, sequence numbers SHALL be strictly increasing with no producer
reuse. A consumer SHALL request items strictly after a cursor and SHALL be able
to detect a gap (missing sequence) so it can report incomplete history rather
than silently presenting a partial timeline.

#### Scenario: Incremental pull returns only new items
- **WHEN** a consumer holding cursor N requests items since N
- **THEN** the relay returns items with sequence > N in ascending order

#### Scenario: Gap is observable
- **WHEN** a consumer receives sequences [5, 7] after holding cursor 4
- **THEN** it can detect that sequence 6 is missing and mark the timeline as having a gap

### Requirement: Pairing payload is self-contained and transferred out-of-band
The pairing QR payload SHALL contain everything a consumer needs to attach to a
channel: protocol version, channel id, the base64 symmetric key, and the relay
base URL. It MAY contain a relay TLS fingerprint for pinning. The symmetric key
SHALL travel only inside this payload and SHALL NOT be transmitted to the relay
or any server.

#### Scenario: Fresh pairing attaches a consumer
- **WHEN** a consumer scans a well-formed pairing payload
- **THEN** it can immediately authenticate to the channel and decrypt that channel's envelopes

#### Scenario: Malformed pairing payload is refused
- **WHEN** a consumer scans a payload missing the key or relay URL
- **THEN** it reports an invalid-pairing error and stores nothing

### Requirement: Relay exposes a blind store-and-forward HTTP API
The relay SHALL accept `POST /v1/channel/{id}` carrying a ciphertext envelope
and SHALL serve `GET /v1/channel/{id}?since={cursor}` returning that channel's
envelopes in ascending sequence order after the cursor. Stored items SHALL
expire after a bounded TTL. Requests SHALL be authenticated per channel. The
relay SHALL store and return ciphertext + routing metadata only and SHALL be
incapable of reading event plaintext.

#### Scenario: Store then forward
- **WHEN** a producer POSTs an envelope and a consumer later GETs since an earlier cursor
- **THEN** the consumer receives that envelope in sequence order

#### Scenario: Expired items drop out
- **WHEN** an envelope older than the configured TTL is requested
- **THEN** the relay no longer returns it, and the consumer treats it as an unrecoverable gap rather than an error

#### Scenario: Unauthorized channel access is refused
- **WHEN** a request omits or presents wrong channel credentials
- **THEN** the relay returns an auth error and reveals no stored bytes

### Requirement: Machine-readable contract artifacts are canonical here
This repository SHALL hold the authoritative JSON Schema for the envelope and
for each event type, plus a set of golden fixture lines exercising every event
type and edge case (omitted `None`, empty `[]`, CJK strings). Downstream
consumers SHALL vendor these artifacts and run a conformance test against them;
the artifacts SHALL carry a version/hash so a vendored copy that drifts is
detectable.

#### Scenario: Conformance fixtures cover every event type
- **WHEN** the fixture set is validated
- **THEN** it contains at least one golden line per event type defined in `events`, and each validates against its JSON Schema

#### Scenario: Drift is detectable
- **WHEN** a consumer's vendored copy of the artifacts differs from the canonical version/hash
- **THEN** the consumer's drift check fails rather than silently running against a stale contract

### Requirement: APNs trigger carries the channel id plus an optional cleartext event summary
The APNs payload SHALL carry the channel id and MAY carry a coarse category and
a short, single-line, human-readable event summary in cleartext (e.g. "BLE
nearby: Magic Keyboard", "Roamed to AX51-E"). The summary is a low-sensitivity
convenience composed by the producer so the notification is useful at a glance;
the relay and APNs necessarily see it, which the user accepts by pairing. The
summary SHALL NOT carry the symmetric key or anything beyond the same event
fields the paired app already displays. The full, structured event SHALL
continue to travel only inside the E2E-encrypted envelope, which the relay and
APNs never read. A producer MAY omit the summary, in which case the push falls
back to a coarse "new {category} activity" trigger.

#### Scenario: Push names the event detail
- **WHEN** a producer triggers a push for a newly-seen BLE device named "Magic Keyboard"
- **THEN** the APNs alert body reads a one-line summary such as "BLE nearby: Magic Keyboard", composed by the producer and forwarded verbatim by the relay

#### Scenario: Summary is cleartext but the full event stays sealed
- **WHEN** the relay receives a POST whose body carries the sealed envelope plus a cleartext `push` summary sibling
- **THEN** the relay uses the summary for the APNs alert, strips it, and stores and later returns only the encrypted envelope — the summary is never persisted

#### Scenario: Summary is optional and back-compatible
- **WHEN** a producer POSTs a plain envelope with no `push` sibling
- **THEN** the relay accepts it and rings a coarse "new {category} activity" doorbell, as before

