## 1. Test plan first

- [x] 1.1 Update `tests/TESTING.md` (EN) — new `headless-capture` section (engine assembly per sensor set, emit-routing parity with fake pollers, manifest accuracy, graceful degradation, teardown) + `cli` rows for `stream --sensors` and `scan --lan/--mdns`
- [x] 1.2 Mirror into `docs/zh/TESTING.md` (ZH parity)

## 2. CaptureEngine

- [x] 2.1 Create `src/diting/capture.py` with `CaptureEngine` — ctor takes backend, inventory, logger, sensor set, scene_source, ble_helper_path, ble_presence_gate_s, lan_active_probe, lan_upnp_fetch, scan_interval, gateway/wan overrides, notify
- [x] 2.2 Assemble pollers for the selected sensors (Wi-Fi, EnvironmentMonitor, BLE, Bonjour-before-LAN, late-bound Latency); wire `set_observer` (companion) + `set_familiarity_store`
- [x] 2.3 Emit `session_meta` with an accurate `build_monitors_manifest(...)` from the resolved/started sensor set
- [x] 2.4 Port the thin consumer loops (Wi-Fi/roam/rf/link-sample/scan-summary, latency, BLE seen/left, LAN seen/left/dhcp, Bonjour seen/left, network_change) as bare `asyncio.create_task` consumers routing to `emit_*` — no widgets/rings
- [x] 2.5 Per-sensor construction guards + one-line stderr note on skip; runtime poller error isolated to its consumer
- [x] 2.6 `async run()` (+ bounded wrapping) and clean teardown: cancel/await consumers, stop bonjour+lan, flush companion+familiarity, close logger

## 3. CLI wiring

- [x] 3.1 `_run_stream`: parse `--sensors` (default `wifi,latency,rf`; `all`; unknown token → exit 2); thread BLE gate / LAN probe / UPnP-fetch in from `_dispatch` (as `_run_tui` receives them); delegate to `CaptureEngine`, keeping the `--duration` bound
- [x] 3.2 `_run_scan`: add `--lan` / `--mdns` sensors (brief poller sweep → latest snapshot → serialize; per-sensor structured error); update default-sensor and JSON-keying logic
- [x] 3.3 Update the `stream` and `scan` descriptors in the `_COMMANDS` table (new flags) so `--help` + `capabilities` reflect them

## 4. Tests

- [x] 4.1 `tests/test_capture.py`: engine constructs only requested sensors (fake pollers); each transition type routes to the right `emit_*`; manifest reflects active set incl. requested-but-unavailable → inactive; Bonjour-before-LAN sharing; teardown cancels tasks + closes logger
- [x] 4.2 `tests/test_capture.py`: graceful degradation — missing BLE helper skips BLE, others continue; runtime poller error isolated
- [x] 4.3 `tests/test_cli.py`: `stream --sensors` parsing (default, `all`, unknown→exit 2); `scan --lan/--mdns` JSON keying + per-sensor error; capabilities manifest carries the new flags
- [x] 4.4 `uv run pytest`

## 5. Docs + parity

- [x] 5.1 `docs/agents.md`: document `--sensors`, the now-full-sensor capture, and `scan --lan/--mdns`
- [x] 5.2 `docs/zh/agents.md`: ZH parity
- [x] 5.3 `README.md` + `docs/zh/README.md`: refresh `stream`/`scan` examples
- [x] 5.4 Any new user-facing `t()` strings get EN + ZH catalog entries

## 6. Gates

- [x] 6.1 `uv run pytest`
- [x] 6.2 `uv run python scripts/tui_snapshot.py --mode regression`
- [x] 6.3 `openspec validate --specs --strict` and `openspec validate headless-capture-engine --strict`
