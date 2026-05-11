## 1. Update test plan first (test-first discipline)

- [ ] 1.1 Add a row to the `bluetooth-scanning` spec coverage matrix in
      `tests/TESTING.md`: `BLE Categories diagnostic SHALL exclude
      protocol-utility GATT services` →
      `test_ble.py::test_service_category_category_only_excludes_protocol_services`
- [ ] 1.2 Add the matching row to `docs/zh/TESTING.md` (EN ↔ ZH parity)

## 2. Implement the filter

- [ ] 2.1 In `src/diting/ble.py`, near `service_category()`, add a
      module-level constant `_PROTOCOL_UTILITY_SERVICES = {"1800", "1801", "180A"}`
      with a one-line comment citing the 2026-05-11 /tui-audit run
      and the bluetooth-scanning Requirement
- [ ] 2.2 In `service_category()`'s `category_only` branch
      (currently at line ~601), add a `short in _PROTOCOL_UTILITY_SERVICES`
      check BEFORE returning the `gatt` hit: if matched, return `None`
- [ ] 2.3 Keep the existing `category_only` member-layer skip; the
      new check is an additional filter, not a replacement

## 3. Add the test

- [ ] 3.1 In `tests/test_ble.py`, after the existing
      `test_service_category_falls_through_to_gatt_services` case,
      add `test_service_category_category_only_excludes_protocol_services`
      that asserts:
        - `service_category("180A", category_only=True) is None`
        - `service_category("1800", category_only=True) is None`
        - `service_category("1801", category_only=True) is None`
        - `service_category("180A")` (default) still returns `"Device Information"`
        - `service_category("180D", category_only=True)` (Heart Rate)
          still returns `"Heart Rate"` — non-protocol services are
          unaffected

## 4. CHANGELOG

- [ ] 4.1 `CHANGELOG.md` `[Unreleased]` → `### Fixed`: one-line entry
      `BLE Categories diagnostic no longer counts protocol-utility
      GATT services (1800 / 1801 / 180A) as device kinds.` with the
      audit-run citation
- [ ] 4.2 `docs/zh/CHANGELOG.md` mirror

## 5. Self-test + ship

- [ ] 5.1 `uv run pytest` — 360 + 1 = 361 pass
- [ ] 5.2 `uv run python scripts/tui_snapshot.py --mode regression --check`
      — 16/16 (synthetic fixtures don't trigger this path; existing
      assertions hold)
- [ ] 5.3 `openspec validate --specs --strict` — 15/15
- [ ] 5.4 `openspec validate ble-categories-exclude-protocol-services --strict`
      — change valid
- [ ] 5.5 Commit, push, open PR

## 6. Post-merge

- [ ] 6.1 `openspec archive ble-categories-exclude-protocol-services`
      — apply the bluetooth-scanning ADDED Requirement into the
      canonical spec
