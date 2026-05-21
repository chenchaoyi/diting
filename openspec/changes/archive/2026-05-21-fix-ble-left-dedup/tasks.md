# tasks — fix-ble-left-dedup

## 1. Spec

- [x] Draft proposal, design, tasks
- [x] Spec delta in `specs/bluetooth-scanning/spec.md`
      (MODIFIED requirement + new "Repeated TTL eviction" scenario)

## 2. Test plan

- [x] Update `tests/TESTING.md` — add row under BLE for the
      new state-machine guarantee
- [x] Update `docs/zh/TESTING.md` — EN ↔ ZH parity

## 3. Tests (test-first)

- [x] `test_poller_does_not_re_emit_left_after_identifier_returns_and_evicts_again` —
      seen → TTL evicts → left → advert re-arrives → TTL evicts
      again → no second left
- [x] Existing transition tests (`test_poller_emits_left_event_on_ttl_eviction`,
      `test_poller_does_not_re_emit_seen_for_known_identifier`)
      still pass

## 4. Implementation

- [x] Add `_departed_identifiers: set[str]` in `BLEPoller.__init__`
- [x] Gate `BLEDeviceLeftEvent` emission on
      `ident not in _departed_identifiers`
- [x] Add `ident` to `_departed_identifiers` after emission

## 5. Validation

- [x] `uv run pytest`
- [x] `uv run python scripts/tui_snapshot.py --mode regression`
- [x] `openspec validate --specs --strict`
- [x] `openspec validate fix-ble-left-dedup --strict`

## 6. CHANGELOG

- [x] CHANGELOG.md — entry under `## [Unreleased]` → `### Fixed`
- [x] docs/zh/CHANGELOG.md — mirror EN entry

## 7. Merge + archive

- [x] PR open, reviewed, merged (#107)
- [x] `/opsx:archive fix-ble-left-dedup`
