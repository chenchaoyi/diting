# Tasks

## 1. Test plan (tests-first)
- [x] 1.1 `tests/TESTING.md` (EN) — add the `familiarity-store` section + the
  `events` familiarity-field + companion-strip rows BEFORE writing tests.
- [x] 1.2 `docs/zh/TESTING.md` — mirror.

## 2. Familiarity store
- [x] 2.1 `src/diting/familiarity.py` — `familiarity_key(kind, ...)` (BLE
  payload token w/ (vendor_id,name) fallback, never UUID/name; ap:bssid;
  lan:mac; bonjour:service). `FamiliarityStore(path)`: fail-soft load.
- [x] 2.2 `observe_seen(key, kind, now) -> str` — classify against
  pre-sighting state (`first_time`/`occasional`/`habitual`/`returning`,
  consts `_HABITUAL_DAYS=3`, `_RETURNING_GAP_DAYS=7`), then record.
- [x] 2.3 `observe_left(key, dwell_s)` — fold dwell EWMA. `flush()` — persist,
  bounded (`_MAX_ENTITIES`, `_AGE_OUT_DAYS=30`).

## 3. Event field
- [x] 3.1 `events.py` — optional `familiarity: str | None = None` on the seen
  dataclasses + `roam`; JSONL omits when None.
- [x] 3.2 `event_log.py` — carry `familiarity` through the emit_* methods.

## 4. Wiring
- [x] 4.1 Construct the store in `cli.py` (default path + `DITING_FAMILIARITY_STORE`),
  flush periodically + on shutdown; git-ignore the file + add `.example`.
- [x] 4.2 Seen/left emit sites — centralised in `event_log.py`: it derives the
  key (BLE reuses the payload key carried on the event; lan:mac; bonjour;
  ap:new_bssid on roam), calls observe_*, stamps the class. `ble.py` populates
  `vendor_id` + `manufacturer_hex` on the seen/left events.

## 5. Companion wire safety
- [x] 5.1 Companion sink strips local-only fields (`{"familiarity"}`) from the
  payload before sealing — wire stays within `companion-protocol`; mobile unaffected.

## 6. Tests
- [x] 6.1 Store: key derivation per kind (payload vs fallback; name never key);
  class thresholds; dwell EWMA; persistence round-trip; fail-soft corrupt;
  cap + age-out. (`tests/test_familiarity.py`)
- [x] 6.2 Events: seen carries `familiarity` with a store, omits without; JSONL key stability;
  payload-key recognition across rotating ids; baseline accrues when logging disabled.
- [x] 6.3 Companion: sink strips `familiarity` before sealing (wire clean / mobile-safe).

## 7. Gates
- [x] 7.1 `uv run pytest`, snapshot regression (48/48), `openspec validate --specs --strict`
  (24 passed), `openspec validate add-familiarity-baseline --strict` (valid).
