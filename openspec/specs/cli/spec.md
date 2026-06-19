# cli Specification

## Purpose

Defines diting's command-line surface — the agent-facing subcommand
vocabulary (`status`, `scan`, `stream`, `calibrate`, `analyze`,
`companion`, `capabilities`, default-TUI; with `once`/`watch`/`monitor`
as deprecation aliases), how flags resolve (`--lang`, `--log <PATH>`,
`--config`, the shared `--duration`/`--since` grammar), the uniform
`--json` contract, and the exit-hint contract that points users at their
just-finished session log. The CLI is both the user's first contact with
the tool and the entry point an agent drives; predictable, JSON-first,
self-describing behaviour is load-bearing.
## Requirements
### Requirement: Agent-facing subcommands SHALL be `status`, `scan`, `stream`, `calibrate`, `analyze`, `companion`, `capabilities`

The CLI SHALL accept exactly these non-default subcommands, plus the default
(no-subcommand) TUI action:

- `status` — print a single Connection + permission snapshot to stdout and exit
- `scan` — print a one-shot sensor snapshot (`--wifi` / `--ble` / `--lan` /
  `--mdns`; Wi-Fi + BLE by default) to stdout and exit
- `stream` — emit a foreground, bounded canonical-JSONL event stream on stdout
  (`--sensors` selects the engine's sensor set; `--duration` optional; runs
  until Ctrl+C / SIGTERM when unbounded)
- `calibrate` — record an empty-room σ baseline (default 300 s)
- `analyze [PATH]` — post-process a JSONL log file into a report
- `companion` — pairing actions (semantics owned by the `companion-bridge`
  capability)
- `capabilities` — emit a machine-readable manifest of the CLI surface

Adding or removing a canonical subcommand MUST file an ADDED / REMOVED
Requirement on this capability. The headless sensor set driven by `scan` /
`stream` is governed by the `headless-capture` capability.

#### Scenario: Each subcommand prints its primary output
- **WHEN** the user runs `diting status`
- **THEN** one Connection snapshot is printed and the process exits 0

#### Scenario: Unknown subcommand is a usage error
- **WHEN** the user runs `diting frobnicate`
- **THEN** stderr names the unknown subcommand and the process exits 2

### Requirement: The deprecated verbs `once`, `watch`, `monitor` SHALL forward to their canonical replacements

The CLI SHALL keep `once`, `watch`, and `monitor` registered as deprecation
aliases for at least one release:

- `once` → `status`
- `watch` → `stream`
- `monitor` → `stream`

Invoking an alias SHALL run the canonical handler unchanged AND print exactly one
deprecation line to **stderr** of the form `diting: 'once' is deprecated; use
'status'`. The notice SHALL go to stderr even under `--json` so that stdout stays
pure JSON. The `capabilities` manifest SHALL list each alias and its canonical
target under a `deprecated_aliases` map.

#### Scenario: Old verb still works with a notice
- **WHEN** the user runs `diting once --json`
- **THEN** stdout carries the same JSON object as `diting status --json`
- **AND** stderr carries one `diting: 'once' is deprecated; use 'status'` line
- **AND** the process exits 0

#### Scenario: Alias notice never pollutes JSON stdout
- **WHEN** the user runs `diting monitor --json | jq .`
- **THEN** jq parses every stdout line; the deprecation notice appears only on stderr

### Requirement: `status` SHALL print a single Connection + permission snapshot

`status` (the renamed `once`) SHALL print one Connection snapshot and exit. With
`--json` it SHALL print exactly one JSON object carrying the connection snapshot,
permission state, and backend name. When the host is not associated to any
network, `status` SHALL still print a well-formed (dis-associated) snapshot and
exit with code 1 per the exit-code convention.

#### Scenario: Associated host
- **WHEN** the user runs `diting status --json` while connected
- **THEN** stdout is one JSON object with the connection, permission state, and backend; exit 0

#### Scenario: Not associated
- **WHEN** the user runs `diting status` while not on any Wi-Fi
- **THEN** a dis-associated snapshot is printed and the process exits 1

### Requirement: `scan` SHALL print a one-shot sensor snapshot

`scan` SHALL collect a single snapshot from the selected sensors and exit. Flags
`--wifi`, `--ble`, `--lan`, and `--mdns` select sensors; with none, `--wifi` and
`--ble` run (the always-available pair). `--duration D` bounds the collection
window for the streaming sensors (BLE / LAN / mDNS; default a few seconds). With
`--json`, stdout SHALL be one JSON object keyed by sensor (`wifi`, `ble`, `lan`,
`mdns` — only the requested keys present), each value a list of results; without
`--json`, a human table per sensor. Wi-Fi results come from the helper scan; BLE
results are decoded via the registered decoders; LAN and mDNS results are the
latest snapshot from a brief poller sweep. A sensor that is unavailable (e.g.
helper missing, permission denied, no network) SHALL surface a structured error
for that sensor without aborting the others. Exit follows the convention: `0` if
any selected sensor returned data, `1` if none did, `2` on usage error.

#### Scenario: Combined Wi-Fi + BLE snapshot
- **WHEN** the user runs `diting scan --json`
- **THEN** stdout is one JSON object with a `wifi` array and a `ble` array; exit 0

#### Scenario: Single sensor
- **WHEN** the user runs `diting scan --wifi --json`
- **THEN** stdout carries only the `wifi` array

#### Scenario: LAN snapshot
- **WHEN** the user runs `diting scan --lan --json`
- **THEN** stdout is one JSON object whose `lan` value is a list of discovered hosts (or a structured `{"error",...}` when LAN discovery cannot run)

#### Scenario: mDNS snapshot
- **WHEN** the user runs `diting scan --mdns --json`
- **THEN** stdout is one JSON object whose `mdns` value is a list of discovered Bonjour services

#### Scenario: One sensor unavailable
- **WHEN** the user runs `diting scan --json` with Bluetooth permission denied
- **THEN** the `wifi` array is present and the `ble` value is a structured `{"error",...}`; exit follows the convention (0 if any sensor succeeded)

### Requirement: `stream` SHALL emit canonical JSONL on stdout with no other output

`stream` (subsuming the headless role of `monitor`) SHALL produce ONLY the
canonical event-log JSONL stream on stdout — the same schema `analyze` consumes —
with no banner, progress, or decorative text. All status / error messages SHALL
go to stderr. `--duration D` SHALL bound the run; when omitted, the stream runs
until Ctrl+C or SIGTERM. SIGTERM SHALL flush the final event and exit cleanly.

`stream` SHALL accept `--sensors a,b,…` to select which sensors the underlying
capture engine drives, from `wifi`, `latency`, `rf`, `ble`, `lan`, `mdns`, plus
`all` (every available sensor). The default SHALL be `wifi,latency,rf` — the
historical headless set — so an unflagged `stream` is behaviourally unchanged and
never starts BLE scanning or LAN active-probing unasked. An unknown sensor token
SHALL be a usage error (exit 2) naming the bad token. When `ble`, `lan`, or
`mdns` are selected, `stream` SHALL emit their canonical device-discovery events
(BLE seen/left, LAN host seen/left/dhcp-rotation, Bonjour service seen/left) on
the same stdout JSONL stream, and the `session_meta.monitors` manifest SHALL
report the sensors actually wired (not a hard-coded subset).

#### Scenario: Pipe to jq
- **WHEN** the user runs `diting stream | jq 'select(.type=="roam")'`
- **THEN** jq receives only valid JSON lines; nothing breaks the pipeline

#### Scenario: Bounded run
- **WHEN** the user runs `diting stream --duration 10s`
- **THEN** the stream emits canonical JSONL for ~10 s, flushes, and exits 0

#### Scenario: Default sensor set is unchanged
- **WHEN** the user runs `diting stream` with no `--sensors`
- **THEN** the engine drives only Wi-Fi + latency + RF stir, and `session_meta.monitors` reports `ble` and `lan` inactive

#### Scenario: Full sensor set
- **WHEN** the user runs `diting stream --sensors all --duration 30s`
- **THEN** the stream additionally emits BLE / LAN / Bonjour device-discovery events as they occur, and `session_meta.monitors` reports the active sensors

#### Scenario: Unknown sensor token
- **WHEN** the user runs `diting stream --sensors wifi,sonar`
- **THEN** stderr names the unknown `sonar` token and the process exits 2

#### Scenario: Pipe to head closes cleanly
- **WHEN** the user runs `diting stream | head -n 10`
- **THEN** the stream exits cleanly via SIGPIPE after head closes; no zombie process

### Requirement: `capabilities` SHALL emit a machine-readable manifest of the CLI surface

`diting capabilities` SHALL emit a self-describing manifest built from the same
declarative command table that drives parsing and `--help`, so the manifest can
never drift from actual behaviour. With `--json` it SHALL print one JSON object
with a top-level integer `schema_version` (starting at `1`), a `commands` array
(each entry: `name`, `summary`, `flags` as `{name,type,default,repeatable}`,
`output` one of `json-object|json-lines|text|tui`, and `exit_codes`), a
`deprecated_aliases` map, and the global exit-code convention. Without `--json`
it SHALL pretty-print the same information. Every dispatchable canonical verb
SHALL appear in `commands`, and every entry in `commands` SHALL be dispatchable.

#### Scenario: Agent discovers the surface
- **WHEN** an agent runs `diting capabilities --json`
- **THEN** stdout is one JSON object with `schema_version`, a `commands` array covering every canonical verb, and a `deprecated_aliases` map; `jq .` parses cleanly

#### Scenario: Manifest matches dispatch
- **WHEN** the manifest is compared against the dispatcher's known subcommands
- **THEN** the set of canonical `commands[].name` equals the set of dispatchable canonical verbs (no orphans either way)

### Requirement: `--duration` and `--since` SHALL share a uniform grammar across commands

Commands that bound a time window SHALL accept a uniform grammar: `--duration D`
on `scan`/`stream` and `--since D` on `analyze`, where `D` is `<int>` seconds or
`<int>` suffixed with `s`/`m`/`h` (e.g. `30s`, `5m`, `2h`). An unparseable value
SHALL be a usage error (exit 2) with a one-line stderr message naming the flag.
`--since` SHALL reuse the existing `analyze` duration grammar so the two are
identical.

#### Scenario: Suffix forms
- **WHEN** the user runs `diting stream --duration 5m`
- **THEN** the stream is bounded to 300 s

#### Scenario: Bad duration
- **WHEN** the user runs `diting scan --duration soon`
- **THEN** stderr names the bad `--duration` value and the process exits 2

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

### Requirement: The CLI SHALL never surface an uncaught traceback
`main()` SHALL wrap subcommand dispatch so that no unexpected exception reaches
the interpreter's default handler. `SystemExit` SHALL propagate unchanged (so
deliberate usage / runtime exit codes are preserved) and `KeyboardInterrupt`
SHALL exit cleanly. Any other exception SHALL be reported as a single
`diting: <message>` line on stderr and SHALL exit with code 1 — never a stack
trace. Setting `DITING_DEBUG=1` SHALL re-raise so developers still get the full
traceback.

#### Scenario: An unexpected runtime error is a clean message
- **WHEN** a subcommand hits an uncaught exception (e.g. a filesystem error)
- **THEN** the process prints one `diting: …` line to stderr and exits 1, with no Python traceback

#### Scenario: Debug mode restores the traceback
- **WHEN** the same error occurs with `DITING_DEBUG=1` set
- **THEN** the full traceback is printed (for development)

#### Scenario: Intentional usage exit is unaffected
- **WHEN** a subcommand calls `sys.exit(2)` for a usage error
- **THEN** the process exits 2 (the guard does not rewrite deliberate exits)

### Requirement: `analyze --for-llm` SHALL take its output directory via `--out-dir`, not a greedy positional
`--for-llm` SHALL be a boolean flag. The bundle output directory SHALL be given
by `-o` / `--out-dir DIR` (with `--for-llm=DIR` accepted for back-compat); a
bare `--for-llm` followed by the input log SHALL NOT consume the log as the
output directory. When no output directory is given, the bundle SHALL default
to `diting-llm-<timestamp>/`. If the resolved output directory already exists
as a non-directory file, the CLI SHALL emit a usage error and exit 2 rather
than crash.

#### Scenario: The reported crash no longer happens
- **WHEN** the user runs `diting analyze --for-llm <log.jsonl>`
- **THEN** `<log.jsonl>` is treated as the input, the bundle is written to the default `diting-llm-<timestamp>/`, and the process does not crash

#### Scenario: Out-dir given explicitly
- **WHEN** the user runs `diting analyze <log.jsonl> --for-llm -o /tmp/bundle`
- **THEN** the bundle is written under `/tmp/bundle`

#### Scenario: Out-dir collides with a file
- **WHEN** the resolved output directory path already exists as a regular file
- **THEN** the CLI prints a usage error and exits 2, not a traceback

### Requirement: The CLI SHALL document subcommand help and a stable exit-code convention

Each subcommand SHALL accept `--help` / `-h` and print its own usage with at
least one EXAMPLES entry and a note of its automation surface (`--json` where
applicable). The per-subcommand help text SHALL be generated from the same
declarative command table that backs `capabilities`, so help and manifest cannot
drift. The CLI SHALL follow a documented exit-code convention: `0` success, `1`
runtime error (including `status` when not associated), `2` usage error (unknown
flag / bad argument / unknown subcommand). The top-level `diting --help` SHALL
state this convention and point at `diting capabilities` for the machine-readable
surface.

#### Scenario: Per-subcommand help
- **WHEN** the user runs `diting analyze --help`
- **THEN** analyze-specific usage, flags, an example, and the `--json` note are printed and the process exits 0

#### Scenario: Exit codes are consistent
- **WHEN** an unknown flag is passed to a subcommand
- **THEN** the process exits 2; a successful run exits 0; an uncaught runtime error exits 1

#### Scenario: Top-level help points at capabilities
- **WHEN** the user runs `diting --help`
- **THEN** the output states the exit-code convention and references `diting capabilities` for the machine-readable command surface

### Requirement: All read commands SHALL support `--json`

`status`, `scan`, `stream`, `analyze`, and `capabilities` SHALL each accept
`--json`. Under `--json`, `status`/`scan`/`analyze`/`capabilities` SHALL print
exactly one JSON document to stdout and `stream` SHALL print newline-delimited
JSON (one object per event). stdout SHALL carry ONLY the JSON — every banner,
hint, deprecation notice, and human prose SHALL go to stderr — and any error
SHALL be emitted as a JSON object (`{"error": <message>, "code": <int>}`) on
stderr with the matching exit code. JSON keys and values SHALL be locale-stable
English regardless of `--lang`. All five commands SHALL share one JSON-output
implementation so purity and error semantics are identical across them.

#### Scenario: analyze emits one parseable JSON document
- **WHEN** the user runs `diting analyze <log> --json`
- **THEN** stdout is a single JSON object carrying the report's counts, timeline, aggregates, and insights, and `stdout | jq .` parses cleanly

#### Scenario: status emits a connection snapshot
- **WHEN** the user runs `diting status --json`
- **THEN** stdout is one JSON object with the connection snapshot, permission state, and backend

#### Scenario: stream emits a JSON line-stream
- **WHEN** the user runs `diting stream --json`
- **THEN** each event is one JSON object on its own line, tailable by an agent

#### Scenario: JSON mode keeps stdout pure
- **WHEN** any `--json` command also has chrome to show (scene banner, permission hint, deprecation notice)
- **THEN** that chrome is written to stderr and stdout stays valid JSON

#### Scenario: Errors are JSON under --json
- **WHEN** a `--json` run fails (bad input, runtime error)
- **THEN** the failure is a JSON object on stderr with an `error` message and a numeric `code`, and the exit code follows the documented convention

### Requirement: `--notify` SHALL be valid on both the default TUI subcommand and `stream`

The `--notify` flag SHALL be parseable on both `diting` (default TUI subcommand)
and `diting stream`. The flag is a boolean toggle (no argument). When set, the
running process SHALL raise macOS Notification Centre alerts for the anomaly
event types per the `anomaly-watchdog` capability spec. When unset, no
`osascript` invocations SHALL occur and the rest of each subcommand's behaviour
SHALL remain unchanged. Because `monitor` forwards to `stream`, `diting monitor
--notify` SHALL continue to work via the alias.

Watchdog SEMANTICS — severity gate, silence window, env-var configuration,
notification body composition — live in the `anomaly-watchdog` capability, not in
`cli`. This Requirement is only about the flag being recognised at the two entry
points.

#### Scenario: TUI user enables notifications
- **WHEN** the user runs `diting --notify` (default subcommand)
- **THEN** the TUI launches as normal and additionally raises OS notifications when anomaly events fire (subject to the watchdog severity gate + silence window)

#### Scenario: headless watchdog
- **WHEN** the user runs `diting stream --notify`
- **THEN** the headless stream emits JSONL events AND raises OS notifications (same semantics as the TUI path)

#### Scenario: alias keeps working
- **WHEN** the user runs `diting monitor --notify`
- **THEN** the alias forwards to `stream`, the deprecation notice prints to stderr, and notifications fire as for `diting stream --notify`

#### Scenario: headless without `--notify`
- **WHEN** the user runs `diting stream` (no `--notify`)
- **THEN** the headless stream emits JSONL events with NO `osascript` invocations

