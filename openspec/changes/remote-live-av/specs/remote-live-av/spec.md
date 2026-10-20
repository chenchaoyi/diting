## ADDED Requirements

### Requirement: Live A/V SHALL be a distinct, off-by-default opt-in from the snapshot tier
Live audio+video SHALL be disabled by default and SHALL be a separate opt-in from
the snapshot camera. Enabling it SHALL require an explicit operator action that
proves BOTH the camera and the microphone macOS grants in the foreground, and
SHALL enable only if both resolve to authorized. The snapshot tier SHALL remain
available and unaffected whether or not live A/V is enabled.

#### Scenario: Enabling surfaces both grants
- **WHEN** the operator enables live A/V for the first time
- **THEN** the macOS camera prompt and the microphone prompt are surfaced in the foreground, and live A/V is enabled only if both are granted

#### Scenario: Denied microphone leaves live A/V off
- **WHEN** the operator grants the camera but denies the microphone
- **THEN** live A/V stays disabled and reports the denial; the snapshot tier still works

#### Scenario: Snapshot unaffected
- **WHEN** live A/V is disabled
- **THEN** the snapshot camera session behaves exactly as before

### Requirement: A live session SHALL stream camera and microphone in real time, end-to-end encrypted
On an operator-initiated live session, the Mac and phone SHALL establish a WebRTC
peer connection and stream the Mac's camera and microphone to the phone in real
time. The media SHALL be end-to-end encrypted (DTLS-SRTP) and SHALL travel
peer-to-peer or via the TURN relay — it SHALL NOT transit the companion relay,
which carries only the sealed signalling. Signalling (SDP offer/answer + ICE)
SHALL be sealed under the channel key.

#### Scenario: Live session connects and streams A/V
- **WHEN** the operator starts a live session and both peers exchange the sealed offer/answer + ICE
- **THEN** a WebRTC connection is established and the phone renders the live video and plays the live audio

#### Scenario: Media never touches the companion relay
- **WHEN** a live session is streaming
- **THEN** audio/video frames flow only over the WebRTC transport (P2P or TURN); the companion relay only ever carried the sealed signalling

#### Scenario: Signalling is sealed
- **WHEN** an SDP or ICE message crosses the relay
- **THEN** it is sealed under the channel key and the relay stores only ciphertext

### Requirement: NAT traversal SHALL use STUN plus a TURN relay whose credentials are short-lived
The session SHALL attempt a direct peer-to-peer path via STUN and SHALL fall back
to a TURN relay for networks where direct fails. The TURN shared secret SHALL NOT
be sent to the phone; the desktop SHALL mint short-lived TURN credentials from the
secret and deliver the ICE-server configuration (STUN + TURN with the minted
credentials) to the phone inside the sealed signalling. When no TURN is
configured, live A/V SHALL be unavailable and SHALL say so, and the snapshot tier
SHALL remain the fallback.

#### Scenario: Phone receives time-limited TURN credentials, not the secret
- **WHEN** the desktop offers a live session
- **THEN** the phone receives an ICE-server list with short-lived TURN credentials, and never the TURN shared secret

#### Scenario: No TURN configured degrades honestly
- **WHEN** live A/V is requested but no TURN is configured
- **THEN** the viewer states live A/V is unavailable and offers the snapshot tier instead of hanging

### Requirement: A live session SHALL be honest, audited, and fail-safe
A live session SHALL keep the Mac's hardware camera indicator AND the macOS
microphone indicator lit, SHALL NOT suppress either, and the phone UI SHALL state
that the session is live audio+video and not covert. Session start and
stop SHALL each emit an `av_session` audit event (metadata only) that syncs to the
phone and persists in the durable report. The session SHALL be held open by the
phone's keepalive heartbeat and SHALL auto-stop within a liveness timeout when the
phone is killed / backgrounded / offline, tearing down the peer and releasing the
camera and microphone.

#### Scenario: Both indicators lit, not covert
- **WHEN** a live session is active
- **THEN** the camera light and the microphone indicator are both on, and the phone UI states it is a live A/V session

#### Scenario: Session is audited on both ends
- **WHEN** a live session starts and later stops
- **THEN** an `av_session` start and stop event are emitted, sync to the phone, and appear in the durable report

#### Scenario: A vanished phone releases camera + mic
- **WHEN** the phone is killed/backgrounded/offline mid-session and its keepalive lapses
- **THEN** the desktop auto-stops within the liveness timeout, tears down the WebRTC peer, and both hardware indicators go dark
