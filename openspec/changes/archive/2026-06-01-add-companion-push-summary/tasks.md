# Tasks

## 1. Test plan (tests-first)
- [x] 1.1 Update `tests/TESTING.md` (EN) + `docs/zh/TESTING.md` (ZH) with the
  push-summary cases before writing test code.

## 2. Producer
- [x] 2.1 Add `companion/push_summary.py` — `push_summary(payload)` → one-line
  localised body, fail-soft on missing fields (never raises).
- [x] 2.2 `companion/relay_client.py` — carry the summary on the queue and POST
  it as a cleartext `push` sibling (`ensure_ascii=False` for CJK names);
  omit when empty.
- [x] 2.3 `companion/sink.py` — compute `push_summary` and pass it to `enqueue`.
- [x] 2.4 `i18n.py` — EN keys + ZH values for every summary template.

## 3. Relay
- [x] 3.1 `relay/src/index.js` — strip the `push` sibling before validate/store;
  pass its `body`/`category` to the doorbell.
- [x] 3.2 `relay/src/apns.js` — `buildPushPayload(channel, category, detail)`
  uses `detail` as the alert body, falling back to the coarse text.

## 4. Tests
- [x] 4.1 Python: `push_summary` per-type + fallback; relay client sends the
  `push` sibling without mutating the envelope; no sibling when empty.
- [x] 4.2 Relay (vitest): the `push` sibling is stripped before storage and not
  returned to the consumer.

## 5. Gates
- [x] 5.1 `uv run pytest`, relay `npx vitest run`, snapshot regression, both
  `openspec validate` strict.
