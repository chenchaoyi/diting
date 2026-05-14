## 1. Defer the heavy Bonjour stages off the event loop

- [x] 1.1 Add a module-level `_import_bonjour_poller()` helper in `src/diting/tui.py` that does `from .mdns import BonjourPoller; return BonjourPoller`. Keep at module scope (not bound) so `asyncio.to_thread` does not capture `self`.
- [x] 1.2 In `BonjourPoller.events()` (`src/diting/mdns.py`), replace the inline `self._start_browser()` call with `await asyncio.to_thread(self._start_browser)`. Leave `_start_browser` itself synchronous.

## 2. Re-route lazy-init and the consumer task through a single worker

- [x] 2.1 Add `_mdns_starting: bool = False` to `DitingApp.__init__` next to `_mdns_poller`.
- [x] 2.2 Rewrite `DitingApp._ensure_mdns_poller` so it: returns immediately if `_mdns_poller is not None` or `_mdns_starting`; sets `_mdns_starting = True`; spawns `run_worker(self._consume_mdns_events(), name="mdns-poller")`.
- [x] 2.3 Rewrite `DitingApp._consume_mdns_events` so it: awaits `asyncio.to_thread(_import_bonjour_poller)` first, instantiates the poller, assigns it to `self._mdns_poller`, clears `_mdns_starting`, then drains `poller.events()` exactly as before. On unexpected exceptions, call `poller.stop()` and reset `self._mdns_poller = None`.

## 3. Trigger the pre-warm on wifi → BLE

- [x] 3.1 In `DitingApp.action_toggle_view`, after the panel `display` toggles and before the per-view refresh, call `self._ensure_mdns_poller()` when `self._view_mode in ("ble", "mdns")`. Remove the call from inside the `else: # mdns` branch (now redundant).

## 4. Tests and gates

- [x] 4.1 Run `uv run pytest` — all existing tests SHALL still pass.
- [x] 4.2 Run `uv run python scripts/tui_snapshot.py --mode regression` — regression snapshot SHALL still pass.
- [x] 4.3 Run `openspec validate prewarm-bonjour-on-ble-switch --strict` — proposal SHALL validate.
- [x] 4.4 Run `openspec validate --specs --strict` — canonical specs SHALL still validate.

## 5. Docs

- [x] 5.1 Update `tests/TESTING.md` (and `docs/zh/TESTING.md`) with a new manual smoke entry: "Press `n` once from Wi-Fi → BLE; press `n` again BLE → mDNS within ~500 ms; the second press SHALL produce the mDNS panel without a visible pause."
