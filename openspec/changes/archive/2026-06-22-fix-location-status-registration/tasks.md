## 1. Test plan first
- [x] 1.1 `tests/TESTING.md` (EN): macos-helper row — `location-status` reads via the auth callback (no registration-lag false notDetermined); `permission.probe` runs the three probes concurrently
- [x] 1.2 ZH parity

## 2. Helper
- [x] 2.1 `runLocationStatusProbe` uses a `CLLocationManagerDelegate` callback + settle timeout; no `requestWhenInUseAuthorization`; exit codes unchanged
- [x] 2.2 Rebuild + verify by hand: exits 4 on a not-determined bundle (via callback/timeout), no prompt, no hang

## 3. Python
- [x] 3.1 `permission.probe` runs Location/Bluetooth/Notifications probes concurrently (ThreadPoolExecutor); result shape unchanged

## 4. Tests
- [x] 4.1 `tests/test_setup.py` still green (probe returns status strings; concurrency transparent)
- [x] 4.2 `uv run pytest`

## 5. Gates
- [x] 5.1 `uv run pytest`
- [x] 5.2 `uv run python scripts/tui_snapshot.py --mode regression`
- [x] 5.3 `openspec validate --specs --strict` and `openspec validate fix-location-status-registration --strict`
