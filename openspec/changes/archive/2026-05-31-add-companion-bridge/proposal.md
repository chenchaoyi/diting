## Why

diting already detects everything worth knowing about a network — roams, RF
stirs, latency spikes, new BLE / LAN / Bonjour neighbours — but those events
only live inside the running TUI on one Mac. The user runs diting-mobile on
their phone and wants their phone to learn about the same events while away
from the Mac (e.g. at the office, knowing what the home Mac just saw), get a
push when something happens, and keep a local report file for on-device and
external-LLM analysis.

The constraint that shapes everything: an iOS app can only be woken when
closed via APNs, and the user wants reach beyond the local network. So the
transport must cross networks without leaking real captures — BSSIDs, SSIDs,
device names and IPs are sensitive and must never reach a third party in
cleartext.

## What Changes

- **New wire contract, owned here.** A versioned `companion-protocol` defines
  how a diting producer hands events to a companion consumer over an
  untrusted store-and-forward relay: the encryption envelope, the pairing QR
  payload, the relay HTTP API, and the APNs trigger shape. The event payload
  inside the envelope **reuses the existing pinned JSONL line schema** from the
  `events` / `event-log` capabilities — it is not a new event vocabulary.
- **New desktop sender, `companion-bridge`.** diting gains an opt-in pairing
  flow (QR rendered in the TUI), an event sink that taps the existing fan-out,
  end-to-end encryption of push-worthy events, and an offline queue that
  flushes when connectivity returns.
- **Push-worthiness reuses the watchdog.** The `_watchdog.py` severity
  thresholds + silence window decide which events are worth a push, so we do
  not relay every `ble_device_seen`.
- **End-to-end encrypted, relay-blind.** Events are sealed with libsodium
  secretbox under a key that only ever travels via the pairing QR. The relay
  (Cloudflare Worker + D1) stores and forwards ciphertext only. The APNs
  payload carries a count + coarse category — never a real identifier.
- **Machine-readable contract artifacts** (JSON Schema for the envelope + each
  event type, plus golden fixture lines) ship here as the canonical source.
  diting-mobile vendors them and runs a cross-repo conformance test, extending
  the "Cross-repo contracts" pattern already in mobile's `openspec/AGENTS.md`.
- **OFF by default.** Sending real captures off-device requires explicit
  pairing; nothing leaves the Mac until the user scans a code.
- **Relay source** (Cloudflare Worker) lands under a top-level `relay/`
  directory; its HTTP behaviour is specified in `companion-protocol`.

Out of scope (recorded so it is not assumed): the event source is the Mac TUI,
so a sleeping laptop produces no events — this feature does not provide 24/7
home monitoring. That is the future Pi-class sidecar, a separate product.
Also out of scope for v1: multiple paired devices (single device only), an
in-app LLM client on mobile (v1 exports/shares the report to an external LLM),
and a relay-cert-pinning hard requirement (the QR MAY carry a fingerprint).

External dependency to flag: closed-app push requires a **paid Apple Developer
account** for the Push Notifications entitlement. APNs JWTs (ES256) are signed
from the Worker.

## Capabilities

### New Capabilities
- `companion-protocol`: the canonical, versioned (`v1`) wire contract between a
  diting producer and a companion consumer — secretbox envelope, monotonic
  cursor, pairing QR payload, relay store-and-forward HTTP API, APNs trigger
  shape, and the machine-readable JSON Schema + golden fixtures that downstream
  consumers (diting-mobile) vendor and conform to. Back-compatible like the
  helper schema: a newer peer tolerates an older protocol version.
- `companion-bridge`: the desktop-side sender behaviour — opt-in pairing with
  in-TUI QR, git-ignored pairing state, the event sink that taps the existing
  fan-out and gates on the watchdog, secretbox encryption, the relay client,
  the offline queue, and the `--companion` config surface.

### Modified Capabilities
<!-- No existing capability's requirements change. The event sink consumes the
     `events` / `event-log` JSONL schema as-is (read-only dependency), and reuses
     `link-health`/`environment-monitor` watchdog thresholds without altering
     their contracts. If implementation reveals the event→wire-dict serialiser
     must be factored out of EventLogger in a behaviour-visible way, that delta
     will be added to `event-log` here. -->

## Impact

- **New code**: `src/diting/companion/` (pairing, sink, secretbox crypto, relay
  client, offline queue); `relay/` (Cloudflare Worker + D1 schema + wrangler
  config); `src/diting/companion/protocol/` (JSON Schema + golden fixtures).
- **Affected existing code** (read/tap, not rewrite):
  - `src/diting/tui.py` event fan-out (`events_ring.push` / `emit_*` /
    `_maybe_notify`, ~lines 6854–7346) — add a companion sink alongside.
  - `src/diting/cli.py` (~lines 256–450, 1169–1206) — `monitor` / `--log`
    paths and a new `--companion` surface.
  - `src/diting/_watchdog.py` — reuse `maybe_notify` severity + silence logic
    to gate push-worthiness.
  - `src/diting/event_log.py` `emit_*` — the event→dict shaping is the wire
    payload; may be factored into a shared serialiser.
- **New dependencies**: `pynacl` (secretbox), a terminal QR renderer
  (e.g. `qrcode` / `segno`). Relay side: Cloudflare Workers + D1 (no Python dep).
- **External**: paid Apple Developer account + APNs `.p8` key (stored as a
  Worker secret, never committed).
- **Privacy/config**: new git-ignored pairing-state file (mirrors `aps.yaml`),
  with a public `*.example` template. Feature OFF by default.
- **Cross-repo**: diting-mobile gains a paired `companion-protocol` change that
  vendors the JSON Schema + fixtures and adds a conformance + drift test.
- **Docs/i18n**: new user-facing strings via `t()` (EN+ZH parity); README
  EN+ZH gain a pairing section; `tests/TESTING.md` EN+ZH updated test-first.
