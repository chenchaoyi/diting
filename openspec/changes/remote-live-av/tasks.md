# Tasks: remote-live-av

**Deferred on 2026-10-20.** All implementation tasks below remain unstarted.
This list is the proposed scope, not a record of delivered functionality. Read
[research.md](research.md) and resolve its open questions before starting work.

## 1. coturn on the VPS (infra — no app code)

- [ ] 1.1 `deploy/coturn/turnserver.conf` template: `realm` + Let's Encrypt cert,
      `listening-port=3478`, `tls-listening-port=443`, a small `min-port`/
      `max-port` UDP relay range, `use-auth-secret` with `static-auth-secret`
- [ ] 1.2 Hardening in the config: `denied-peer-ip` for loopback / RFC1918 /
      169.254.169.254, `total-quota`, `bps-capacity`, `fingerprint`, `no-cli`,
      `no-multicast-peers`
- [ ] 1.3 `deploy/coturn/install.sh` (Let's Encrypt + systemd + firewall notes),
      mirroring `deploy/self-tunnel/` ops style; a README with the ports to open
- [ ] 1.4 Verify a TURN allocation works from an external client (trickle-ice test)

## 2. Protocol v4 — `signal` message class + relay routes

- [ ] 2.1 `version.py`: `PROTOCOL_VERSION=4`, `SUPPORTED_VERSIONS={1,2,3,4}`
- [ ] 2.2 `protocol/messages.py`: `validate_signal` + `build_signal_schema`
      (`kind` enum `offer|answer|ice`, `sdp?`, `candidate?`); `_generate.py`
      writes `signal.schema.json` + a deterministic `sealed-signal.json` fixture
- [ ] 2.3 `crypto.py`: `seal_signal`/`open_signal` (stamp v4)
- [ ] 2.4 `relay/migrations/0004_signal.sql`: `signal_to_desktop` +
      `signal_to_phone` tables (delete-on-delivery, short TTL)
- [ ] 2.5 `relay/src/index.js`: bump `SUPPORTED_VERSIONS` to `{1,2,3,4}`; add
      `POST/GET /signal-to-desktop` + `/signal-to-phone` via the queue helpers
- [ ] 2.6 Tests: protocol conformance (new fixtures/hashes), relay signalling
      round-trip + direction + TTL; re-vendor note for diting-mobile

## 3. Helper WebRTC peer (device-verified)

- [ ] 3.1 Add libwebrtc to `helper/Package.swift` (Swift binary framework, e.g.
      `stasel/WebRTC`); `helper/Info.plist` `NSMicrophoneUsageDescription`
- [ ] 3.2 `main.swift` `webrtc` role: `AVCaptureSession` camera + mic →
      `RTCVideoSource`/`RTCAudioSource` → `RTCPeerConnection`; create offer;
      trickle ICE; stdio JSON-Lines signalling in/out; ICE config from stdin;
      camera/mic denial → exit 3
- [ ] 3.3 Extend the install permission sequence to include Microphone; verify
      permission retention/re-grant after the bundle update on supported macOS
- [ ] 3.4 `make helper` builds with the framework; bundle size documented

## 4. Daemon — signalling courier + live session + grant

- [ ] 4.1 `_helper.py`: `webrtc_peer()` wrapper (Popen, bidirectional stdio
      signalling: write ICE config + phone messages, read helper offer/ICE)
- [ ] 4.2 TURN cred minting: `turn.py` — `mint_credentials(secret, ttl)` (REST
      API: `username=<exp>:<nonce>`, `password=HMAC-SHA1`); config `DITING_TURN_URL`
      / `DITING_TURN_SECRET`
- [ ] 4.3 `companion/live.py` `LiveSessionDriver`: start on `av.start`, courier
      signalling (relay ↔ helper), keepalive/liveness/stop, teardown releases
      devices; `sink` signal seal/open + `signal-to-*` relay client methods
- [ ] 4.4 `runtime.py`/`capture.py`/TUI: spawn the live driver gated on the
      live-A/V flag; `state.py` `live_av_enabled`
- [ ] 4.5 `cli.py` `companion av on|off|status` + TUI toggle: foreground dual
      (camera+mic) grant via a `camsnap`-style probe; enable only on both
- [ ] 4.6 `av_session` audit event: add to `EVENT_SPEC` + `EventLogger` +
      fixtures (this is the one place a live session touches the event log)

## 5. Phone (separate chenchaoyi/diting-mobile change)

- [ ] 5.1 Re-vendor protocol v4; Dart `signal` codec + `sendSignal`/`pullSignal`
- [ ] 5.2 `flutter_webrtc`: answer the offer, apply the ICE config from
      signalling, render remote video + play audio
- [ ] 5.3 Camera viewer: live/snapshot toggle; honest connection states
      (connecting / live / relayed / poor / live-unavailable-no-TURN)
- [ ] 5.4 l10n EN+ZH; gates

## 6. Docs + gates

- [ ] 6.1 README + `docs/zh/README.md`: live A/V opt-in, the dual grant, the
      coturn deploy pointer, the honest limits (both indicators lit, not covert)
- [ ] 6.2 `tests/TESTING.md` (EN+ZH): the live-A/V test plan before test code
- [ ] 6.3 Gates: `uv run pytest`, tui snapshot, `openspec validate` (specs +
      change), `swift build`, relay `npm test`
- [ ] 6.4 Archive-readiness: coexists with `companion-remote-camera`; both
      archive once their features are device-verified stable
