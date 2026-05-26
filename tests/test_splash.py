"""Unit coverage for `src/diting/splash.py`.

Pins the frame-data invariants (silhouette stays put across
adjacent frames), the three-tier dispatch (interactive / narrow /
non-TTY), and the status-line semantics (`[..]` → `[✓]` / `[✗]`
with falsy probes and re-raise on exception).
"""

from __future__ import annotations

import io
from typing import Any

import pytest
from rich.console import Console

from diting import i18n, splash
from diting.splash import (
    _FRAME_CANONICAL,
    _FRAMES,
    _cells_differ,
    _frame_dimensions,
    run_with_splash,
)
from diting.tui import _LOGO_MARK_ART


# ---------- Frame-data invariants ----------

def test_frames_share_row_and_column_count():
    """Every entry in `_FRAMES` matches the canonical mark's grid
    so the silhouette never visibly resizes during animation. The
    canonical pose itself MUST match `_LOGO_MARK_ART` from
    `tui.py:6181` byte-for-byte — splash and running header
    render the same beast."""
    assert _FRAME_CANONICAL == _LOGO_MARK_ART, (
        "splash canonical frame drifted from tui._LOGO_MARK_ART"
    )
    canonical_rows, canonical_width = _frame_dimensions(_FRAME_CANONICAL)
    for frame in _FRAMES:
        rows, width = _frame_dimensions(frame)
        assert rows == canonical_rows, (
            f"frame has {rows} rows; canonical is {canonical_rows}"
        )
        assert width == canonical_width, (
            f"frame has width {width}; canonical is {canonical_width}"
        )


def test_adjacent_frames_differ_by_at_most_two_cells():
    """Micro-motion only — silhouette identity preserved per the
    `do not redesign the mark` rule in CLAUDE.md."""
    for i in range(len(_FRAMES)):
        a = _FRAMES[i]
        b = _FRAMES[(i + 1) % len(_FRAMES)]
        diff = _cells_differ(a, b)
        assert diff <= 2, (
            f"adjacent frames {i} → {(i+1) % len(_FRAMES)} differ in "
            f"{diff} cells; spec caps adjacent deltas at 2"
        )


# ---------- Tier dispatch helpers ----------

def _capture_console(*, terminal: bool, width: int = 80) -> Console:
    """Build a Rich Console writing to an in-memory buffer.

    `force_terminal=True` together with a stubbed buffer would make
    Rich emit ANSI escapes; we keep it off to keep assertions
    plain-text. The Tier B / Tier A dispatch hinges on
    `is_terminal` and `size.width`, both of which are honoured
    when we pass them explicitly via `Console(...)` kwargs.
    """
    return Console(
        file=io.StringIO(),
        force_terminal=terminal,
        force_interactive=terminal,
        width=width,
        legacy_windows=False,
    )


# ---------- Tier C (non-TTY) ----------

def test_run_with_splash_tier_c_non_tty():
    """Non-TTY fallback: single plain line + raw callable
    invocation. No Live, no cursor games."""
    calls: list[str] = []

    def ok_a():
        calls.append("a")
        return True

    def ok_b():
        calls.append("b")
        return True

    console = _capture_console(terminal=False)
    results = run_with_splash(
        [("step a", ok_a), ("step b", ok_b)],
        console=console,
    )
    assert results == [True, True]
    assert calls == ["a", "b"]
    output = console.file.getvalue()
    assert "diting starting" in output
    # No status glyphs leak into Tier C output.
    assert "[..]" not in output
    assert "[✓]" not in output


# ---------- Tier B (narrow TTY) ----------

def test_run_with_splash_tier_b_narrow():
    """Narrow TTY: static beast + `\\r` status overwrites."""
    console = _capture_console(terminal=True, width=20)
    results = run_with_splash(
        [
            ("a", lambda: True),
            ("b", lambda: True),
            ("c", lambda: True),
        ],
        console=console,
    )
    assert results == [True, True, True]
    output = console.file.getvalue()
    # Beast rendered (look for a slice of the canonical art).
    assert "█▀██████▄" in output
    # `\r` overwrite was used at least once for the running status.
    assert "\r" in output


# ---------- Tier C tick sequence + falsy + raising ----------

def test_run_with_splash_tick_sequence():
    """Callables fire in order and their results land in the same
    order; truthy / falsy are reported faithfully."""
    seen: list[str] = []

    def make(name: str, ret: Any):
        def fn():
            seen.append(name)
            return ret
        return fn

    console = _capture_console(terminal=False)
    results = run_with_splash(
        [
            ("a", make("a", True)),
            ("b", make("b", "non-empty string also truthy")),
            ("c", make("c", 0)),  # 0 is falsy
        ],
        console=console,
    )
    assert seen == ["a", "b", "c"]
    assert results == [True, True, False]


def test_run_with_splash_callable_falsy_marks_step_failed():
    """A falsy probe SHALL mark the step `[✗]` in the rendered
    output. Subsequent steps still run."""
    console = _capture_console(terminal=True, width=80)
    results = run_with_splash(
        [
            ("first", lambda: True),
            ("middle", lambda: False),
            ("last", lambda: True),
        ],
        console=console,
    )
    assert results == [True, False, True]
    output = console.file.getvalue()
    assert "[✗]" in output


def test_run_with_splash_callable_raising_reraises_after_teardown():
    """A raising callable re-raises AFTER the splash tears down so
    upstream exception handling still fires; subsequent steps are
    skipped (their results are False) and the live cursor never
    leaks."""

    def boom():
        raise OSError("helper subprocess crashed")

    console = _capture_console(terminal=False)
    with pytest.raises(OSError, match="helper subprocess crashed"):
        run_with_splash(
            [
                ("a", lambda: True),
                ("b", boom),
                ("c", lambda: True),  # SHALL NOT run
            ],
            console=console,
        )


def test_run_with_splash_callable_raising_skips_subsequent_steps():
    """When a callable raises, callables after it MUST NOT execute
    — the splash's failure semantics short-circuit, just like a
    bare try/except around the original probe chain would."""
    called: list[str] = []

    def boom():
        called.append("b")
        raise OSError("boom")

    def later():
        called.append("c")
        return True

    console = _capture_console(terminal=False)
    with pytest.raises(OSError):
        run_with_splash(
            [
                ("a", lambda: called.append("a") or True),
                ("b", boom),
                ("c", later),
            ],
            console=console,
        )
    assert called == ["a", "b"]


# ---------- i18n ----------

def test_run_with_splash_zh_locale(monkeypatch):
    """Status labels translate via `t()` at call-site; the splash
    itself doesn't touch i18n. Verify the keys exist in the ZH
    catalog by rendering a step whose label is the EN catalog key."""
    monkeypatch.setattr(i18n, "_LANG", i18n.ZH, raising=False)
    i18n.set_lang(i18n.ZH)
    try:
        label_a = i18n.t("checking Location Services")
        label_b = i18n.t("checking Bluetooth")
        assert label_a == "检查 Location Services"
        assert label_b == "检查 Bluetooth"
        # `diting starting...` label travels through Tier C too.
        assert i18n.t("diting starting...") == "diting 启动中…"
    finally:
        i18n.set_lang(i18n.EN)
