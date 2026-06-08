# show-paired-mobile-count

## Why

The desktop pairing screen (`k` → `Companion — scan in diting-mobile`)
shows only the QR and the `r / u / esc` hint line. A user who has
already paired a phone gets no confirmation from the desktop that
anything is actually listening. Show whether any diting-mobile is
**currently connected** to this channel.

**A count, not a device list.** The companion protocol is channel-based
and identity-free by design — the pairing QR carries only `channel /
key / relay_url / fingerprint`, the APNs registration sends only
`{token, sandbox}`, and the event envelope has no sender field. Multiple
phones scanning one QR share one channel + one key and cannot be told
apart. A connected-*count* needs no identity, so this stays
privacy-light: no new PII, no wire-format change, no protocol bump.

## What Changes

- **Relay:** the existing authenticated pull (`GET /v1/channel/{id}`) —
  the phone's recurring heartbeat — upserts a short-TTL presence entry
  keyed by an opaque per-connection hash (salted `cf-connecting-ip`),
  never a stored identity. A new `GET /v1/channel/{id}/presence`
  (Bearer-authed, same convention) returns `{active, ttl_s, as_of}`.
- **Desktop:** the pairing screen polls `/presence` every few seconds
  and renders one connected-count line under the QR — connected / zero
  / error states, bilingual, in the mono face like other diting data,
  with semantic colour (connected vs none vs error).

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `companion-bridge`: a new requirement for the relay presence endpoint
  (TTL-decayed, count-only, no identity) and a new requirement for the
  desktop pairing screen's connected-count display (connected / zero /
  error states).

## Out of scope

- Per-device identity or a device list (would need new identity fields
  + a registry + a `protocol_version` bump + re-vendoring into
  diting-mobile).
- Any change to the QR / `pairing.schema.json` / `envelope.schema.json`
  or any `protocol_version` bump — the wire contract is untouched.
- Counting registered APNs tokens (stale tokens never expire, so that
  number only grows — recent-pull presence reflects phones online now).
- A mobile-side foreground `ping` for tighter presence — a follow-up;
  the existing periodic pull is the heartbeat, so diting-mobile needs
  no code change.

## Impact

- `relay/migrations/0002_presence.sql` — presence table.
- `relay/src/index.js` — presence upsert in `handlePull`; new
  `handlePresence` + route; `relay/test/relay.test.js` cases.
- `src/diting/companion/relay_client.py` — `fetch_presence()` (GET,
  injectable transport returning a body).
- `src/diting/tui.py` — `CompanionScreen` presence line + poll timer +
  state rendering; `src/diting/i18n.py` — EN keys + ZH values.
- `tests/` + `tests/TESTING.md` + `docs/zh/TESTING.md`.
