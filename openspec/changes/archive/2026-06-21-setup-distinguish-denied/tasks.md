## 1. Test plan first

- [x] 1.1 `tests/TESTING.md` (EN): permission-setup row — pending (`notDetermined`) is waited on, only settled denial routes to Settings; probe returns status strings
- [x] 1.2 ZH parity in `docs/zh/TESTING.md`

## 2. Probes return status

- [x] 2.1 `_helper.location_status` / `bluetooth_authorization_status` → status string from exit code (0 authorized · 3 denied · 4 not_determined · 5 restricted · else unknown); keep `*_authorized` bools delegating
- [x] 2.2 `permission.probe()` → location/bluetooth as status strings (read-only when supported, else functional bool → authorized/unknown); `is_ready` checks `== "authorized"`

## 3. setup loop + display

- [x] 3.1 `_run_setup`: drop the grace-window denial assumption; route to Settings only on `denied`/`restricted` (once each), wait on `not_determined`/`unknown`; `_setup_state_json` maps status→bool; status words handle the strings

## 4. Tests

- [x] 4.1 `tests/test_setup.py`: probe returns status strings; `is_ready` on strings; json maps to bool; denied-vs-pending routing (a fake state machine driving the decision)
- [x] 4.2 `uv run pytest`

## 5. Gates

- [x] 5.1 `uv run pytest`
- [x] 5.2 `uv run python scripts/tui_snapshot.py --mode regression`
- [x] 5.3 `openspec validate --specs --strict` and `openspec validate setup-distinguish-denied --strict`
