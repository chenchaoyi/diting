# Tasks

## 1. Test plan (tests-first)
- [x] 1.1 `tests/TESTING.md` (EN) — add a `salience` section + the `events`
  salience-field row + the `companion-bridge` salience-gate / strip rows BEFORE
  writing tests.
- [x] 1.2 `docs/zh/TESTING.md` — mirror.

## 2. Salience scorer
- [x] 2.1 `src/diting/salience.py` — `salience(payload) -> str | None` over the
  ordered tiers `noise`/`low`/`notable`/`high`; tier rank helper +
  `meets_threshold`. Familiarity-weighted arrivals, intrinsic anomalies,
  departures→noise, at-launch cap, absent-familiarity→low (never noise);
  abstain (`None`) on unscored/malformed.

## 3. Stamp in the logger
- [x] 3.1 `event_log.py` — compute salience in `_emit` (downstream of the
  familiarity stamp), add `payload["salience"]` when non-None, before the
  observer tap + write.

## 4. Salience-gated push
- [x] 4.1 `companion/push_policy.py` — read `payload.get("salience")`, drop
  below `DITING_PUSH_MIN_SALIENCE` (default `low`); absent → no-op. Gate runs
  before the rf_stir-confidence + silence-window gates.

## 5. Wire safety
- [x] 5.1 `companion/sink.py` — add `salience` to the stripped local-only field
  set so the sealed envelope stays within `companion-protocol`.

## 6. Tests
- [x] 6.1 Scorer: tier per familiarity class; anomaly tiers; close-BLE bump;
  absent-familiarity→low; departures→noise; at-launch cap; abstain on
  session_meta / malformed. (`tests/test_salience.py`)
- [x] 6.2 Logger: scored event carries `salience` in JSONL; unscored omits it.
- [x] 6.3 Push policy: noise suppressed; missing salience passes through;
  threshold env override; gate composes with silence window.
- [x] 6.4 Sink: strips `salience` (and `familiarity`) before sealing; caller
  dict untouched.

## 7. Gates
- [x] 7.1 `uv run pytest`, snapshot regression, `openspec validate --specs --strict`,
  `openspec validate add-event-salience --strict`.
