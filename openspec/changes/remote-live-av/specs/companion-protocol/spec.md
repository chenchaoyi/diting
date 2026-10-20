## ADDED Requirements

### Requirement: A `signal` sealed message class SHALL carry WebRTC signalling
The protocol SHALL define `signal` as a sealed message class (protocol v4) that
rides the existing envelope and the same authenticated-encryption seal as
`command`/`media`, but is NOT an event: it never enters the event vocabulary, the
event logger, or the durable report. A `signal` plaintext SHALL carry a `kind`
(`offer` / `answer` / `ice`) plus the SDP (`sdp`) for offer/answer or the ICE
candidate (`candidate`) for `ice`, and SHALL be stamped at protocol version 4.
The supported-version set SHALL include 4, and the relay SHALL accept it. The
media itself is NOT part of the protocol — only the signalling is.

#### Scenario: Signal seals like a command
- **WHEN** a `signal` plaintext is sealed under the channel key
- **THEN** it uses the same envelope + authenticated-encryption seal as `command`/`media`, stamped at version 4, and fails closed on a wrong key or tampered ciphertext

#### Scenario: Signal is not an event
- **WHEN** a `signal` message is sealed, sent, and opened
- **THEN** it never appears in the event log, the durable report, or the events timeline

### Requirement: The relay SHALL expose bidirectional ephemeral signalling routes
The relay SHALL expose two ephemeral, delete-on-delivery signalling queues —
phone→desktop and desktop→phone — mirroring the `command`/`media` shape (short
TTL, low cap, ciphertext-only, per-channel authenticated). Because signalling is
bidirectional, both directions SHALL have their own route, and the relay SHALL
remain blind (it stores and forwards ciphertext only and cannot read SDP or ICE).

#### Scenario: Offer and answer route in opposite directions
- **WHEN** the desktop posts an offer to the desktop→phone route and the phone posts an answer to the phone→desktop route
- **THEN** each peer drains only its inbound route, and delivered items are deleted

#### Scenario: Relay can't read signalling
- **WHEN** a sealed signalling message transits the relay
- **THEN** the relay stores and forwards ciphertext only and cannot recover the SDP or ICE
