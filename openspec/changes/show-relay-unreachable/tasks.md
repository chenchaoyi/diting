# Tasks

## 1. Test plan (tests-first)
- [x] 1.1 `tests/TESTING.md` (EN) + `docs/zh/TESTING.md` — `companion-bridge`
  rows: failure-counter semantics + chip unreachable annotation.

## 2. Relay client failure counter
- [x] 2.1 `relay_client.py` — `consecutive_failures` property: a flush that
  attempts delivery and sends 0 increments; any successful send resets;
  a flush with an empty queue leaves it unchanged.

## 3. Chip annotation
- [x] 3.1 `runtime.py` — `subtitle_chip` appends `· relay unreachable` to the
  queued variants when `consecutive_failures >= 3`.
- [x] 3.2 `i18n.py` — ZH entries for the new chip strings.

## 4. Tests
- [x] 4.1 `test_companion_runtime.py` / `test_companion_sender.py` — counter
  increments on failed flush, resets on success, idle flush no-ops; chip shows
  the annotation at the threshold and drops it after recovery.

## 5. Gates
- [x] 5.1 `uv run pytest`, snapshot regression,
  `openspec validate --specs --strict`,
  `openspec validate show-relay-unreachable --strict`.
