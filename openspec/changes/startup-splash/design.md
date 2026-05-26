## Context

Current `_ensure_helper_ready` (`src/diting/cli.py:1256`) runs three synchronous probes in sequence:

1. `_helper.has_ble_scan_subcommand(binary)` — `binary --help` subprocess, 5 s timeout, typical ~50 ms.
2. `_helper.has_permission(binary)` — `binary scan` subprocess, 12 s timeout, typical 3-8 s (full CoreWLAN scan, with the LaunchServices re-spawn dance documented in the macos26 memory).
3. `_helper.has_bluetooth_permission(binary)` — `binary bluetooth-status` subprocess, 8 s timeout, typical 2-3 s.

Each probe is a `subprocess.run(...)` blocking call on the main thread. While they run, stdout is silent — the user sees a frozen terminal. The TUI alt-screen only enters after all three return.

The pixel-art mark canonical to the project lives at `docs/design/diting-design/assets/logo-mark.svg` and is already rendered in the running TUI header as the literal half-block string `_LOGO_MARK_ART` (`tui.py:6181`):

```
  █
█▀██████▄
▀██▀▀▀▀██
```

Three rows × nine columns of Unicode half-block characters (`▀▄█`), styled brand-orange (`#fea62b`) on dark background. The terminal compatibility envelope of this art is already the project's baseline — anything that can run diting can render the splash.

## Goals / Non-Goals

**Goals:**
- Make the existing 6-15 s startup wait *legible*: user can see the program is alive, what it's doing, and which step is in flight.
- Reuse the canonical brand mark; do not redesign or substitute it.
- Micro-motion that reads as "alive" without distracting; preserve silhouette frame-to-frame.
- Safe across the terminal environments diting already runs in (interactive TTY, narrow pane, piped non-TTY, dumb terminal).

**Non-Goals:**
- Reducing wall-clock startup latency. That belongs in a separate change covering TCC caching and probe parallelization.
- Adding any TUI panel or alt-screen state — splash lives entirely BEFORE alt-screen.
- Replacing or "upgrading" the brand mark.
- Showing real-time animation inside the alt-screen post-mount.
- Internationalising the beast art. Frame data is purely visual.

## Decisions

### Rich `Live` rather than rolling our own terminal-control

`rich.live.Live` is already a transitive dependency via Textual. It handles:

- TTY detection (auto-disables on non-TTY).
- Refresh throttling (caps at 4 Hz by default; we set 4 Hz explicitly).
- Cursor save/restore, terminal width detection.
- Clean teardown via context-manager exit.

Alternatives considered: hand-rolled ANSI cursor moves + `\r` clear-line loop. Rejected — Rich's `Live` is more conservative across SSH-over-bad-link and terminals that mishandle `\r` overwriting, and we're already paying the Rich import cost (the TUI uses Rich extensively for panel rendering).

### Frame data shape

Frames are simple multi-line strings stored as a tuple of constants in `src/diting/splash.py`. Each frame:

- Same row count (3) as the canonical mark.
- Same column count (9) as the canonical mark.
- Same brand-orange palette (single colour, single style — no per-cell colouring).
- Differs from `_LOGO_MARK_ART` by ≤ 2 cells. The variations are *micro-motion only*:
  - **Ear twitch frame**: the lone top cell (`  █      `) shifts one column right (`   █     `). Returns to canonical on the next frame.
  - **Eye blink frame**: a single inner cell flips from `█` to ` ` for one frame. Re-fills on the next frame.

Three frames total (canonical + ear-twitch + eye-blink) cycled at 4 Hz means each frame holds for 250 ms — fast enough to read as alive, slow enough that the eye registers the micro-motion as intentional rather than glitch. The exact frame data is authored in the implementation pass, not pinned here, so the design phase doesn't lock in pixel art ahead of visual review. The spec scenarios pin the *invariants* (same dimensions, same colour, ≤ 2 cells different) rather than the specific deltas.

### Status-line model

Below the beast, a three-line status block:

```
[✓] helper located
[..] checking Location Services
[ ] checking Bluetooth
```

States and their renderings:

- `[ ]` — pending; never run; dim style.
- `[..]` — in flight; current step; bright style with the dots cycling (`[..]` → `[.]` → `[..]`) on the splash's own 4 Hz tick. Same cycle as the beast micro-motion so the redraw is one Rich update per tick.
- `[✓]` — completed successfully; bright green.
- `[✗]` — completed with failure (probe returned falsy or raised); bright red.

The list of steps is fixed in `_ensure_helper_ready`'s call to `run_with_splash`. Each step is a `(label_i18n_key, callable)` pair; the callable returns a truthy value on success. Exceptions from a callable are caught, mark the step `[✗]`, and re-raised after teardown so existing error paths (the `note: diting-tianer not found…` prose) continue to fire downstream.

### Fallback ladder

| Tier | Environment | Render |
|---|---|---|
| A | TTY stdout AND `cols >= 30` | Beast + cycling frames + status lines via Rich `Live` |
| B | TTY stdout AND `cols < 30` | One static frame + status lines updated via `\r`; no Live |
| C | non-TTY (pipes, `force_interactive=False`, dumb term) | Single plain line `"diting starting..."`; no Live, no cursor games |

Detection: `console.is_terminal` for A/B vs C; `console.size.width` for A vs B. The 30-column threshold is comfortable for the 9-wide beast + two spaces of padding + status-line text; below that the beast would clip the status text.

Tier C also fires when stdout is captured by the test harness — tests assert against Tier C output by default.

### Splash hosts `_ensure_helper_ready`, not the other way around

The current `_ensure_helper_ready` is a single function returning the resolved binary path. The shape after this change:

1. Build the `steps` list: `[(i18n("helper located"), lambda: find_then_validate()), (i18n("checking Location Services"), lambda: has_permission(b)), (i18n("checking Bluetooth"), lambda: has_bluetooth_permission(b))]`.
2. Call `splash.run_with_splash(steps)`. The coordinator drives Rich Live (or its fallback), invokes each callable in turn, ticks the UI.
3. Coordinator returns a `list[bool]` (or raises if a callable raised).
4. `_ensure_helper_ready` reads the result list and runs the existing "permission missing → `open` the bundle" path with the splash already torn down. The existing instructional `print` calls work unchanged.

The probe callables themselves are unchanged. The splash module never touches `_helper.py`.

### Why no animation inside the alt-screen too

Once Textual takes over, polling threads and panel renders fight for the same `Live`-like coordinator. Rich `Live` and Textual coexist poorly. Splash lives strictly BEFORE alt-screen, tears down cleanly before `DitingApp.run()` is called. Any "permission pending" badge in the running TUI would belong in a separate change covering post-mount permission rechecks.

## Risks / Trade-offs

[Risk] **Splash hides the existing `print()` calls in `_ensure_helper_ready`** that fire when a helper isn't found / is stale / lacks the BLE subcommand. → Mitigation: those calls run BEFORE the splash starts. Build order in `_ensure_helper_ready` is: helper-locate prints + return-None early exits stay in front of the splash; the splash only wraps the two TCC probes (Location, Bluetooth). The `has_ble_scan_subcommand` probe goes inside the splash as the first step because it's cheap and provides confidence that the splash is alive.

[Risk] **Slow SSH links may see splash flicker** as Rich tries to redraw faster than the bandwidth allows. → Mitigation: Rich's `Live` already throttles to terminal capability; we set `refresh_per_second=4`, well within SSH-friendly territory. If the terminal absorbs <1 frame/sec, the splash visibly slows but never tears.

[Risk] **The micro-motion could read as a rendering glitch rather than intentional**. → Mitigation: the cycle pattern is deliberate — beast holds canonical pose for 500 ms, ticks once, returns. Reviewer-pass during implementation; if it reads as glitchy in real terminals, fall back to static beast + dot-cycle status only (the `[..]` animation alone reads "alive" without touching the mark).

[Risk] **Tests over-pin the frame data and break on art tweaks**. → Mitigation: tests assert on dimensions, palette, and silhouette stability, NOT on per-cell content of any specific frame. The pixel data is allowed to evolve during the implementation pass.

[Risk] **First-run TCC prompt flows interact strangely with the splash** (when Location Services or Bluetooth permission is missing, the existing code `open`s the helper bundle and polls every 2 s until the grant lands). → Mitigation: splash tears down via context-manager exit before the `open` + poll loop begins. The user sees the splash run, see the missing permission marked `[✗]`, then sees the existing instructional prose + the GUI prompt. The poll loop runs without the splash (it can take minutes — animated splash would be inappropriate).

## Migration Plan

No migration. The splash is purely additive; existing CLI invocations behave identically other than the visible startup output. No env var to opt out is needed for v1.7.x — if user reports surface a real terminal that mishandles even Tier C, an env var (`DITING_NO_SPLASH=1`) can land as a follow-up.

## Open Questions

- Should the splash also show the resolved scene (`[home]` chip) once `_resolve_scene_at_startup` has run? **Defer**: scene resolution runs BEFORE `_ensure_helper_ready` and is fast; the current banner emits via `_emit_scene_banner` to stderr already. Don't reroute through the splash in this change.
- Frame count — 2 or 3? **Defer to implementation**: author both and pick the one that reads better in the terminal.
- Do we want a `--no-splash` flag? **Defer**: not landing one in this change. Tier C fallback already covers the "this terminal can't handle it" case; an explicit opt-out can come later if needed.
