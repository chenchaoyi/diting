# Tasks

> Paired protocol change. Desktop (this repo) is the source of truth: land the
> wire contract + fixtures here, then vendor into diting-mobile. Do NOT release
> desktop to users until mobile ships v2 support (per-envelope versioning keeps
> desktop-updated-first safe — the phone just won't see insights until it
> updates).

## 0. Confirm the version strategy
- [x] 0.1 Confirm per-envelope minimum-version stamping (recommended) vs a
  flag-day all-v2 bump. (Blocks the wire work.)

## 1. Test plan (tests-first)
- [x] 1.1 `tests/TESTING.md` (EN) — companion-protocol `insight` type + `obj`
  tag + v2 + per-envelope stamping; companion-bridge insight-forward rows;
  events nested-detail update. Mirror `docs/zh/TESTING.md`.

## 2. Wire shape
- [x] 2.1 `protocol/_schema_spec.py` — add the `insight` spec + the `obj` tag
  (doc the tag table).
- [x] 2.2 `protocol/events_schema.py` — `_tag_ok` + `_TAG_SCHEMA`/`_field_schema`
  handle `obj` (`{"type":"object"}`, inner keys unconstrained).
- [x] 2.3 `event_log.py` — `emit_insight` emits `detail` as a nested object (drop
  the flatten); update the v1.13.0 flattened-shape tests to nested.

## 3. Versioning
- [x] 3.1 `protocol/version.py` — `PROTOCOL_VERSION = 2`,
  `SUPPORTED_VERSIONS = {1, 2}`; `EVENT_MIN_VERSION = {"insight": 2}`.
- [x] 3.2 Seal path (`crypto.seal_event` / `sink`) — stamp the envelope `v` at
  the event's min version; envelope schema `v` enum → `[1, 2]`.

## 4. Push wiring
- [x] 4.1 `push_policy.py` — add `insight` to `DEFAULT_PUSH_TYPES`; `_target`
  insight branch → `code`. (Salience gate already drops `info`.)

## 5. Regenerate + vendor
- [x] 5.1 `python -m diting.companion.protocol._generate` — regenerate
  `event.schema.json`, `fixtures/events.jsonl` (gains an `insight` line),
  `manifest.json`. Commit the regenerated artifacts.

## 6. Tests
- [x] 6.1 Protocol: insight validates (nested detail, unknown inner keys ok);
  v2 in supported set; per-envelope stamping (existing→v1, insight→v2);
  fixtures reproducible. Bridge: threat forwards, info dropped, code-keyed
  window. Events: nested-detail JSONL.

## 7. Gates
- [x] 7.1 `uv run pytest`, snapshot regression, `openspec validate --specs --strict`,
  `openspec validate forward-insights-over-companion --strict`.

## 8. Paired mobile change (separate repo `chenchaoyi/diting-mobile`)
> Step-by-step handoff (artifact hashes, Dart decode, render/notify, insight
> code catalog, sequencing): see `mobile-handoff.md` in this change dir.
- [ ] 8.1 Vendor the regenerated `protocol/` artifacts; conformance test green.
- [ ] 8.2 Decode + render `insight` (info/note/warn → `[INSIGHT]`, critical →
  `[THREAT]`) + notification; confirm it abstains on v2 envelopes pre-support.
- [ ] 8.3 Ship mobile v2 BEFORE the desktop release that forwards insights.
