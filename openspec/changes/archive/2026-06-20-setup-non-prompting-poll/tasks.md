## 1. Test plan first

- [x] 1.1 Update `tests/TESTING.md` (EN) — `permission-setup` rows: read-only polling (no duplicate prompts), graceful degradation on old helper; `macos-helper` row for the two read-only probes
- [x] 1.2 Mirror into `docs/zh/TESTING.md` (ZH parity)

## 2. Helper: read-only probes

- [x] 2.1 Add `location-status` (read `CLLocationManager().authorizationStatus`, exit 0 on authorized) and `bluetooth-authorization` (read `CBManager.authorization`, exit 0 on `.allowedAlways`) to `main.swift`; disclaim hop; no prompt; list both in `--help`
- [x] 2.2 Rebuild helper (`./helper/build.sh`); verify both exit codes by hand and confirm neither surfaces a prompt

## 3. Python read-only probes + permission.probe

- [x] 3.1 `_helper.location_authorized(binary)` + `_helper.bluetooth_authorized(binary)` (run the new probes) + `has_location_status_subcommand` / `has_bluetooth_authorization_subcommand` detection (`--help` grep)
- [x] 3.2 `permission.probe()`: use the read-only probes for Location/Bluetooth when available, else fall back to the existing functional probes; Notifications unchanged

## 4. setup display

- [x] 4.1 Suppress the scene banner for the `setup` command in `_dispatch` (gate `_emit_scene_banner`); keep status output concise

## 5. Tests

- [x] 5.1 `tests/test_setup.py`: `permission.probe` prefers read-only probes when advertised; falls back when absent (patched `_helper`)
- [x] 5.2 `tests/test_helper.py` (or test_setup): new probe parsing + subcommand detection
- [x] 5.3 `tests/test_cli.py`: `setup` does not emit the scene banner
- [x] 5.4 `uv run pytest`

## 6. Gates

- [x] 6.1 `uv run pytest`
- [x] 6.2 `uv run python scripts/tui_snapshot.py --mode regression`
- [x] 6.3 `openspec validate --specs --strict` and `openspec validate setup-non-prompting-poll --strict`
