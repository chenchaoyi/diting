## Why

The headless stream (`diting stream`, the renamed `monitor`) only observes
Wi-Fi + latency + RF stir — it is blind to BLE, LAN, and mDNS/Bonjour, which the
TUI sees in full. Its `session_meta` `monitors` manifest even hard-codes
`ble=false, lan=false`. An agent doing a long watch therefore gets a strictly
poorer capture than a human at the dashboard, and `scan` can only snapshot Wi-Fi
and BLE. The TUI and the stream each hand-assemble their pollers, so the wiring
is duplicated and drifts. This change introduces a single headless
`CaptureEngine` that assembles the full sensor set below the UI, so a headless
capture sees everything the TUI sees and the manifest tells the truth.

## What Changes

- Add a headless `CaptureEngine` (`src/diting/capture.py`) that assembles and
  drives the full sensor set — Wi-Fi, latency, RF/environment, BLE, LAN,
  mDNS/Bonjour — and emits the **same** canonical event-log JSONL the TUI does
  (the device-discovery `emit_*` calls that are TUI-only today: BLE seen/left,
  Bonjour service seen/left, LAN host seen/left/dhcp-rotation, and
  `network_change`). Each poller already self-diffs via `drain_transitions()`;
  the engine runs thin emit loops, with no Textual / widget coupling.
- `diting stream` delegates poller assembly to the engine and gains
  `--sensors a,b,…` to select which sensors run (`wifi`, `latency`, `rf`, `ble`,
  `lan`, `mdns`, plus `all`). Default stays `wifi,latency,rf` so an unflagged
  `stream` is unchanged; opting into `ble`/`lan`/`mdns` requires asking for them.
- `diting scan` gains `--lan` and `--mdns` one-shot snapshots (a brief poller
  sweep → first snapshot), alongside the existing `--wifi`/`--ble`.
- `session_meta.monitors` reflects what the engine **actually** wired (correct
  `ble`/`lan`/`latency`/`rf_stir` flags + gate/interval), replacing the
  hard-coded `ble=false, lan=false`.
- A sensor that can't start (helper missing, permission denied, scene gates LAN
  probing off) degrades gracefully: the engine logs a one-line stderr note,
  omits/flags that monitor in the manifest, and the other sensors keep running.
- The full-sensor stream honours the same scene-derived gates the TUI does:
  the BLE presence gate, LAN active-probe, and UPnP-fetch values are resolved
  and threaded into the engine (today only `scene_source` reaches `stream`). The
  Bonjour poller is constructed before LAN and shared into it so LAN keeps its
  Bonjour-name enrichment.

Out of scope: the TUI keeps its own poller wiring this change (converging it onto
the engine is a larger, riskier refactor deferred to a follow-up); diting-managed
background sessions are the next change (`capture-sessions`).

## Capabilities

### New Capabilities
- `headless-capture`: the headless capture engine's behavioural contract — which
  sensors it assembles, that its JSONL is byte-compatible with the TUI/`--log`
  schema, that `session_meta.monitors` is accurate, graceful per-sensor
  degradation, and bounded teardown.

### Modified Capabilities
- `cli`: `stream` gains `--sensors`; `scan` gains `--lan` / `--mdns` sensors;
  the `capabilities` manifest reflects the new flags.

## Impact

- New `src/diting/capture.py` — `CaptureEngine` (construct → drive → drain →
  emit, teardown). Reuses `WiFiPoller`, `BLEPoller`, `BonjourPoller`,
  `LANInventoryPoller`, `LatencyPoller`, `EnvironmentMonitor`, `EventLogger`.
- `src/diting/cli.py` — `_run_stream` delegates to `CaptureEngine` and parses
  `--sensors`; `_run_scan` gains `--lan`/`--mdns`; thread BLE gate / LAN probe /
  UPnP-fetch into `_run_stream` (as `_run_tui` already receives them).
- `tests/` — new `tests/test_capture.py` (engine assembly, per-sensor emit
  routing with fake pollers, manifest accuracy, graceful degradation, teardown);
  extend `tests/test_cli.py` (`--sensors` parsing, `scan --lan/--mdns`). Update
  `tests/TESTING.md` (EN + ZH) first.
- `docs/agents.md` + `docs/zh/agents.md` — document `--sensors` and the
  now-full-sensor capture; README command tables refreshed.
- No helper schema bump; no change to the JSONL event schema itself (only which
  events a headless run emits). The `event-log` emit surface is reused as-is.
