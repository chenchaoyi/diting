# show-paired-mobile-count — design

## Context

The relay (Cloudflare Worker + D1) forwards sealed envelopes from the
desktop producer (POST `/v1/channel/{id}`) to phone consumers (GET
`/v1/channel/{id}?since=…`), and rings an APNs doorbell. The desktop
only ever POSTs; phones only ever GET. All parties on a channel share
one bearer token (derived from the channel key), so the relay cannot
distinguish individual phones by token. The CompanionScreen renders the
pairing QR and a static hint line.

## Goals / Non-Goals

**Goals:**

- Show, on the desktop pairing screen, how many phones are pulling this
  channel right now — count only, privacy-light, no protocol change.
- Honest numbers: zero is a real shown state; errors never fabricate a
  count.

**Non-Goals:**

- Per-device identity / a device list (a much larger PII-bearing change).
- Any wire-format / `protocol_version` change.
- Tight presence for a backgrounded, non-polling phone (future
  foreground-`ping` follow-up; mobile needs no change for this version).

## Decisions

- **Presence = recently-active puller, not registered token.** Stale
  APNs tokens never expire, so a registered-token count only grows.
  The phone's existing authenticated pull is the heartbeat; nothing new
  is needed client-side.
- **Distinguish pullers by an opaque salted connection hash
  (resolves the blocking open question).** All phones share the channel
  bearer, so the token can't separate them — but the Worker has
  `cf-connecting-ip`. The presence key is
  `sha256(channelId + ":" + cf-connecting-ip)`: an opaque, per-channel,
  non-reversible dedupe key, never the IP itself, with a TTL. This
  yields an approximate distinct count. Honest caveat (documented in
  copy intent, not overclaimed): phones behind one NAT collapse to a
  single entry (undercount); the count never *over*states distinct
  networks. When `cf-connecting-ip` is absent (local/test), a fixed
  sentinel key is used so any pull registers as `active: 1`. Chosen
  over (a) registered-token count (only grows) and (b) any/none-only
  (loses real information when the Worker can in fact separate networks).
- **TTL = 90 s.** ≥ 2× the mobile pull cadence so one missed poll
  doesn't drop the count.
- **Storage: a D1 `presence` table, lazy-pruned on read.** Mirrors the
  existing envelopes lazy-purge in `handlePull`. `PRIMARY KEY (channel,
  puller)` makes the upsert idempotent; `last_seen` carries the TTL.
  No Durable Object / KV needed — the relay is already D1-backed.
- **Presence is upserted only on `/pull`, never on `/presence`.** The
  desktop's own `/presence` poll must not inflate the count; only the
  phone heartbeat (`/pull`) registers a puller. The desktop never pulls,
  so the count is phones-only by construction.
- **Endpoint:** `GET /v1/channel/{id}/presence`, Bearer-authed against
  the existing channel token, returns `{active, ttl_s, as_of}` — count
  + window + timestamp, no bodies, no identity. Read-only and idempotent
  (does not itself touch presence), safe to poll. 403 on bad token,
  404 on unknown channel — same as the other read path.
- **Desktop UI — honest-number states.** Poll every 4 s while the
  pairing screen is open (timer started on mount, stopped on unmount).
  One line under the QR, above the key hints:
  - connected: `↔ N 台设备已连接 · <relative as_of>` (cyan)
  - zero: `↔ 暂无设备连接` (dim — never hidden)
  - error/timeout: `↔ 无法确认连接数` (yellow — never a stale/guessed number)
  - loading (first poll pending): `↔ 检查连接中…` (dim)
  The count is a measurement → mono face; relative time tracks `as_of`.
  Singular/plural handled in EN (`1 device connected`).

## Risks / Trade-offs

- [NAT undercount] → multiple phones on one network read as 1. Accepted:
  the alternative (exact identity) needs a protocol bump and PII. The
  copy says "connected", not "distinct devices", so 1-vs-2 ambiguity on
  one LAN is tolerable.
- [IP churn overcount] → a phone roaming WiFi↔cellular within the TTL
  could briefly count as 2. Bounded by the 90 s window; self-heals.
- [Presence table growth] → bounded by lazy-prune on read + the small
  per-channel puller set; an unused channel's rows decay and are deleted
  on the next presence/pull read.
- [Polling a screen the user left open] → 4 s cadence on one tiny GET is
  negligible; the timer is scoped to the screen and stopped on unmount.
