## Context

diting detects events on one Mac and keeps them in an in-memory `EventRing` plus
an optional `diting-*.jsonl` log. The user runs diting-mobile and wants the
phone to mirror those events from anywhere, get woken when something happens,
and keep a local report for analysis. There is no networking surface in diting
today; mobile has no networking, push, persistence, or LLM path either.

The hard constraints that drive the design:
- An iOS app closed in the background can only be woken via **APNs**, which
  requires a paid Apple Developer account. There is no LAN-only substitute.
- Reach is **cross-network** (office ↔ home), so same-LAN sync is insufficient.
- Captures contain **real BSSIDs / SSIDs / device names / IPs**; diting's
  standing rule is they never reach a third party in cleartext.

These three together force a store-and-forward design where the transport is
untrusted and everything sensitive is end-to-end encrypted, with APNs used only
as a content-free doorbell.

## Goals / Non-Goals

**Goals:**
- A versioned, machine-checkable wire contract owned canonically in this repo,
  reusing the existing JSONL event schema as the payload.
- End-to-end encryption such that the relay and Apple see only ciphertext /
  a content-free trigger.
- Cross-network reach with offline queueing on the producer.
- Opt-in, off-by-default, single paired device for v1.
- Zero-ops relay.

**Non-Goals:**
- 24/7 home monitoring — the source is the Mac TUI; a sleeping laptop emits
  nothing. The always-on story is the future Pi-class sidecar (separate product).
- Multiple paired devices, key rotation UX, relay-cert-pinning as a hard
  requirement (the QR MAY carry a fingerprint), and an in-app mobile LLM client
  (v1 exports/shares the report to an external LLM).
- Live foreground streaming (WebSocket). v1 is pull-on-wake + pull-on-foreground.

## Decisions

### D1 — Transport: E2E store-and-forward relay (not VPN, not plaintext cloud)
A relay queues ciphertext for the phone to pull when reachable; the producer
encrypts, the relay is blind.
- *vs Tailscale/WireGuard mesh*: direct and E2E, but the iOS tunnel must come up
  in the background on push (fiddly), and a sleeping/absent peer means no queue.
  The relay naturally queues while the phone is unreachable — exactly the
  "I'm at the office" case.
- *vs plaintext cloud / FCM data payloads*: violates the privacy rule.

### D2 — Relay platform: Cloudflare Worker + D1 (not a self-hosted VPS)
- Zero ops, free tier ample for personal volume, automatic TLS, global edge.
- D1 (SQLite) makes the cursor pull a single `WHERE channel=? AND seq>? ORDER BY
  seq` query; KV would make ordered pagination awkward.
- APNs token auth is an ES256 JWT signed with the `.p8` (P-256) key; Workers'
  WebCrypto (`ECDSA P-256`) signs it natively — verified as a well-trodden path.
- *vs VPS*: a VPS means recurring patching, cert renewal, uptime, and a single
  point of failure for a ~200-line service; the E2E encryption neutralises the
  "trust the platform" advantage a VPS would otherwise offer.
- The relay logic is small and portable, so platform lock-in risk is low.

### D3 — Crypto: libsodium secretbox under a QR-delivered pre-shared key
- XSalsa20-Poly1305 authenticated encryption; the key is generated on the Mac,
  shown only in the pairing QR, and stored on each device — never sent to any
  server. `pynacl` on the producer, `sodium`/`cryptography` on mobile.
- A pre-shared symmetric key is sufficient for a personal single-device pairing
  and far simpler than an asymmetric handshake; revisit if multi-device lands.

### D4 — Payload: reuse the pinned JSONL event schema verbatim
- The `events`/`event-log` capabilities already pin a locale-stable,
  English-keyed, additive-only event object. Sealing that exact object as the
  plaintext means the wire vocabulary and the on-disk report share one schema,
  and the analyzer/report code is shared rather than duplicated.
- Factor the existing event→dict shaping out of `EventLogger.emit_*` into a
  shared serialiser so the logger and the sink cannot drift.

### D5 — Push-worthiness: reuse `_watchdog.py`
- The watchdog already encodes "what deserves a macOS alert" (severity
  thresholds + silence window). Reusing it for "what deserves a phone push"
  keeps one notion of signal and avoids a second, divergent threshold set.

### D6 — APNs as a content-free doorbell
- The push carries count + coarse category + channel id only. The phone wakes,
  pulls ciphertext, decrypts locally, and only then renders rich text. Apple
  never sees a real identifier. Reliable alert pushes are used (not silent
  content-available, which iOS throttles and may drop); the full content syncs
  on open as the source of truth.

### D7 — Cross-repo contract governance
- Canonical JSON Schema + golden fixtures live here under
  `src/diting/companion/protocol/`. diting-mobile vendors a copy under its
  `protocol/` dir and runs a conformance test against the fixtures plus a
  version/hash drift check. This extends the existing "Cross-repo contracts"
  clause in mobile's `openspec/AGENTS.md` (BLE decoders). A protocol-affecting
  change requires paired OpenSpec changes in both repos at the same version.
- No third shared repo / submodule yet — revisit when a third consumer (the Pi
  sidecar) appears.

## Risks / Trade-offs

- **Mac-asleep blindness** → Documented as a non-goal; the sidecar is the fix.
  No silent pretence of 24/7 coverage.
- **APNs background delivery is best-effort** → Treat the relay as the source of
  truth; missed doorbells self-heal on next foreground pull via the cursor.
- **Apple Developer account is a hard external dependency ($99/yr)** → Surfaced
  in the proposal; the LAN/foreground path can be demoed before the account
  exists, but closed-app push cannot.
- **Relay sees traffic timing + volume metadata** → Accepted; only ciphertext
  and routing metadata are exposed, never event content. TTL bounds retention.
- **Pre-shared key compromise = full channel readability** → Re-pairing rotates
  channel id + key; key lives only on paired devices and in the QR.
- **Offline queue overflow** → Bounded queue with an honest, user-visible drop
  indication rather than unbounded growth or silent loss.
- **Cross-repo drift** → Conformance test + version/hash check fail loudly on
  both sides; the canonical copy is single-sourced here.

## Migration Plan

Feature is additive and off by default; no migration of existing behaviour.
Rollback is removing the pairing (channel id + key) — the sink goes inert.
Phasing: (1) protocol artifacts + relay, (2) desktop sink + pairing, (3) mobile
consumer + report, (4) mobile report/LLM export. Phases 1–2 ship and self-test
in this repo independently of the mobile half.

## Open Questions

- Relay channel auth token: derive from the channel key (HMAC) vs a separate
  bearer in the QR? Leaning derived, to keep the QR minimal.
- D1 vs Durable Object per channel: D1 ships v1 for simplicity; a DO would later
  enable a hibernatable WebSocket for live foreground streaming.
- QR rendering library on the producer (`segno` vs `qrcode`) and whether to also
  expose the payload as a copyable URI for manual entry.
- Coarse-category taxonomy for the APNs trigger — confirm the minimal set
  ("link" / "ble" / "lan" / "bonjour" / "env") leaks nothing useful.
