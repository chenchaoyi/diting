## 1. Test plan (test-first)

- [x] 1.1 `tests/TESTING.md` (EN) — append entries under `mdns-scanning` (active-probe scheduling, non-blocking) and `wifi-scanning` (Max-hidden-when-Tx-exceeds-it).
- [x] 1.2 `docs/zh/TESTING.md` — mirror in ZH.

## 2. mdns-scanning — active per-service re-probe

- [x] 2.1 `src/diting/mdns.py::BonjourPoller` — add `_active_probe_interval_s: float = 30.0` constructor parameter; track `_last_active_probe_at` (monotonic time); add `_kick_active_probes(now)` method that iterates `_state.keys()` and dispatches `self._loop.create_task(self._apply_callback("update", type_, name))` per entry. Call from `events()` once per snapshot tick (no-op when monotonic-now is within `_active_probe_interval_s` of the last fire).
- [x] 2.2 `tests/test_mdns.py` — `test_poller_active_probe_scheduled_per_state_entry_at_cadence`, `test_poller_active_probe_does_not_block_snapshot_yield`, `test_poller_active_probe_keeps_state_alive_through_cache_expiry`.

## 3. wifi-scanning — Connection panel hides Max when Tx > Max

- [x] 3.1 `src/diting/tui.py::ConnectionPanel._paint` (or wherever the `Tx / Max` row is built) — gate the trailing `/ <max> Mbps` segment on `not (tx_rate > max_link_speed)`. When the inversion is detected, render Tx alone.
- [x] 3.2 `tests/test_tui_helpers.py` — `test_connection_panel_hides_max_when_tx_exceeds_it`, `test_connection_panel_shows_both_when_max_ge_tx`. (Re-use `_render_connection_panel_text` / `_conn_full` factory from the existing audit-polish tests.)

## 4. CI gates

- [x] 4.1 `uv run pytest`
- [x] 4.2 `uv run python scripts/tui_snapshot.py --mode regression`
- [x] 4.3 `openspec validate --specs --strict`
- [x] 4.4 `openspec validate tui-audit-2026-05-18 --strict`
