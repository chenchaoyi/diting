## Context

Every diting poller self-diffs internally and exposes `drain_transitions()` —
the TUI consumer loops are thin (iterate `events()`, drain, isinstance-route to
`EventLogger.emit_*`, refresh a panel). `DitingApp` hand-assembles all pollers in
`on_mount` (`tui.py:7281-7334`) and runs five `_consume_*` workers; `_run_stream`
(`cli.py`) hand-assembles a Wi-Fi-only subset. There is no shared assembly today.
The device-discovery emitters (`emit_ble_device_seen/left`,
`emit_bonjour_service_seen/left`, `emit_lan_host_seen/left/dhcp_rotation`) and
`emit_network_change` are only ever called from the TUI.

## Goals / Non-Goals

**Goals:**
- One headless `CaptureEngine` that drives Wi-Fi + latency + RF + BLE + LAN +
  mDNS and emits the same canonical JSONL the TUI does, with no UI coupling.
- `stream --sensors` to select sensors; accurate `session_meta.monitors`;
  graceful per-sensor degradation; bounded, snappy teardown.
- `scan --lan/--mdns` one-shot snapshots.

**Non-Goals:**
- Refactoring the TUI onto the engine (deferred — high-risk, the TUI consumers
  also drive widgets/rings the engine doesn't have).
- Background session management (`capture-sessions`, the next change).
- Any change to the JSONL event schema, helper schema, or decoder layer.
- New cross-sensor analysis — the engine only emits; analysis stays in `analyze`.

## Decisions

### D1 — `CaptureEngine` owns assembly + emit loops, not the UI bits
New `src/diting/capture.py`. `CaptureEngine(backend, inv, *, logger, sensors,
scene_source, ble_helper_path, ble_presence_gate_s, lan_active_probe,
lan_upnp_fetch, scan_interval, gateway_override, wan_override, notify)` exposes
`async run()` (until cancelled / SIGTERM) and is also usable for a bounded run by
the caller wrapping it in `wait_for`. It lifts the TUI's construct→drive→drain→
emit logic but drops `run_worker`, `_consumer_guard`, `query_one`, `_events_ring`,
panel refreshes — pure `asyncio.create_task` consumers that only push to the
`EventLogger`. `_run_stream` becomes a thin wrapper: resolve flags → build logger
→ `await engine.run()` (bounded by `--duration` exactly as today).

  Alternative considered: refactor the TUI to share the engine now. Rejected for
  this change — converging the live dashboard is a separate, riskier effort; the
  duplication here is small and the engine is the eventual common base.

### D2 — `--sensors` selection, conservative default
`--sensors` accepts a comma list of `wifi`, `latency`, `rf`, `ble`, `lan`,
`mdns`, plus `all` (everything available). Default = `wifi,latency,rf` — today's
`stream` behaviour, so an unflagged run is unchanged and never starts BLE
scanning or LAN active-probing without being asked. Unknown tokens are a usage
error (exit 2). `wifi` is implied whenever `latency`/`rf` are requested (they
derive from the Wi-Fi stream); requesting `lan` implies `mdns` construction
(LAN needs the Bonjour instance for enrichment) but only emits LAN events unless
`mdns` is also selected.

### D3 — Manifest tells the truth
The engine builds `session_meta.monitors` from the resolved sensor set via
`build_monitors_manifest(wifi=…, scan_interval_s=…, ble=…, ble_gate_s=…, lan=…,
latency=…, rf_stir=…)` — no more hard-coded `ble=false, lan=false`. A sensor that
fails to start is recorded as inactive (its `active=false`), so the header never
claims a monitor that isn't running.

### D4 — Graceful per-sensor degradation
Each sensor's construction is independently guarded. BLE needs a helper with the
`ble-scan` subcommand → if absent, skip BLE with a one-line stderr note and mark
`ble` inactive. LAN active-probe follows the scene/`DITING_LAN_PROBE` gate exactly
as the TUI; with probing off it still runs passive discovery. A poller raising at
runtime is logged and its task ends without taking down the others (mirrors the
TUI's per-consumer isolation). stdout JSONL is never interrupted.

### D5 — Construction order + sharing
Bonjour poller is constructed first and the same instance handed to
`LANInventoryPoller(bonjour_poller=…)` (the TUI invariant at `tui.py:8037` →
`lan.py:695`), so LAN keeps Bonjour-name enrichment. Latency is late-bound on the
first gateway and rebuilt on gateway change (the TUI behaviour the current
`_run_stream` omits); `network_change` is emitted on gateway shift.

### D6 — `scan --lan/--mdns` reuse the pollers' first snapshot
One-shot LAN/mDNS run the respective poller for `--duration`, take the latest
snapshot (`LANInventoryUpdate.hosts` / `BonjourScanUpdate.devices`), serialize,
and stop the poller. Same per-sensor structured-error contract as `--wifi`/`--ble`.

### D7 — Teardown
On cancel/exit: cancel + await all consumer tasks, `bonjour.stop()`, `lan.stop()`,
cancel companion flush, `familiarity.flush()`, `logger.close()` — the union of the
TUI `on_unmount` and the current `_run_stream` finally. The in-flight-scan teardown
latency noted in `agent-cli-foundation` is unchanged here (still gated by the
helper scan timeout); a cancellable scan is out of scope.

## Risks / Trade-offs

- [Engine duplicates TUI consumer logic → drift] → Keep the engine's emit
  routing a faithful mirror; a `test_capture.py` asserts each transition type
  maps to the right `emit_*`. Converging the TUI is tracked as follow-up.
- [Active LAN probing / BLE scanning started unexpectedly] → Conservative default
  (`wifi,latency,rf`); BLE/LAN/mDNS are opt-in via `--sensors`; LAN honours the
  existing scene / `DITING_LAN_PROBE` gate; the manifest records what ran.
- [BLE/LAN pollers spawn subprocesses that slow teardown] → Same class of
  teardown latency already accepted for `stream`; bounded by existing poller
  timeouts. Documented, not regressed.
- [Manifest schema consumers] → `monitors` is emitted today (not a spec-pinned
  field); flipping `ble`/`lan` to true is additive and matches what
  `build_monitors_manifest` already supports.

## Migration Plan

1. Land `CaptureEngine`; `_run_stream` delegates with default sensors =
   today's set → zero behaviour change for unflagged `stream`.
2. `--sensors`, `scan --lan/--mdns`, accurate manifest are additive opt-ins.
3. Follow-up change may converge the TUI onto the engine.

## Open Questions

- None blocking. Whether `--sensors all` should become the default for `stream`
  is deferred — conservative default now, revisit once `capture-sessions` lands.
