## Status

Deferred on 2026-10-20 at the maintainer's request. This is a design proposal;
implementation has not started. The original design was drafted on 2026-07-07.
See [research.md](research.md) for the recovered context, verified code baseline,
open questions and suggested restart point. No protocol, dependency or deployment
change is included in this proposal checkpoint.

## Why

The shipped remote-camera feature is a low-rate JPEG *snapshot* checkup (open a
session, pull ~4 fps stills over the blind relay). It is deliberately not live:
the poll-based relay can't carry smooth audio/video, so there is no sound and no
real-time motion. The operator sometimes wants to actually *watch and listen* —
see live movement and hear the room — not just glance at stills.

This change adds a **live audio+video** tier on top of the snapshot one, using
real-time WebRTC (peer-to-peer, DTLS-SRTP encrypted media) instead of the
snapshot pipeline. It is a deliberate escalation from "checkup" to "live view",
so it comes with a correspondingly stronger honesty/consent model.

## What Changes

- **New live-A/V session over WebRTC.** From the phone, start a live session; the
  Mac and phone establish a WebRTC peer connection and stream camera **and
  microphone** in real time, end-to-end encrypted (DTLS-SRTP). The existing
  snapshot mode stays as the lighter, infra-free fallback.
- **Signalling over the existing relay.** SDP offer/answer + trickled ICE ride a
  new sealed `signal` message class on the companion relay (two ephemeral
  routes, phone↔desktop), exactly like `command`/`media` — the relay stays blind.
- **Native WebRTC in the helper.** The macOS helper (`diting-tianer.app`, which
  already owns the camera/mic TCC grants) becomes the WebRTC peer: it captures
  camera + mic, encodes, and runs the peer connection (libwebrtc). It exchanges
  signalling with the daemon over stdio; the daemon seals/relays it. This is the
  only place that can hold the grants, so the peer must live here.
- **Microphone opt-in + grant.** Live A/V additionally needs the microphone
  (`NSMicrophoneUsageDescription`; verify the updated bundle's permission
  migration on supported macOS versions). The
  camera+mic grant is proven in the foreground when the operator enables live
  A/V, same pattern as `camera on`.
- **TURN relay for NAT traversal.** Cross-network peers need a TURN server;
  self-hosted **coturn** on the operator's VPS (TURN-over-TLS on 443,
  short-lived HMAC credentials — the same shared-secret pattern as the relay
  auth token), which is China-reachable and self-controlled (the WebRTC-native
  analog of gtmux's self-hosted `--backend self` VPS tunnel). Public STUN for
  the P2P-direct path; the desktop mints time-limited TURN creds and hands the
  ICE-server config to the phone inside the sealed signalling.
- **Stronger consent + honesty model.** Off by default; enabling live A/V is a
  distinct, explicit opt-in that surfaces BOTH the camera and microphone macOS
  prompts in the foreground. During a session the Mac's hardware camera light
  AND the macOS microphone indicator are lit — never suppressed. Every session
  is an audited `av_session` event on both ends. A vanished phone auto-stops the
  session (heartbeat), releasing camera + mic.

## Capabilities

### New Capabilities
- `remote-live-av`: the operator-initiated live audio+video session — the
  WebRTC session lifecycle (offer/answer/ICE, keepalive, stop, liveness-timeout),
  the camera+mic dual opt-in and foreground grant, the TURN/ICE configuration,
  the audit event, and the honesty/consent model (both hardware indicators lit,
  not covert; live-vs-snapshot are distinct tiers).

### Modified Capabilities
- `companion-protocol`: adds a v4 `signal` sealed message class (SDP + ICE) and
  its two ephemeral relay routes, parallel to `command`/`media`.
- `companion-bridge`: the daemon gains the signalling courier + live-A/V session
  control, gated by the live-A/V opt-in, running the helper as the WebRTC peer.
- `macos-helper`: the helper gains a WebRTC-peer role (camera+mic capture +
  peer connection + stdio signalling) and `NSMicrophoneUsageDescription`.

## Impact

- **Protocol** (`src/diting/companion/protocol/`): v4 `signal` schema + fixtures
  + manifest; version set `{1,2,3,4}`.
- **Relay** (`relay/`): a `signal` migration + phone↔desktop routes.
- **Helper** (`helper/`): libwebrtc dependency (Swift binary framework), a
  `webrtc` role (AVCapture camera + mic → RTCPeerConnection, stdio signalling),
  `NSMicrophoneUsageDescription`. Bundle grows (~tens of MB).
- **Daemon** (`src/diting/companion/`): signalling courier, live-A/V session
  driver, TURN-cred minting, `av on/off` (dual grant). New TURN config
  (`DITING_TURN_URL` / `DITING_TURN_SECRET`, like the relay token).
- **VPS**: coturn deploy (config + Let's Encrypt + HMAC auth + peer-IP denylist +
  quotas), mirroring the `deploy/self-tunnel/` ops style.
- **Phone** (separate `chenchaoyi/diting-mobile` change): `flutter_webrtc`
  viewer — answer the offer, render remote video, play audio, use the ICE
  config from signalling; a live-vs-snapshot toggle in the camera viewer.
- **Coexists with** the shipped snapshot feature (`companion-remote-camera`):
  live A/V is the heavier opt-in tier (needs coturn + mic grant); snapshot stays
  the infra-free fallback.

## Non-Goals

- No multi-viewer / SFU (1:1 only). No recording/archival of the live stream.
- No screen sharing. No pan/tilt. No always-on / scheduled sessions.
- The snapshot tier is not removed or rewritten.
