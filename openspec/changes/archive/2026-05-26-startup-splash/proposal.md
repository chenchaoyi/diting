## Why

The visible startup wait between invoking `diting` and the TUI alt-screen appearing is 6-15 seconds in the steady-state path — entirely dominated by two synchronous TCC probes inside `_ensure_helper_ready` (`src/diting/cli.py:1256`): a real Wi-Fi `scan` to prove Location Services is granted, and a `bluetooth-status` query to prove Bluetooth is granted. During that window the user's terminal sits silent — no output at all — and the experience reads as "frozen" or "hung" rather than "running self-checks".

We are NOT cutting that latency here. The probes still happen, still block, still take the same time. What we ARE doing is making the wait *legible*: render a small animated splash with the diting brand mark and a tick-down list of which probe is currently in flight, so the user can see the program is alive, what it's doing, and roughly how many steps remain. Perceived wait drops sharply even when wall-clock wait is unchanged.

A later change can layer on TCC-result caching to drop the wall-clock wait too; that work is explicitly out of scope for this proposal.

## What Changes

- New module `src/diting/splash.py` containing:
  - 2-3 hand-authored frames of micro-motion variants of the existing `_LOGO_MARK_ART` pixel beast (`tui.py:6181`). Allowed deltas between frames: single-cell pixel shifts (ear twitch / eye blink). Silhouette, bounding box, and brand-orange palette stay 100% identical across frames per the "do not redesign the mark" rule in `CLAUDE.md`.
  - A `run_with_splash(steps, *, console=None)` coordinator that drives a `rich.live.Live` for the duration of a sequence of `(label, callable)` pairs, ticking each step from `[..]` to `[✓]` (or `[✗]`) as the callable returns. Animation runs at 3-4 Hz; total redraw cost is negligible vs the probe wall-clock.
- `src/diting/cli.py` `_ensure_helper_ready` reorganised so the three probes (`has_ble_scan_subcommand`, `has_permission`, `has_bluetooth_permission`) become `(label, callable)` steps and the splash is the host. The existing post-probe permission-grant flow (the `open` of the helper bundle when a TCC grant is missing) tears down the splash cleanly before printing its instructional text, so the missing-permission path keeps its existing prose.
- Fallback ladder, choose the highest tier the environment supports:
  - **Tier A — animated splash**: TTY stdout AND `cols >= 30`. Beast + cycling frames + status lines. Default for an interactive terminal session.
  - **Tier B — static splash**: TTY stdout but `cols < 30`. One frame, no Live, status lines update by overwriting via `\r`. Covers narrow side panes.
  - **Tier C — plain text**: non-TTY (pipes, dumb terminals, `force_interactive=False`). Single line `"diting starting..."`, no Live, no cursor games.
- EN + ZH catalog entries for three status labels: `"helper located"`, `"checking Location Services"`, `"checking Bluetooth"`.

## Capabilities

### New Capabilities

(none — splash lives inside the existing `cli` capability's startup flow.)

### Modified Capabilities

- `cli`: new requirement that the default TUI subcommand SHALL render a startup splash during the synchronous TCC-probe phase, with a defined fallback ladder for non-interactive environments.
- `i18n`: catalog parity for the three new status-line strings.

## Impact

- **Code**: new `src/diting/splash.py` (~150 lines including the frame data tables and the fallback ladder). `src/diting/cli.py` `_ensure_helper_ready` reorganised to drive the splash (~30 lines of touch). `src/diting/i18n.py` gains three keys.
- **Tests**: new `tests/test_splash.py` covering frame data shape (cells outside the silhouette stay empty), Tier A / B / C dispatch by stub-console capability, status-line tick sequence, and `[✗]` rendering when a probe callable returns falsy / raises.
- **TESTING.md** + **docs/zh/TESTING.md**: new rows under the `cli` capability table.
- **Snapshot regression**: unaffected. The splash renders BEFORE alt-screen and never overlaps with the captured `tui_snapshot.py` scenarios.
- **Dependencies**: none. `rich.live` is already a transitive dep via Textual.
- **Permissions / privacy**: none. Splash is pure stdout.
- **Probe timing**: unchanged. This change is perceived-latency only.
- **Spec deltas**: `cli`, `i18n`.

## Explicitly out of scope

- TCC-result caching (the `~/.diting/permissions-ok` sentinel idea from prior exploration). Will be a separate proposal — keeping splash isolated so the perceived-vs-actual latency wins can land independently and be verified independently.
- Probe parallelization.
- Post-mount in-TUI permission-pending state.
- Reworking the logo mark itself — micro-motion only, silhouette stays canonical.
