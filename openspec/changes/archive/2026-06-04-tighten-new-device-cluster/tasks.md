# Tasks

## 1. Test plan (tests-first)
- [x] 1.1 `tests/TESTING.md` (EN) + `docs/zh/TESTING.md` — `insights`
  new_device_cluster proximity-gate row.

## 2. Proximity gate
- [x] 2.1 `insights.py` — `_CLUSTER_NEAR_RSSI_DBM = -70` + `_arrival_is_near`
  gate in `observe`: BLE counts only when RSSI ≥ threshold (excludes no-RSSI);
  LAN/Bonjour always count.

## 3. Tests
- [x] 3.1 `test_insights.py` — near BLE clusters; far / no-RSSI BLE does not;
  LAN/Bonjour count without RSSI; updated the `_arrival` helper + the cooldown
  + TUI-wiring fixtures to carry a near RSSI.

## 4. Gates
- [x] 4.1 `uv run pytest`, snapshot regression, `openspec validate --specs --strict`,
  `openspec validate tighten-new-device-cluster --strict`.
