## ADDED Requirements

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
