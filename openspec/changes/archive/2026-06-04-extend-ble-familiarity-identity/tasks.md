# Tasks

## 1. Test plan (tests-first)
- [x] 1.1 `tests/TESTING.md` (EN) + `docs/zh/TESTING.md` — `familiarity-store`
  rows: MiBeacon service-data id (B) + vendor-group (A) key rungs.

## 2. service-data identity (B)
- [x] 2.1 `ble.py::service_data_identity()` — parse MiBeacon `FE95`, return
  `mibeacon:<mac>` when the MAC-included bit is set; abstain (None) otherwise;
  never raise.
- [x] 2.2 `events.py` — in-memory `service_data_id` on BLE seen/left events;
  populate at the four `ble.py` construction sites from `dev.service_data`.

## 3. familiarity key ladder
- [x] 3.1 `familiarity.py::familiarity_key` — add `service_data_id` + `vendor`
  params; rungs `ble:sd:<id>` (after payload) and `ble:vg:<vendor>` (last
  resort). `event_log.py` passes both for BLE seen + left.

## 4. Docs
- [x] 4.1 `docs/explainers/ble-identity.md` (EN) + `docs/zh/explainers/...` (ZH);
  link from README EN+ZH.

## 5. Tests
- [x] 5.1 `service_data_identity`: MiBeacon MAC extracted (LE reversed); abstain
  on no-MAC-bit / short / wrong-uuid / malformed. (`tests/test_ble.py`)
- [x] 5.2 `familiarity_key`: `ble:sd:` for service-data id; `ble:vg:` for
  vendor-only; precedence (payload > sd > vn > vg); anon → None; existing keys
  unchanged. (`tests/test_familiarity.py`)
- [x] 5.3 `event_log` integration: a service-data BLE seen gets `ble:sd:`
  familiarity; a vendor-only seen gets `ble:vg:`; left folds dwell under the
  same key. (`tests/test_event_log.py`)

## 6. Gates
- [x] 6.1 `uv run pytest`, snapshot regression, `openspec validate --specs --strict`,
  `openspec validate extend-ble-familiarity-identity --strict`.
