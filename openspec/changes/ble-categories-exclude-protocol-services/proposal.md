## Why

The /tui-audit run on 2026-05-11 (live capture against the office
WLAN, 61 BLE devices visible) caught a real UX bug in the BLE
diagnostic strip's Categories row:

```
Categories  Device Information 20  ·  iPhone 7  ·  MS device beacon 4
            ·  Find My target 2  ·  Apple Proximity 1  ·  26 other
```

`Device Information` (GATT 0x180A) is a generic protocol service
that virtually every BLE peripheral with bonding advertises — it
is not a *device kind*. Leading the Categories row with it makes
the line answer the wrong question ("what protocol services are
broadcast?" instead of "what kinds of devices are around me?").

Same trap would show up if `Generic Access` (0x1800) or
`Generic Attribute` (0x1801) ever surfaced in advertisement
data — both are protocol plumbing, not device classes.

The fix is one filter in `service_category()` — when called with
`category_only=True` (the path the Categories diagnostic uses),
skip the three protocol-utility GATT services. The per-row
"Services" column keeps showing them because in a single device's
detail context they ARE useful information; it's only the
aggregate row where they're misleading.

## What Changes

- **`src/diting/ble.py:service_category()`** — when `category_only=True`,
  return `None` for the three known protocol-utility GATT services
  (`1800` Generic Access, `1801` Generic Attribute, `180A` Device
  Information).
- **Per-row "Services" column unaffected.** `service_category(uuid)`
  (default `category_only=False`) still returns the friendly name,
  so the BLE detail modal and the per-row services column keep
  rendering `Device Information` when the device's UUID list
  includes 0x180A.
- **Test coverage**: new pytest case under `tests/test_ble.py`
  verifying that `service_category("180A", category_only=True)`
  returns `None` and that `service_category("180A")` (default)
  still returns `"Device Information"`.
- **TESTING.md row** added under `bluetooth-scanning` so the
  spec→test mapping stays honest.
- **CHANGELOG entry** under `[Unreleased]` → `### Fixed`.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `bluetooth-scanning` — adds one ADDED Requirement formalising
  the "Categories diagnostic excludes protocol-utility services"
  rule so future regressions get caught at review time. The
  Requirement is precise: it lists the three UUIDs that count
  as protocol-utility and reaffirms that the per-row Services
  column still renders them.

## Impact

- **Files touched**: `src/diting/ble.py` (one filter), `tests/test_ble.py`
  (one new test), `tests/TESTING.md` + `docs/zh/TESTING.md` (mapping
  row), `CHANGELOG.md` + `docs/zh/CHANGELOG.md` (`### Fixed` entry).
- **Tests**: 360 existing pytest cases stay green; one new case added.
- **Snapshot regression**: untouched (the synthetic fixtures don't
  populate Device Information in the Categories context).
- **CI gates**: pytest matrix · regression · spec strict · change
  strict — all expected to pass.
- **External**: no version bump (this is patch-level fix), no
  release. Could land in a hypothetical v0.8.1 if the maintainer
  wants to tag a patch.
