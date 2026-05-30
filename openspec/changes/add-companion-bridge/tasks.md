## 1. Protocol artifacts (canonical, `companion-protocol`)

- [x] 1.1 Update `tests/TESTING.md` (EN) + `docs/zh/TESTING.md` (ZH) with the conformance test plan BEFORE writing test code
- [x] 1.2 Sink consumes the exact payload dict via an `EventLogger` observer tap (`set_observer`) — same dict the JSONL writer emits, so drift is impossible by construction (stronger than parallel builders); existing event_log/events tests stay green
- [x] 1.3 Author JSON Schema for the envelope (version, channel, seq, ts, nonce, ciphertext) under `src/diting/companion/protocol/` — `schema/envelope.schema.json` + `envelope.py`
- [x] 1.4 Author JSON Schema for each event type, deriving from the existing `events`/`event-log` schema (English keys, omitted `None`, `[]` for empty) — `schema/event.schema.json` generated from `_schema_spec.py` (single source) via `events_schema.build_json_schema`
- [x] 1.5 Author golden fixture JSONL lines covering every event type + edge cases (omitted `None`, empty `[]`, CJK strings); stamp a protocol version/hash — `fixtures/events.jsonl` (generated from real `EventLogger`) + `manifest.json`
- [x] 1.6 Define the pairing-payload schema (version, channel id, base64 key, relay URL, optional fingerprint) and a canonical encode/decode helper — `pairing.py` + `schema/pairing.schema.json`
- [x] 1.7 Define the APNs trigger payload shape (count + coarse category + channel id only) and the coarse-category taxonomy — `apns.py` + `schema/apns-trigger.schema.json`
- [x] 1.8 Tests: fixtures validate against the schema; fail-closed validation; version abstention; pairing + envelope + trigger round-trips — `tests/test_companion_protocol.py` (33 tests). NOTE: secretbox round-trip + tamper/wrong-key tests move to group 3 with the `pynacl` dependency

## 2. Relay (Cloudflare Worker + D1, `relay/`)

- [x] 2.1 Scaffold `relay/` with `wrangler` config and a D1 schema (channel, seq, ts, ciphertext, expiry) — `relay/wrangler.jsonc` + `migrations/0001_init.sql`
- [x] 2.2 Implement `POST /v1/channel/{id}` storing a ciphertext envelope and assigning/honouring monotonic seq — producer-assigned seq, idempotent `ON CONFLICT DO NOTHING`
- [x] 2.3 Implement `GET /v1/channel/{id}?since={cursor}` returning ordered envelopes after the cursor, with TTL expiry — lazy purge + `expiry>now` filter
- [x] 2.4 Implement per-channel auth (token derived from the channel key) and reject unauthorized access without leaking bytes — HMAC bearer (`protocol/auth.py` + Worker `auth.js`), trust-on-first-use, relay stores only `sha256(token)`; 401/403/404
- [x] 2.5 Implement the APNs trigger: ES256 JWT signed via WebCrypto from the stored `.p8` Worker secret; send content-free alert push — `relay/src/apns.js` (cached JWT, content-free payload)
- [x] 2.6 Worker unit/integration tests (store→forward, cursor, TTL drop, auth refusal); document deploy + secret setup (no secrets committed) — `relay/test/relay.test.js` + README. NOTE: npm registry unreachable in authoring env, so the JS suite is unrun in-repo; the cross-language auth derivation it relies on is verified Python-side

## 3. Desktop sender (`companion-bridge`)

- [x] 3.1 Add `pynacl` + a terminal QR renderer to dependencies — `pynacl` + `segno`
- [x] 3.2 Implement pairing: generate channel id + symmetric key, render the QR, persist git-ignored pairing state — `companion/state.py` (QR via segno); rendered in the `companion pair` CLI (TUI render is the indicator task below)
- [x] 3.3 Add the git-ignored pairing-state path to `.gitignore` and ship a public `*.example` template — `diting-companion.json` ignored, `diting-companion.example.json` tracked
- [x] 3.4 Implement the secretbox encrypt + envelope-build path against the `companion-protocol` schema (monotonic seq) — `companion/crypto.py` (seal/open)
- [x] 3.5 Implement the relay client (POST) with a bounded local offline queue that flushes in order on reconnect, with honest drop indication on overflow — `companion/relay_client.py` (+ a User-Agent so Cloudflare doesn't 403 the producer, found via live test)
- [x] 3.6 Implement the event sink tapping the fan-out, gating push-worthiness via `_watchdog.py` thresholds + silence window — `companion/sink.py` + `push_policy.py` + the `EventLogger` observer tap; wired into both `monitor` and the TUI via `companion/runtime.py` (attach observer in init + periodic async flush; final drain on exit). Opt-in by pairing (`DITING_COMPANION=0` disables); the hot/unpaired path never imports pynacl
- [x] 3.7 Wire the `--companion` surface, off by default, surfacing paired/queued/reachable state — `diting companion pair/status/unpair` CLI + a TUI header subtitle chip (`companion: on` / `{n} queued` / `{d} dropped`) shown only when paired, so unpaired snapshots are unchanged
- [x] 3.8 Tests: crypto round-trip/fail-closed; policy gating; queue order + overflow; sink seals+enqueues; CLI — `tests/test_companion_sender.py` (22) + `test_companion_cli.py` (3). Verified END-TO-END live against the deployed relay (seal→POST→pull→decrypt round-trip, CJK preserved)

## 4. i18n, docs, validation

- [ ] 4.1 Add all user-facing strings via `t()` with EN+ZH parity (pairing prompts, companion status, queue/overflow notices)
- [ ] 4.2 Add a pairing/companion section to `README.md` + `docs/zh/README.md`, including the Apple Developer account prerequisite and the Mac-asleep limitation
- [ ] 4.3 Run all four CI gates: `uv run pytest`; `uv run python scripts/tui_snapshot.py --mode regression`; `openspec validate --specs --strict`; `openspec validate add-companion-bridge --strict`

## 5. Cross-repo handoff (diting-mobile, tracked, executed in mobile session)

- [ ] 5.1 Confirm the canonical protocol artifacts + version/hash are final here before mobile vendors them
- [ ] 5.2 Open the paired `companion-protocol` change in diting-mobile that vendors the JSON Schema + fixtures and adds the conformance + drift test
- [ ] 5.3 Cross-link: add a "companion protocol" note to both `CLAUDE.md` files pointing at the canonical spec + the vendor/sync rule
