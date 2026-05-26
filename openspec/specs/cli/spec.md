# cli Specification

## Purpose

Defines diting's command-line surface — the subcommand vocabulary
(`once`, `watch`, `monitor`, `calibrate`, `analyze`, default-TUI),
how flags resolve (`--lang`, `--log <PATH>`, `--config`), and the
exit-hint contract that points users at their just-finished session
log. The CLI is the user's first contact with the tool; backward-
compatible flag parsing is load-bearing.
## Requirements
### Requirement: Subcommands SHALL be `once`, `watch`, `monitor`, `calibrate`, `analyze`
The CLI SHALL accept exactly these five non-default subcommands:

- `once` — print a single Connection snapshot to stdout and exit
- `watch` — streaming colourised event log on stdout, Ctrl+C to quit
- `monitor` — headless JSONL events stream for long-runs / Home Assistant
- `calibrate` — record an empty-room σ baseline (default 300 s)
- `analyze [PATH]` — post-process a JSONL log file into a report

Adding a sixth subcommand or removing one MUST file an ADDED /
REMOVED Requirement on this capability.

#### Scenario: Each subcommand prints its primary output
- **WHEN** the user runs `diting once`
- **THEN** one Connection-line is printed and the process exits 0

### Requirement: `--lang en|zh` SHALL override env / locale resolution
The `--lang` flag SHALL be the highest-priority language source,
overriding `DITING_LANG` env var and the system locale. Invalid
values SHALL exit non-zero with a clear error message; missing
value (`--lang` without an argument) SHALL also exit non-zero.

#### Scenario: ZH user wants EN UI for one run
- **WHEN** they run `diting --lang en` on a `LANG=zh_CN` system
- **THEN** the UI renders English

#### Scenario: Typo
- **WHEN** they run `diting --lang fr`
- **THEN** the CLI prints "unsupported language: 'fr'" and exits non-zero

### Requirement: `--log [PATH]` SHALL enable JSONL logging with sensible defaults
The TUI default action SHALL accept `--log` with optional value:

- `--log /tmp/foo.jsonl` — log to that exact path
- `--log` (no value) — log to a default path under
  `diting-<YYYYMMDD-HHMMSS>.jsonl` in the current directory

The log file SHALL be created on-demand at first event; an unwritable
directory SHALL be reported via `notify` and the TUI SHALL continue
without logging rather than crash.

#### Scenario: User wants a log but doesn't care where
- **WHEN** they run `diting --log`
- **THEN** the tool creates `./diting-20260509-153012.jsonl` (or similar timestamp) and emits events into it

#### Scenario: Path under a read-only directory
- **WHEN** they run `diting --log /etc/wifi.jsonl` (no write permission)
- **THEN** the TUI shows a notification and continues running unlogged, exit code 0

### Requirement: TUI exit SHALL print a tip pointing at the just-written log
After a TUI session that wrote to `--log`, the CLI SHALL print to
stdout (NOT stderr — must be pipeable):

```
tip: summarise this session with
       diting analyze <path>
```

If `--log` was not used, the exit hint SHALL be omitted. The hint
SHALL appear AFTER any final session statistics, just before
returning from the entry point.

#### Scenario: User logged a session, quits with `q`
- **WHEN** they exit the TUI
- **THEN** the last line on stdout is the analyze tip with the file path filled in

#### Scenario: User did not pass --log
- **WHEN** they exit
- **THEN** no tip is printed; only any final-stats line

### Requirement: `--config <PATH>` SHALL accept a custom inventory file location
The `--config <PATH>` flag SHALL override the default `aps.yaml`
search path (current working directory). A missing file SHALL
silently fall back to empty inventory (per `inventory` capability) —
NOT an error.

#### Scenario: Multi-site user
- **WHEN** they run `diting --config ~/.diting/home.yaml` and tomorrow `diting --config ~/.diting/office.yaml`
- **THEN** AP names load from the appropriate file each session

### Requirement: `diting` with no subcommand SHALL launch the TUI
The default action SHALL be the interactive TUI. Users invoking
`diting` (no subcommand) SHALL get the four-panel dashboard with
no further configuration. SHALL NOT print help text first; SHALL
NOT require any flag.

#### Scenario: First-time user
- **WHEN** they run `diting`
- **THEN** the TUI starts immediately, no preamble

### Requirement: `diting monitor` SHALL emit JSONL on stdout with no other output
The monitor subcommand SHALL produce ONLY the JSONL event stream on
stdout — no banner, no progress messages, no decorative text. All
status / error messages SHALL go to stderr. SIGTERM SHALL flush the
final event and exit cleanly.

#### Scenario: Pipe to jq
- **WHEN** user runs `diting monitor | jq 'select(.type=="roam")'`
- **THEN** jq receives only valid JSON lines; nothing breaks the pipeline

#### Scenario: Pipe to head -n 10
- **WHEN** user runs `diting monitor | head -n 10`
- **THEN** the monitor exits cleanly via SIGPIPE after head closes; no zombie process

### Requirement: `--notify` SHALL be valid on both the default TUI subcommand and `monitor`
The `--notify` flag SHALL be parseable on both `diting` (default TUI subcommand) and `diting monitor`. The flag is a boolean toggle (no argument). When set, the running process SHALL raise macOS Notification Centre alerts for the three anomaly event types per the `anomaly-watchdog` capability spec. When unset, no `osascript` invocations SHALL occur and the rest of each subcommand's behaviour SHALL remain unchanged from v0.8.0.

Watchdog SEMANTICS — severity gate, silence window, env-var configuration, notification body composition — live in the `anomaly-watchdog` capability, not in `cli`. This Requirement is only about the flag being recognised at the two entry points.

#### Scenario: TUI user enables notifications
- **WHEN** the user runs `diting --notify` (default subcommand)
- **THEN** the TUI launches as normal and additionally raises OS notifications when anomaly events fire (subject to the watchdog severity gate + silence window)

#### Scenario: TUI user does not enable notifications
- **WHEN** the user runs `diting` with no flag (default subcommand)
- **THEN** the TUI launches as normal and NO `osascript` invocations occur regardless of which events fire

#### Scenario: headless watchdog
- **WHEN** the user runs `diting monitor --notify`
- **THEN** the headless monitor emits JSONL events AND raises OS notifications (same semantics as the TUI path)

#### Scenario: headless without `--notify`
- **WHEN** the user runs `diting monitor` (no `--notify`)
- **THEN** the headless monitor emits JSONL events with NO `osascript` invocations

### Requirement: `--scene SCENE` SHALL select one of the four named scenes for the session
The `--scene` flag SHALL accept exactly one of `home`, `office`, `public`, `audit`. The flag is global — valid on the default TUI subcommand, `monitor`, `calibrate`, and any future subcommand that runs pollers.

Resolution precedence is documented in the `scenes` capability and SHALL be honoured here: `--scene` (highest) > `DITING_SCENE` env var > default `home`.

Invalid values SHALL exit non-zero with a clear error listing the four accepted names. Missing value (`--scene` with no argument) SHALL exit non-zero.

The resolved scene SHALL be threaded through every subcommand that constructs a `BLEPoller`, so the poller's `presence_gate_s` default matches `scene_defaults(scene)["ble_presence_gate_s"]` unless `--ble-presence-gate D` explicitly overrides it. Override precedence: explicit `--ble-presence-gate` > scene-derived default.

#### Scenario: User in an office picks the office scene
- **WHEN** they run `diting --scene office`
- **THEN** the BLE presence gate defaults to 15 s (not the home / default 5 s)

#### Scenario: Explicit `--ble-presence-gate` overrides scene
- **WHEN** they run `diting --scene office --ble-presence-gate 5s`
- **THEN** the BLE presence gate is 5 s; the scene name is still `office` (used by session_meta and LLM context)

#### Scenario: Invalid scene name
- **WHEN** they run `diting --scene shop`
- **THEN** stderr prints "unsupported scene: 'shop'" and lists the four valid names; the process exits non-zero

#### Scenario: Missing value
- **WHEN** they run `diting --scene` (no argument)
- **THEN** stderr prints a clear error; the process exits non-zero

### Requirement: `--version` SHALL print the running version and exit 0
`diting --version` SHALL print exactly one line `diting <version>` to stdout (where `<version>` is the value of `importlib.metadata.version("diting")`) and exit with status 0. The flag SHALL be recognised at the top level only; passing it after a subcommand (`diting once --version`) SHALL be ignored or rejected by the subcommand's own argument parser.

If `importlib.metadata.version("diting")` raises `PackageNotFoundError` (e.g. an unusual install layout without a dist-info record), `--version` SHALL print `diting 0+unknown` and exit 0 — it MUST NOT crash.

#### Scenario: User asks for the version
- **WHEN** the user runs `diting --version`
- **THEN** stdout has exactly one line `diting <X.Y.Z>` matching `pyproject.toml`'s `version` field
- **AND** the process exits with status 0
- **AND** no TUI is launched, no helper is spawned, no log file is written

#### Scenario: Frozen binary reports the same version as the source build
- **WHEN** the user installs via `curl ... | bash` and runs `diting --version`
- **THEN** the output matches what `uv run diting --version` prints from a checkout at the same tag

### Requirement: `DITING_LAN_PROBE=0|1` env var SHALL override the scene's `lan_active_probe` default at process startup
The CLI SHALL read the env var `DITING_LAN_PROBE` at process startup. Accepted values:

- `1` — force active LAN probing ON regardless of the active scene's default (overrides `public`'s passive default).
- `0` — force active LAN probing OFF regardless of the active scene's default (overrides `home`/`office`/`audit` defaults).
- unset (or blank) — fall through to the scene default from `scene_defaults(scene)["lan_active_probe"]`.

Any other value (e.g. `true`, `yes`, `on`) SHALL print a one-line stderr warning and fall through as if unset. The env var SHALL be documented in `diting --help` under the global-options section alongside `DITING_LANG`, `DITING_SCENE`, `DITING_LAN_INVENTORY_WIDE`.

A companion env var `DITING_LAN_UPNP_FETCH=0|1` SHALL gate the optional HTTP fetch of UPnP LOCATION URLs. Default is `1` (fetch enabled). Setting `0` keeps M-SEARCH active but skips the follow-up HTTP GET. Same parse rules as `DITING_LAN_PROBE`.

#### Scenario: Public scene forced to probe via env
- **WHEN** `DITING_LAN_PROBE=1 diting` is invoked on a public Wi-Fi (auto-detected scene `public`)
- **THEN** the LAN poller runs NBNS + SSDP + mDNS-meta every sweep tick despite the scene's default `lan_active_probe=False`

#### Scenario: Home scene forced silent via env
- **WHEN** `DITING_LAN_PROBE=0 diting` is invoked at home
- **THEN** the LAN poller runs ICMP + ARP only; no NBNS / SSDP / mDNS-meta packets are emitted

#### Scenario: UPnP LOCATION fetch disabled via env
- **WHEN** `DITING_LAN_UPNP_FETCH=0 diting` is invoked
- **THEN** SSDP M-SEARCH still runs (when scene/env permit) and `LANHost.upnp_server` is populated, but `upnp_friendly_name` / `upnp_model` remain None (no HTTP GET fired)

#### Scenario: Invalid value warns and falls through
- **WHEN** `DITING_LAN_PROBE=yes diting` is invoked in `home` scene
- **THEN** a single stderr warning is printed; the LAN poller defaults to the scene knob (probing ON, since home defaults to active)

#### Scenario: Both env vars documented in --help
- **WHEN** the user runs `diting --help`
- **THEN** the global-options section includes a line for `DITING_LAN_PROBE` and a line for `DITING_LAN_UPNP_FETCH` with brief descriptions, in the same style as `DITING_LANG` and `DITING_SCENE`


### Requirement: The default TUI subcommand SHALL render a startup splash during the synchronous TCC-probe phase
The default `diting` subcommand SHALL host a startup splash in front of the `_ensure_helper_ready` TCC-probe phase. The splash SHALL render the canonical pixel-art beast mark with optional micro-motion animation, alongside a status-line block ticking down each probe step (`helper located`, `checking Location Services`, `checking Bluetooth`) as the underlying `_helper.has_*` callables resolve. The splash SHALL tear down cleanly before any post-probe permission-grant prompt flow runs (helper-bundle `open` + grant-polling loop) so that path retains its existing instructional prose unaltered.

The splash SHALL NOT change probe timing — wall-clock latency through `_ensure_helper_ready` is the same as before this requirement. The splash is perceived-latency only.

The splash SHALL be hosted by a new `src/diting/splash.py` module exposing `run_with_splash(steps, *, console=None)` where `steps` is an iterable of `(label, callable)` pairs. Each callable returns a truthy value on success; falsy values mark the step `[✗]`. Exceptions raised by a callable SHALL be caught for the duration of the splash render, mark the step `[✗]`, then re-raised after teardown so existing exception-driven error paths continue to fire.

The animation SHALL preserve the brand mark's silhouette and palette frame-to-frame:

- All frames SHALL have the same row count and column count as the canonical `_LOGO_MARK_ART` constant in `src/diting/tui.py`.
- All frames SHALL use the brand-orange foreground (`#fea62b`) on the surface background, with no per-cell colour variation.
- Adjacent frames SHALL differ by no more than two cells from each other (micro-motion only — ear shift, eye blink, etc.). The frame data SHALL NOT redraw or substitute the beast.

Frame cycle rate SHALL be in the range 3-4 Hz so the redraw is one Rich `Live` tick per frame; total redraw cost is negligible vs the probe wall-clock.

#### Scenario: Interactive TTY user launches `diting` with both TCC grants in place
- **WHEN** the user runs `diting` in an interactive terminal (≥ 30 columns) with Location Services and Bluetooth permissions granted to the helper bundle
- **THEN** the splash renders the beast mark + a three-line status block; status lines tick `[..]` → `[✓]` as each probe resolves; after all three resolve, the splash tears down and the Textual alt-screen takes over without leaving residual glyphs on the scroll-back

#### Scenario: Probe callable returns falsy
- **WHEN** `_helper.has_permission(binary)` returns `False` because Location Services is not granted to the helper bundle
- **THEN** the corresponding status line ticks to `[✗]`; the splash tears down; the existing `Permissions required:` instructional prose prints; the helper-bundle `open` + grant-polling loop begins (without splash)

#### Scenario: Probe callable raises
- **WHEN** `_helper.has_bluetooth_permission(binary)` raises an OS error (e.g. helper binary disappeared mid-run)
- **THEN** the splash catches the exception, marks the step `[✗]`, tears down, then re-raises so existing exception handling in the parent `_ensure_helper_ready` flow remains in effect

#### Scenario: Splash is bypassed in non-interactive environments
- **WHEN** stdout is not a TTY (e.g. user runs `diting | tee log.txt` or `diting < /dev/null`)
- **THEN** the splash SHALL detect via `console.is_terminal == False` and SHALL print a single plain line `"diting starting..."` instead of attempting Live rendering; the underlying probes run to completion unchanged

#### Scenario: Splash collapses in narrow terminals
- **WHEN** stdout is a TTY but `console.size.width < 30` (very narrow side pane)
- **THEN** the splash SHALL render one static frame of the beast plus the status-line block, updating the status lines via `\r` overwrites rather than driving Rich `Live`

#### Scenario: Probe wall-clock latency is preserved
- **WHEN** the user benchmarks startup with the splash enabled versus a synthetic environment where the splash is bypassed
- **THEN** the wall-clock time spent inside `_ensure_helper_ready` SHALL be the same in both runs to within ±50 ms (the splash render layer adds no probe-blocking work; the only added cost is Rich `Live` redraw, which is measured in microseconds per frame at 4 Hz)

#### Scenario: Splash does not leak past alt-screen entry
- **WHEN** `_ensure_helper_ready` returns and the Textual alt-screen takes over via `DitingApp(...).run()`
- **THEN** no Rich `Live` instance remains active; the terminal's pre-splash cursor position is restored; the alt-screen renders without competing for stdout writes
