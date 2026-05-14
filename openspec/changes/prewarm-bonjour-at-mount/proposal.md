## Why

The Bonjour prewarm trigger landed in v1.0.x was "first time the
user leaves the Wi-Fi view" — i.e. the wifi → BLE step. That
window is long enough on the source-installed `uv run diting` build
(`asyncio.to_thread(import …)` actually overlaps with the BLE
view's reading time because `.py` file reads release the GIL during
`open()`).

It's not enough for the **PyInstaller-frozen binary** (the curl-
install path). PyInstaller's `PyiFrozenImporter` decompresses each
imported module from a PYZ archive inside pure-Python code that
holds the GIL the entire time. So `asyncio.to_thread` doesn't help
— the import is effectively synchronous from the event loop's
perspective. Users on the curl-installed v1.0.9 see the second `n`
press (BLE → mDNS) hang for >1.5 s while zeroconf is still being
unpacked.

## What Changes

- The Bonjour prewarm SHALL be triggered at TUI mount, not on the
  first wifi → BLE step. `App.on_mount` calls
  `_ensure_mdns_poller()` after scheduling the other pollers.
- The existing wifi → BLE call from `action_toggle_view` stays as
  a safety net (idempotent gate handles it).
- **BREAKING (spec only)**: the previous requirement "user who
  only uses Wi-Fi view never imports zeroconf" no longer holds.
  Every TUI session imports zeroconf at mount. Acceptable: the
  cost is amortised over the user's first ~5 s of reading the
  wifi view, which is dominated by their cognitive load, not the
  app's CPU.

## Capabilities

### New Capabilities
<!-- none -->

### Modified Capabilities
- `mdns-scanning`: prewarm trigger moves from "first wifi → BLE"
  to "TUI mount". Same underlying mechanism (idempotent
  `_ensure_mdns_poller` + worker), just earlier.

## Impact

- `src/diting/tui.py`: one new call (`self._ensure_mdns_poller()`)
  at the end of `App.on_mount`.
- `tests/test_tui_smoke.py`: rename / rewrite the two
  Bonjour-lazy tests to reflect mount-time prewarm; update the
  `_inject_bonjour_devices` helper to pause polling so the
  mount-time consumer task can't overwrite the injection.
- Same applies for the source build but the wifi-only-user
  optimisation it removes was always a minor savings.
