# diting companion relay

End-to-end-encrypted store-and-forward for diting desktop→mobile pairing,
on a Cloudflare Worker + D1. The relay forwards **ciphertext only** and
rings an APNs doorbell; it never holds the secretbox key and cannot read
event content. The wire contract is `companion-protocol`, owned in the
diting repo (`openspec/changes/add-companion-bridge`).

## What it does

- `POST /v1/channel/:id` — store one ciphertext envelope (producer). The
  channel binds to the bearer's hash on first contact (trust-on-first-use);
  later requests must present the same bearer. Idempotent per `seq`. If the
  channel has a registered APNs token, fires a content-free push. An
  optional `X-Diting-Category: ble|lan|link|bonjour|env` header is forwarded
  as a coarse hint (no identifiers).
- `GET /v1/channel/:id?since=N` — pull envelopes with `seq > N` in order
  (consumer). Expired rows (past TTL) are excluded and lazily purged. Each
  authenticated pull also upserts a short-TTL (90 s) presence entry keyed
  by an opaque, non-reversible hash of the connection (`sha256(channel +
  ":" + cf-connecting-ip)`) — never the IP, never a device identity.
- `GET /v1/channel/:id/presence` — count-only connected-puller report for
  the desktop pairing screen: `{ "active": N, "ttl_s": 90, "as_of": "…" }`.
  Read-only (does not itself register a puller), so a desktop polling it
  never inflates the count. Phones behind one NAT collapse to one entry
  (undercount); the relay stores nothing identifying.
- `POST /v1/channel/:id/apns` — register the consumer's APNs device token
  (`{ "token": "...", "sandbox": false }`).
- `DELETE /v1/channel/:id` — unpair: drop the channel, its envelopes, and
  its presence rows.

Auth bearer = `urlsafe_b64(HMAC-SHA256(channel_key, "diting-companion/v1 relay-auth"))`,
derived identically by the desktop (`diting.companion.protocol.auth`) and
the mobile consumer. The relay stores only `sha256(bearer)`.

## Deployed instance

- URL: `https://diting-companion-relay.ccy-chenchaoyi.workers.dev`
- D1: `diting-companion` (binding `DB`, id in `wrangler.jsonc`)
- Verified live: store / ordered cursor pull / 401 / 403 / 404 / idempotent
  re-store / unpair / envelope validation. APNs push is wired but inert
  until the secrets below are set (needs a paid Apple Developer account).

## Deploy

```bash
npm ci
npx wrangler d1 create diting-companion       # paste the id into wrangler.jsonc
npm run migrate:remote
# APNs token-auth credentials (from your paid Apple Developer account):
npx wrangler secret put APNS_KEY              # contents of the .p8 (PEM)
npx wrangler secret put APNS_KEY_ID           # 10-char key id
npx wrangler secret put APNS_TEAM_ID          # 10-char team id
npm run deploy
```

Set `APNS_BUNDLE_ID` (the mobile app's bundle id) and `APNS_HOST` in
`wrangler.jsonc` `vars`. Use the sandbox host per-channel via the
`sandbox` flag at APNs registration; `APNS_HOST` is the production default.

## Test

```bash
npm ci
npm test    # vitest inside the Workers runtime (workerd) + local D1
```

The suite (`test/relay.test.js`) covers store/forward, cursor pulls,
idempotency, TTL exclusion, auth (TOFU bind / 401 / 403 / 404), envelope
validation, and APNs registration / unpair.

> Authored without a reachable npm registry, so the JS suite was not
> executed in-repo. The cross-language auth-token derivation it depends on
> **is** verified on the Python side
> (`tests/test_companion_protocol.py::test_committed_relay_auth_fixture_matches_derivation`).
