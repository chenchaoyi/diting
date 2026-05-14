## 1. Move the prewarm trigger

- [x] 1.1 In `src/diting/tui.py` `App.on_mount`, add `self._ensure_mdns_poller()` after the LatencyPoller worker block. Keep the existing `action_toggle_view` call as an idempotent no-op fallback.

## 2. PyInstaller version metadata (related fix that ships in same release)

- [x] 2.1 Add `--copy-metadata diting` to the PyInstaller invocation in `scripts/build_frozen.py` so `importlib.metadata.version("diting")` resolves in the frozen binary (v1.0.9 shipped with this missing, producing `diting v0+unknown` in the TUI title).
- [x] 2.2 Add a regression test in `tests/test_helper.py` asserting `scripts/build_frozen.py` still contains the `--copy-metadata diting` flag.

## 3. Tests

- [x] 3.1 Rename `test_app_constructs_bonjour_panel_lazily` → `test_bonjour_prewarms_at_mount` and assert `_mdns_starting` or `_mdns_poller` is set right after mount.
- [x] 3.2 Rewrite `test_bonjour_prewarms_on_first_wifi_to_ble_switch` → `test_bonjour_view_switch_is_idempotent_after_mount_prewarm` to assert pressing `n` after the mount-time prewarm does not replace the poller.
- [x] 3.3 Update `_inject_bonjour_devices` in `tests/test_tui_smoke.py` to set `app._paused = True` so the mount-time consumer task's first empty yield does not overwrite injected devices.

## 4. Gates

- [x] 4.1 `uv run pytest` passes.
- [x] 4.2 `uv run python scripts/tui_snapshot.py --mode regression` passes.
- [x] 4.3 `openspec validate --specs --strict` passes.
- [x] 4.4 `openspec validate prewarm-bonjour-at-mount --strict` passes.
