## ADDED Requirements

### Requirement: The daemon SHALL courier WebRTC signalling and drive live sessions when live A/V is enabled
The daemon SHALL, when live A/V is enabled and paired, run the helper as the
WebRTC peer and courier signalling between it and the relay: it SHALL seal the
helper's outbound SDP/ICE onto the desktop→phone route and open the phone's
inbound SDP/ICE from the phone→desktop route and feed it to the helper. It SHALL
mint short-lived TURN credentials from the configured TURN secret and pass the
ICE-server configuration to the helper for the offer. It SHALL drive the session
lifecycle — start on the phone's request, hold on keepalive, stop on an explicit
stop or a lapsed liveness timeout — and on stop SHALL tear down the helper peer so
the camera and microphone are released. When live A/V is off, unpaired, or no
TURN is configured, the daemon SHALL NOT start a live session.

#### Scenario: Signalling is couriered both ways
- **WHEN** the helper emits an offer/ICE and the phone posts an answer/ICE
- **THEN** the daemon seals and forwards each across the correct relay route and feeds the phone's messages to the helper

#### Scenario: TURN credentials are minted per session
- **WHEN** a live session starts
- **THEN** the daemon mints short-lived TURN credentials from the secret and includes them (with STUN) in the ICE configuration given to the helper

#### Scenario: Stop releases the devices
- **WHEN** the session stops (explicit stop or liveness timeout)
- **THEN** the daemon tears down the helper peer and the camera and microphone are released

### Requirement: Live A/V SHALL be a distinct persisted opt-in requiring both grants
Live A/V SHALL be gated by its own persisted flag, separate from the snapshot
camera opt-in, and off by default. Enabling it (`companion av on` or the
equivalent TUI control) SHALL run a foreground grant that surfaces both the
camera and microphone prompts and SHALL enable only on both grants. Session
start/stop SHALL emit an `av_session` audit event through the normal sink.

#### Scenario: Live A/V opt-in is independent of snapshot
- **WHEN** the snapshot camera is enabled but live A/V is off
- **THEN** snapshot sessions work and no live session or signalling occurs

#### Scenario: Enabling requires camera and microphone
- **WHEN** the operator runs `companion av on`
- **THEN** it enables only if both the camera and microphone grants resolve to authorized, otherwise it reports the denial and stays off
