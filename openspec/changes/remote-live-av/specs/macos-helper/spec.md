## ADDED Requirements

### Requirement: The helper SHALL expose a WebRTC peer role that captures camera + microphone
The helper bundle SHALL expose a role that runs a WebRTC peer: it SHALL capture
the default camera and microphone, wire them into a peer connection (native
libwebrtc), create the offer, and exchange signalling (SDP + trickled ICE) with
its parent over stdio JSON-Lines — the same subprocess pattern as the streaming
roles. It SHALL take the ICE-server configuration (STUN + TURN with credentials)
from its parent rather than embedding any secret. On camera or microphone TCC
denial it SHALL fail fast with the helper's denial exit code. It SHALL live on the
existing `diting-tianer` bundle so it inherits that bundle's cdhash and single TCC
subject.

#### Scenario: Peer captures A/V and offers
- **WHEN** the WebRTC role is started with an ICE configuration and camera+mic are authorized
- **THEN** it captures camera + microphone, emits an SDP offer + ICE candidates over stdio, and streams DTLS-SRTP media once connected

#### Scenario: Denied capture fails loud
- **WHEN** the camera or microphone is denied or restricted
- **THEN** the role exits with the helper's denial exit code and starts no session

#### Scenario: No embedded secret
- **WHEN** the role needs TURN
- **THEN** it uses the ICE configuration passed by its parent and never embeds a TURN shared secret

### Requirement: The helper SHALL declare a microphone usage description
The helper bundle SHALL declare `NSMicrophoneUsageDescription`. Adding it changes
the bundle; the install permission flow SHALL check the current grants and
request any missing permissions in the foreground, including the microphone
alongside the camera. Upgrade instructions SHALL reflect verified permission
retention/re-grant behaviour on supported macOS versions.

#### Scenario: Updated helper needs a microphone grant
- **WHEN** a user enables live A/V after updating the helper and the microphone grant is missing
- **THEN** the foreground grant flow requests microphone access and enables live A/V only when both capture permissions are authorized
