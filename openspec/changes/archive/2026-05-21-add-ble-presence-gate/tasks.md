# tasks — add-ble-presence-gate

## 1. Spec

- [x] Draft proposal, design, tasks
- [x] Spec delta in `specs/bluetooth-scanning/spec.md`

## 2. Test plan

- [x] `tests/TESTING.md` — extend the BLE-events row + new row
      for CLI-flag tests
- [x] `docs/zh/TESTING.md` — EN ↔ ZH parity

## 3. Tests

- [x] `test_poller_anonymous_advert_below_gate_emits_no_seen_no_left`
- [x] `test_poller_anonymous_advert_graduates_after_gate_elapses`
- [x] `test_poller_named_first_advert_bypasses_gate`
- [x] `test_poller_connected_peripheral_bypasses_gate`
- [x] `test_poller_presence_gate_zero_restores_no_debounce`
- [x] `test_poller_pending_identifier_graduates_when_name_appears_in_later_advert`
- [x] Existing transition tests still green (107 BLE tests pass)

## 4. CLI plumbing

- [x] `src/diting/cli.py` — `_extract_ble_presence_gate_arg`,
      `_resolve_ble_presence_gate`, thread through `_run_tui`
- [x] Help text mentions the flag + env var (EN + ZH i18n catalog)
- [x] `tests/test_cli.py` — 10 new tests covering parse / env /
      defaults / invalid input

## 5. Implementation

- [x] `src/diting/ble.py` — `BLEPoller.__init__(presence_gate_s=5.0)`,
      `_pending_seen` dict
- [x] `src/diting/ble.py` — `_detect_transitions` re-shaped with
      PENDING/PRESENT/DEPARTED state machine
- [x] `src/diting/tui.py` — `DitingApp` plumbs `ble_presence_gate_s`
      to BLEPoller

## 6. Validation

- [x] `uv run pytest` — 784 passed
- [x] `uv run python scripts/tui_snapshot.py --mode regression` — green
- [x] `openspec validate --specs --strict` — 21/21
- [x] `openspec validate add-ble-presence-gate --strict` — valid

## 7. README + CHANGELOG

- [x] `README.md` — extended the BLE bullet under "What you can do with it"
- [x] `docs/zh/README.md` — mirror EN entry
- [x] `CHANGELOG.md` — `## [Unreleased]` → `### Changed`
- [x] `docs/zh/CHANGELOG.md` — mirror EN entry

## 8. Merge + archive

- [x] PR open, reviewed, merged (#111)
- [x] `/opsx:archive add-ble-presence-gate`
