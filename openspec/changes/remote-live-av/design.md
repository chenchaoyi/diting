# Design: remote-live-av

Status: **deferred, design only** (2026-10-20). The architecture below records the
2026-07-07 direction; library packaging, TCC re-grant behaviour and the VPS network
layout still need validation. See [research.md](research.md) before resuming.

## Context

The shipped remote camera (`companion-remote-camera`) is a snapshot checkup: the
desktop's `camstream` helper emits ~4 fps JPEGs, sealed and pushed to the relay's
delete-on-delivery `media` queue, and the phone polls them. That pipeline is
poll-based store-and-forward — fine for stills, structurally unable to carry
smooth, synchronised, low-latency audio+video. Live A/V needs a real-time media
transport: **WebRTC** (UDP peer-to-peer, DTLS-SRTP encrypted, ICE for
connectivity), which the current relay is not.

Two hard constraints shape every decision:
1. **The camera/mic TCC grants belong to the helper bundle's cdhash.** A Python
   or Go process can't hold them (the reason `camsnap`/`camstream` live in the
   helper). So the *media-capturing* peer must be the helper.
2. **Cross-network + China reachability.** The Mac and phone are usually on
   different networks; the maintainer's context is China. P2P-direct often fails
   behind NAT, so a TURN relay is required, and it must be reachable from China.
   gtmux already proved the pattern for HTTP (`--backend self`: chisel over
   TLS/443 to the user's own VPS). The WebRTC-native analog is coturn on the
   same VPS.

## Goals / Non-Goals

**Goals**
- Live, synchronised camera + microphone from the Mac to the phone, real-time,
  end-to-end encrypted, cross-network.
- Reuse the existing sealed companion relay for signalling only (the media never
  touches it).
- Keep the snapshot tier intact as the infra-free fallback.
- A consent/honesty model proportionate to a live A/V (both hardware indicators
  lit; explicit dual opt-in; audited; auto-stop).

**Non-Goals**
- Not 1:many / SFU, not recording, not screen share, not always-on.
- Not removing the snapshot tier.
- Not shipping a hosted TURN for all users (this is a self-hosted, personal tool;
  coturn on the operator's VPS).

## Decisions

### 1. The WebRTC peer lives in the helper (native libwebrtc)
The helper already holds camera + mic TCC, so it becomes the peer: an
`AVCaptureSession` feeds an `RTCVideoSource` + `RTCAudioSource`, wired into an
`RTCPeerConnection` (libwebrtc via a Swift binary framework, e.g. the
`stasel/WebRTC` packaging of Google's libwebrtc). It does hardware-accelerated
H.264/VP8 + Opus encode and DTLS-SRTP — native quality and A/V sync that a
re-encode-in-Python (aiortc) path can't match. Cost: libwebrtc is a large binary
dependency; the bundle grows by tens of MB, and the helper build gains a
SwiftPM/CocoaPods binary target. Accepted — the alternative (aiortc feeding off
`camstream` JPEGs + a new mic pipe) both re-encodes and can't sync A/V well.

### 2. Signalling over the relay as a v4 `signal` message class; media never touches it
WebRTC needs a signalling channel to exchange SDP offer/answer + ICE candidates.
Reuse the blind relay: a new sealed `signal` message class (protocol v4), sealed
under the channel key like `command`/`media`, carrying
`{kind: offer|answer|ice, sdp?, candidate?}`. Two ephemeral delete-on-delivery
routes mirror `command`/`media` but are bidirectional:
`signal-to-desktop` (phone→desktop) and `signal-to-phone` (desktop→phone). The
relay stays blind (opaque ciphertext, short TTL). The **media itself** flows
peer-to-peer over WebRTC (or via TURN) and **never** transits the relay — only
the tiny signalling does. Trickle ICE: candidates stream as they're gathered.

The helper is the signalling *endpoint* but not the *courier*: it emits/consumes
signal JSON over stdio (like `ble-scan`), and the daemon (which holds the channel
key + relay token) seals and posts/pulls them. So:
`helper (WebRTC + signal JSON over stdio) ↔ daemon (seal ↔ relay) ↔ phone`.

### 3. The DESKTOP offers; the phone answers
The desktop has the media tracks, so on a phone `av.start` the helper creates the
offer (camera + mic tracks), and the phone answers. Both trickle ICE back through
signalling. This keeps the phone a pure consumer of the offer.

### 4. TURN = self-hosted coturn on the operator's VPS; desktop mints the creds
- coturn on the VPS, preferably **TURN-over-TLS on 443** if a dedicated listener
  is available, a small UDP relay-port range, and a Let's Encrypt certificate.
  TURN-over-TLS is not HTTPS; an ordinary HTTP reverse proxy cannot forward it.
  Check coexistence with the existing gtmux HTTPS listener before choosing the
  port/IP arrangement. China reachability remains a deployment measurement,
  not an established result of this design.
- Auth via `use-auth-secret` (TURN REST API): the shared secret lives on coturn
  **and** the desktop only (config: `DITING_TURN_SECRET` + `DITING_TURN_URL`,
  baked/env like the relay token). The desktop mints short-lived creds
  (`username = <expiry>:<nonce>`, `password = base64(HMAC-SHA1(secret, username))`)
  and sends the full ICE-server list (public STUN + this TURN with the minted
  creds) to the phone **inside the sealed signalling**. The phone never sees the
  shared secret — only time-limited creds. This mirrors the relay-auth HMAC
  derivation the project already uses.
- Security hardening (documented + in the deploy config): `denied-peer-ip` for
  loopback / RFC1918 / the cloud metadata IP (stop the relay being an SSRF
  jump-box), `total-quota` / `bps-capacity`, `fingerprint`, `no-cli`,
  `no-multicast-peers`.
- A proposed `deploy/coturn/` dir (config template + a Let's Encrypt + systemd
  setup script) would mirror the **gtmux repository's** `deploy/self-tunnel/`
  ops style. No deployment assets have been created here yet.

### 5. Consent + honesty model (proportionate to live A/V)
Live A/V is a real monitoring capability, so the model is stronger than snapshot:
- **Off by default**, a distinct opt-in from snapshot. Enabling (`companion av on`
  or a TUI toggle) runs a foreground grant that surfaces BOTH the camera and the
  microphone macOS prompts, and only enables on both grants.
- **Both hardware indicators lit, never suppressed:** the camera light and the
  macOS microphone indicator (menu-bar orange dot). Stated plainly on the phone
  UI — this is not covert.
- **Audited:** session start/stop emit an `av_session` event (metadata only) on
  both ends, into the durable report — the act of live-watching is itself a
  first-class record.
- **Heartbeat-held, fail-safe:** the phone beats keepalive; a killed/backgrounded/
  offline phone auto-stops the session within the liveness timeout, which tears
  down the peer and **releases camera + mic** (both indicators go dark).

### 6. Coexist with the snapshot tier
Snapshot (`companion-remote-camera`) stays the default, infra-free "checkup"
(no TURN, no mic, works anywhere the relay does). Live A/V is the heavier opt-in
tier (needs coturn + mic grant). The phone's camera viewer gains a live/snapshot
choice; live is unavailable (greyed, with a reason) when TURN isn't configured or
the mic grant is absent. This keeps the reliable fallback and makes the escalation
explicit.

## Risks / Trade-offs

- **libwebrtc bloats the helper + complicates the build.** Tens of MB, a binary
  framework target, and another cdhash change (mic key). Accepted as the price of
  native real-time A/V; snapshot remains for anyone who won't run it.
- **TURN is self-hosted infra the operator must run + secure.** coturn is an abuse
  magnet; the denylist + quota + short-lived-cred hardening is mandatory, not
  optional. Documented, with a deploy script.
- **China reachability isn't guaranteed even with coturn.** TURN-over-TLS/443
  is a path to test, but a poorly-routed VPS may still drop. The snapshot fallback
  covers the "couldn't connect live" case honestly (the UI says so and offers
  snapshot).
- **Privacy escalation.** This turns a checkup into a live A/V monitor. The dual
  opt-in + both indicators + audit event are the mitigations; the design refuses
  to suppress any indicator or hide any session.
- **A/V sync + latency depend on the network.** WebRTC adapts bitrate; over TURN
  the latency is higher than P2P-direct. The UI shows connection state honestly
  (connecting / live / relayed / poor).

## Phasing

1. **coturn on the VPS** — deploy config + script (TLS/443, HMAC auth, denylist,
   quotas). Verify a TURN allocation works. (Infra; no app code.)
2. **Protocol v4 `signal`** — message class + relay `signal-to-{desktop,phone}`
   routes + fixtures + version set (Python + relay JS + tests; pure, testable).
3. **Helper WebRTC peer** — libwebrtc integration, camera+mic capture,
   offer/ICE, stdio signalling; `NSMicrophoneUsageDescription`. (Biggest;
   device-verified.)
4. **Daemon** — signalling courier, live-A/V session driver, TURN-cred minting,
   `av on/off` dual grant, `av_session` audit event.
5. **Phone** (separate diting-mobile change) — `flutter_webrtc` viewer + the
   live/snapshot toggle + honest connection states.
6. **Docs + privacy surface** — README/CHANGELOG (EN+ZH), the honesty copy, the
   coturn deploy guide.

Phases 1–2 are infra + pure protocol (no device). Phase 3 is the heavy native
work needing a real Mac. Each phase is a separately-mergeable PR; the openspec
change stays open until all land, then archives.

## Migration

Additive and back-compatible. Protocol v4 keeps `{1,2,3}` decodable; a phone/
desktop without live A/V simply never sends `signal` and never offers live.
The snapshot tier is untouched. Adding microphone support changes the helper
bundle. Verify permission retention and foreground re-grant behaviour on the
supported macOS versions before documenting the upgrade steps; a universal
one-time reset of every existing grant has not been established. TURN is opt-in:
with no `DITING_TURN_*` configured, live A/V is unavailable and the UI says so;
snapshot still works.
