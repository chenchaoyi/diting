# Tasks

## 1. Test plan (tests-first)
- [x] 1.1 `tests/TESTING.md` (EN) + `docs/zh/TESTING.md` — `threats`
  security_downgrade row; `events`/`companion-bridge` local-only `security`.

## 2. Wire the cipher (desktop-local)
- [x] 2.1 `event_log.py` — `emit_connection_update` stamps `security` on both
  associated `link_state` payloads (first-poll + transition).
- [x] 2.2 `protocol/events_schema.py` — `LOCAL_ONLY_FIELDS` += `security`.

## 3. Detector
- [x] 3.1 `threats.py` — `_security_rank` (open<WEP<WPA<WPA2<WPA3; transitional
  ranks strongest; unrankable → None) + per-SSID strongest-cipher baseline +
  `security_downgrade` (point-in-time, cooldown per ssid).
- [x] 3.2 `insights.py` `format_insight_summary` + `i18n.py` (EN↔ZH) one-liner.

## 4. Tests
- [x] 4.1 Detector: fires on weaker / not on first / not on same-or-stronger /
  skips unrankable / transitional ranks strongest; cooldown per ssid.
  (`tests/test_threats.py`)
- [x] 4.2 `event_log`: associated link_state carries `security`; sink strips it.

## 5. Gates
- [x] 5.1 `uv run pytest`, snapshot regression, `openspec validate --specs --strict`,
  `openspec validate add-security-downgrade-threat --strict`.
