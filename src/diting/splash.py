"""Pre-alt-screen startup splash.

Renders a small animated splash with the diting brand mark and a
status-line block while `_ensure_helper_ready` (in `cli.py`) runs
its synchronous TCC probes. The splash does NOT shorten the wait;
it makes the wait *legible*.

Three render tiers, picked from the terminal environment:

- **Tier A** (interactive TTY ≥ 30 cols) — Rich `Live` driving the
  beast frames + status lines at 4 Hz.
- **Tier B** (interactive TTY < 30 cols) — one static frame, status
  lines overwritten via ``\\r``.
- **Tier C** (non-TTY: pipes, dumb terms) — a single
  ``"diting starting..."`` line; no cursor games.

See `openspec/changes/startup-splash/` for the full design + spec.
"""

from __future__ import annotations

import sys
import time
from contextlib import contextmanager
from typing import Callable, Iterator, Sequence

from rich.console import Console
from rich.live import Live
from rich.text import Text

from .i18n import t


# Canonical mark from `tui.py:_LOGO_MARK_ART`. Mirrored here (not
# imported) so this module does not pull in the heavy `tui` import
# chain just to read three lines of art. The two strings MUST stay
# byte-equal; the test suite asserts shape parity against the tui
# value, so a drift here surfaces immediately.
#
# Frames vary by ≤ 2 cells from the canonical pose to preserve the
# silhouette per the "do not redesign the mark" rule in CLAUDE.md.
# Frame 0 IS the canonical pose; frame 1 is an ear-twitch micro-
# motion (top-row cell shifts one column right); frame 2 is an
# eye-blink (one inner cell flips off for a beat).
_FRAME_CANONICAL = "  █      \n█▀██████▄\n▀██▀▀▀▀██"
_FRAME_EAR_TWITCH = "   █     \n█▀██████▄\n▀██▀▀▀▀██"
# Eye-blink modifies one inner cell on the body row; the row's
# rendered width stays at 9 (one █ → one space).
_FRAME_EYE_BLINK = "  █      \n█▀██ ███▄\n▀██▀▀▀▀██"

_FRAMES: tuple[str, ...] = (
    _FRAME_CANONICAL,
    _FRAME_EAR_TWITCH,
    _FRAME_CANONICAL,
    _FRAME_EYE_BLINK,
)

_FRAME_INTERVAL_S: float = 0.25  # 4 Hz
_NARROW_THRESHOLD_COLS: int = 30
_BRAND_ORANGE: str = "#fea62b"


Step = tuple[str, Callable[[], object]]


# ---------- public entry point ----------

def run_with_splash(
    steps: Sequence[Step],
    *,
    console: Console | None = None,
) -> list[bool]:
    """Drive ``steps`` with a startup splash; return per-step truthy results.

    Each step is a ``(label, callable)`` pair. The callable runs
    synchronously; its return value coerces to bool and lands in the
    returned list. Exceptions raised by a callable are caught for the
    duration of the splash teardown, the step renders as ``[✗]``, and
    the exception is re-raised AFTER teardown so existing error paths
    upstream continue to fire.

    Tier dispatch:

    - non-TTY  → :func:`_run_tier_c` (plain ``"diting starting..."``)
    - narrow   → :func:`_run_tier_b` (static frame + ``\\r`` updates)
    - default  → :func:`_run_tier_a` (Rich ``Live`` with cycling frames)

    A custom ``console`` is accepted so tests can stub the tier
    decision and capture output deterministically.
    """
    console = console or Console()
    if not console.is_terminal:
        return _run_tier_c(steps, console)
    if console.size.width < _NARROW_THRESHOLD_COLS:
        return _run_tier_b(steps, console)
    return _run_tier_a(steps, console)


# ---------- tier implementations ----------

def _run_tier_c(
    steps: Sequence[Step], console: Console,
) -> list[bool]:
    """Non-TTY fallback. Print one line, run callables, no rendering."""
    console.print(t("diting starting..."))
    results: list[bool] = []
    pending_exc: BaseException | None = None
    for _label, fn in steps:
        if pending_exc is not None:
            # Mirror Tier A/B semantics: once a step has raised we
            # stop invoking subsequent callables — the exception
            # will re-raise after the loop.
            results.append(False)
            continue
        try:
            results.append(bool(fn()))
        except BaseException as exc:  # noqa: BLE001 — surface after teardown
            pending_exc = exc
            results.append(False)
    if pending_exc is not None:
        raise pending_exc
    return results


def _run_tier_b(
    steps: Sequence[Step], console: Console,
) -> list[bool]:
    """Narrow TTY fallback. Static frame + ``\\r`` status overwrites."""
    # Beast prints once at the top; status block follows on a single
    # line we overwrite each step. We do NOT animate frames in this
    # tier — a 20-cell wide pane can't host a multi-line block
    # without wrapping the beast art into the next line.
    for line in _FRAME_CANONICAL.splitlines():
        text = Text(line, style=f"bold {_BRAND_ORANGE}")
        console.print(text)

    results: list[bool] = []
    pending_exc: BaseException | None = None
    statuses: list[str] = ["pending"] * len(steps)
    for i, (label, fn) in enumerate(steps):
        statuses[i] = "running"
        _render_narrow_status(console, steps, statuses)
        if pending_exc is not None:
            statuses[i] = "fail"
            results.append(False)
            continue
        try:
            ok = bool(fn())
        except BaseException as exc:  # noqa: BLE001
            pending_exc = exc
            statuses[i] = "fail"
            results.append(False)
            _render_narrow_status(console, steps, statuses)
            continue
        statuses[i] = "ok" if ok else "fail"
        results.append(ok)
        _render_narrow_status(console, steps, statuses)
    console.print()  # Finalise with a newline so subsequent stdout starts clean.
    if pending_exc is not None:
        raise pending_exc
    return results


def _render_narrow_status(
    console: Console,
    steps: Sequence[Step],
    statuses: Sequence[str],
) -> None:
    """Overwrite the same line with the current step's status."""
    # Tier B shows only the in-flight or most-recently-completed
    # step's label; a 20-col pane has no room for the full block.
    label_idx = len(statuses) - 1
    for i, status in enumerate(statuses):
        if status in ("running", "fail", "ok"):
            label_idx = i
            if status == "running":
                break
    label = steps[label_idx][0]
    glyph = _STATUS_GLYPHS[statuses[label_idx]]
    line = f"\r{glyph} {label}"
    # Trim to the terminal width so we don't wrap into a second row.
    width = console.size.width
    if len(line) > width:
        line = line[:width]
    # `Console.file.write` skips Rich's own buffering — needed so
    # the `\r` actually overwrites the previous render rather than
    # appending to it.
    console.file.write(line)
    console.file.flush()


def _run_tier_a(
    steps: Sequence[Step], console: Console,
) -> list[bool]:
    """Default tier. Rich Live with the cycling-frame beast."""
    state = _SplashState(steps)
    results: list[bool] = []
    pending_exc: BaseException | None = None

    with Live(
        state.render(),
        console=console,
        refresh_per_second=4,
        transient=True,
    ) as live:
        for i, (_label, fn) in enumerate(steps):
            state.mark_running(i)
            live.update(state.render())
            if pending_exc is not None:
                state.mark_done(i, False)
                results.append(False)
                live.update(state.render())
                continue
            try:
                ok = bool(fn())
            except BaseException as exc:  # noqa: BLE001
                pending_exc = exc
                state.mark_done(i, False)
                results.append(False)
                live.update(state.render())
                continue
            state.mark_done(i, ok)
            results.append(ok)
            live.update(state.render())
            # Brief frame tick so the user sees the transition rather
            # than the whole list resolving in a single redraw.
            time.sleep(_FRAME_INTERVAL_S)

    if pending_exc is not None:
        raise pending_exc
    return results


# ---------- internal state + glyphs ----------

_STATUS_GLYPHS: dict[str, str] = {
    "pending": "[ ]",
    "running": "[..]",
    "ok": "[✓]",
    "fail": "[✗]",
}

_STATUS_STYLES: dict[str, str] = {
    "pending": "dim",
    "running": "bold yellow",
    "ok": "bold green",
    "fail": "bold red",
}


class _SplashState:
    """Mutable render state for Tier A. Owns the frame cursor and the
    per-step status list; ``render()`` returns a renderable for Live.
    """

    def __init__(self, steps: Sequence[Step]) -> None:
        self._steps = steps
        self._statuses: list[str] = ["pending"] * len(steps)
        self._frame_index = 0
        self._start = time.monotonic()

    def mark_running(self, i: int) -> None:
        self._statuses[i] = "running"

    def mark_done(self, i: int, ok: bool) -> None:
        self._statuses[i] = "ok" if ok else "fail"

    def render(self) -> Text:
        # Advance the frame cursor based on wall-clock time so Live's
        # own refresh rate drives the animation cadence.
        elapsed = time.monotonic() - self._start
        self._frame_index = int(elapsed / _FRAME_INTERVAL_S) % len(_FRAMES)
        out = Text()
        # Beast block, brand-orange.
        beast = _FRAMES[self._frame_index]
        for line in beast.splitlines():
            out.append(line, style=f"bold {_BRAND_ORANGE}")
            out.append("\n")
        out.append("\n")
        # Status lines.
        for status, (label, _fn) in zip(self._statuses, self._steps):
            glyph = _STATUS_GLYPHS[status]
            style = _STATUS_STYLES[status]
            out.append(f"{glyph} ", style=style)
            out.append(label, style=style)
            out.append("\n")
        return out


# ---------- shape introspection (used by tests) ----------

def _frame_dimensions(frame: str) -> tuple[int, int]:
    """Return ``(rows, max_cell_width)`` for ``frame``.

    Each ``█`` / ``▀`` / ``▄`` / space cell counts as 1 — we are
    NOT using Rich's `cell_len` here because the half-block art is
    pure ASCII-width-1 glyphs and the test invariants want the raw
    grid count.
    """
    lines = frame.splitlines()
    rows = len(lines)
    width = max((len(line) for line in lines), default=0)
    return rows, width


def _cells_differ(a: str, b: str) -> int:
    """Count cells that differ between two frame strings.

    Returns a hamming distance over the union of cells (treating
    missing trailing cells in a shorter row as space). Used by the
    test that pins ≤ 2-cell deltas between adjacent frames.
    """
    a_lines = a.splitlines()
    b_lines = b.splitlines()
    rows = max(len(a_lines), len(b_lines))
    diff = 0
    for r in range(rows):
        la = a_lines[r] if r < len(a_lines) else ""
        lb = b_lines[r] if r < len(b_lines) else ""
        width = max(len(la), len(lb))
        for c in range(width):
            ca = la[c] if c < len(la) else " "
            cb = lb[c] if c < len(lb) else " "
            if ca != cb:
                diff += 1
    return diff


@contextmanager
def _suppress(exc_types: tuple[type[BaseException], ...]) -> Iterator[None]:
    """Tiny helper. Unused in the public API; kept for future use
    if the splash gains a sub-flow that should swallow specific
    exceptions without the Live re-raise dance."""
    try:
        yield
    except exc_types:
        pass


__all__ = ["run_with_splash"]
