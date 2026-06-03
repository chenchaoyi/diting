"""Anomaly watchdog — notification side-effect for monitor and TUI.

Owns three pieces:

* :class:`WatchdogConfig` — env-var-driven settings.
* :class:`SilenceClock` — per-(event_type, target) cooldown so a
  sustained anomaly produces one banner per silence window rather
  than one per detector tick.
* :func:`maybe_notify` — the entry point both call sites share.

Silence window state is in-memory only; restart resets it (a feature —
first notification after restart per active anomaly class is desirable).
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from dataclasses import dataclass
from typing import Awaitable, Callable, Mapping

_VALID_STIR_GATES = ("high", "medium", "all")
_DEFAULT_SILENCE_S = 60
_MIN_SILENCE_S = 3
_MAX_SILENCE_S = 3600
_DEFAULT_STIR_GATE = "high"


@dataclass(frozen=True)
class WatchdogConfig:
    silence_window_s: int = _DEFAULT_SILENCE_S
    stir_confidence: str = _DEFAULT_STIR_GATE

    @classmethod
    def from_env(
        cls, env: Mapping[str, str] | None = None
    ) -> "WatchdogConfig":
        e = os.environ if env is None else env
        silence = _parse_silence(e.get("DITING_NOTIFY_SILENCE_S"))
        gate = _parse_stir_gate(e.get("DITING_NOTIFY_STIR_CONFIDENCE"))
        return cls(silence_window_s=silence, stir_confidence=gate)


def _parse_silence(raw: str | None) -> int:
    if raw is None or raw == "":
        return _DEFAULT_SILENCE_S
    try:
        n = int(raw)
    except (TypeError, ValueError):
        _warn(
            f"DITING_NOTIFY_SILENCE_S={raw!r} not an integer in "
            f"[{_MIN_SILENCE_S}, {_MAX_SILENCE_S}]; using default "
            f"{_DEFAULT_SILENCE_S}"
        )
        return _DEFAULT_SILENCE_S
    if not (_MIN_SILENCE_S <= n <= _MAX_SILENCE_S):
        _warn(
            f"DITING_NOTIFY_SILENCE_S={raw} out of range "
            f"[{_MIN_SILENCE_S}, {_MAX_SILENCE_S}]; using default "
            f"{_DEFAULT_SILENCE_S}"
        )
        return _DEFAULT_SILENCE_S
    return n


def _parse_stir_gate(raw: str | None) -> str:
    if raw is None or raw == "":
        return _DEFAULT_STIR_GATE
    if raw not in _VALID_STIR_GATES:
        _warn(
            f"DITING_NOTIFY_STIR_CONFIDENCE={raw!r} not one of "
            f"{_VALID_STIR_GATES}; using default {_DEFAULT_STIR_GATE!r}"
        )
        return _DEFAULT_STIR_GATE
    return raw


def _warn(message: str) -> None:
    print(f"diting: warning: {message}", file=sys.stderr)


class SilenceClock:
    """Per-(event_type, target) cooldown clock.

    ``should_fire`` returns ``True`` when no prior fire is recorded for
    ``(kind, target)`` OR when ``now - last >= window_s``. The clock
    records the new timestamp only when it returns ``True``, so callers
    that decline to fire (e.g. severity-gated out before this point)
    must not have called ``should_fire`` at all.
    """

    def __init__(self, window_s: int) -> None:
        self._window_s = window_s
        self._last_fired_at: dict[tuple[str, str], float] = {}

    def should_fire(self, kind: str, target: str, now: float) -> bool:
        key = (kind, target)
        last = self._last_fired_at.get(key)
        if last is not None and (now - last) < self._window_s:
            return False
        self._last_fired_at[key] = now
        return True


def should_notify_stir(payload: dict, gate: str) -> bool:
    """Severity gate for ``rf_stir`` events.

    ``gate`` is one of ``"high" / "medium" / "all"`` (already validated
    by :class:`WatchdogConfig`). Returns True iff the payload's
    confidence meets the gate.
    """
    confidence = payload.get("confidence")
    if gate == "all":
        return True
    if gate == "medium":
        return confidence in ("medium", "high")
    return confidence == "high"


def notify_message(payload: dict) -> str:
    """Compose a short macOS notification body from an event dict."""
    kind = payload.get("type")
    if kind == "rf_stir":
        return (
            f"RF stir at {payload.get('location', '?')} — "
            f"σ {payload.get('magnitude_db', '?')} dB"
        )
    if kind == "latency_spike":
        return (
            f"Latency spike on {payload.get('target', '?')}: "
            f"{payload.get('rtt_ms', '?')} ms"
        )
    if kind == "loss_burst":
        return (
            f"Loss burst on {payload.get('target', '?')}: "
            f"{payload.get('loss_pct', '?')}%"
        )
    if kind == "insight":
        # The caller passes the already-localised one-liner; fall back to the
        # stable code if it didn't.
        return str(payload.get("summary") or payload.get("code", "insight"))
    return f"event {kind}"


NotifierCallable = Callable[..., Awaitable[None]]


async def maybe_notify(
    payload: dict,
    *,
    target: str,
    clock: SilenceClock,
    config: WatchdogConfig,
    notifier: NotifierCallable | None = None,
) -> None:
    """Apply severity gate + silence window; fire ``osascript`` when both pass.

    Call sites:

    * ``cli._run_monitor`` (headless ``monitor --notify``)
    * ``tui.DitingApp`` (interactive ``diting --notify``)

    Both pass a ``clock`` and ``config`` constructed once at startup.
    ``notifier`` defaults to :func:`_macos_notify`; tests inject a stub.
    """
    kind = payload.get("type")
    if kind == "rf_stir":
        if not should_notify_stir(payload, config.stir_confidence):
            return
    elif kind == "insight":
        # note/warn/critical insights raise a banner; info stays log + TUI only.
        # critical is the threat tier — always notifies.
        if payload.get("severity") not in ("note", "warn", "critical"):
            return
    elif kind not in ("latency_spike", "loss_burst"):
        return
    if not clock.should_fire(kind, target, time.monotonic()):
        return
    fn = notifier if notifier is not None else _macos_notify
    await fn(title="diting", message=notify_message(payload))


async def _macos_notify(*, title: str, message: str) -> None:
    """Post a macOS notification via the diting helper bundle.

    The helper's `notify` subcommand uses `UNUserNotificationCenter`
    under the bundle's identity, so the notification carries the
    bundle's AppIcon (the diting logo) — unlike the legacy
    `osascript -e 'display notification'` path which always
    attached the AppleScript scroll icon.

    Best-effort: if the helper isn't installed or doesn't respond in
    time, the notification is silently skipped. The watchdog's
    contract is fire-and-forget; we never propagate an exception
    into the TUI's event loop.
    """
    # Imported lazily to keep this module's import path free of the
    # macos_backend / pyobjc graph — _watchdog runs in `diting monitor`
    # (headless CLI) as well as the TUI, and we don't want to drag
    # CoreWLAN into the import surface of the simpler path.
    from . import _helper

    binary = _helper.find_helper()
    if binary is None:
        return
    try:
        proc = await asyncio.create_subprocess_exec(
            binary, "notify",
            "--title", title,
            "--body", message,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(proc.wait(), timeout=3.0)
    except (FileNotFoundError, OSError, asyncio.TimeoutError):
        pass
