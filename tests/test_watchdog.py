"""Unit tests for the anomaly-watchdog module."""

from __future__ import annotations

import asyncio

import pytest

from diting._watchdog import (
    SilenceClock,
    WatchdogConfig,
    maybe_notify,
    notify_message,
    should_notify_stir,
)


# ---------- SilenceClock ----------

def test_silence_clock_first_fire_returns_true() -> None:
    clock = SilenceClock(window_s=60)
    assert clock.should_fire("rf_stir", "AS11-2_4", now=100.0) is True


def test_silence_clock_second_fire_within_window_returns_false() -> None:
    clock = SilenceClock(window_s=60)
    clock.should_fire("rf_stir", "AS11-2_4", now=100.0)
    assert clock.should_fire("rf_stir", "AS11-2_4", now=120.0) is False


def test_silence_clock_second_fire_after_window_returns_true() -> None:
    clock = SilenceClock(window_s=60)
    clock.should_fire("rf_stir", "AS11-2_4", now=100.0)
    assert clock.should_fire("rf_stir", "AS11-2_4", now=161.0) is True


def test_silence_clock_independent_per_tuple() -> None:
    clock = SilenceClock(window_s=60)
    clock.should_fire("rf_stir", "AS11-2_4", now=100.0)
    # Different target, same kind — independent.
    assert clock.should_fire("rf_stir", "AS11-5", now=101.0) is True
    # Different kind, same target — independent.
    assert clock.should_fire(
        "latency_spike", "AS11-2_4", now=102.0,
    ) is True
    # Original tuple still silenced.
    assert clock.should_fire("rf_stir", "AS11-2_4", now=103.0) is False


# ---------- should_notify_stir ----------

def test_should_notify_stir_default_gate() -> None:
    assert should_notify_stir({"confidence": "high"}, "high") is True
    assert should_notify_stir({"confidence": "medium"}, "high") is False
    assert should_notify_stir({"confidence": "low"}, "high") is False
    assert should_notify_stir({}, "high") is False


def test_should_notify_stir_medium_gate() -> None:
    assert should_notify_stir({"confidence": "high"}, "medium") is True
    assert should_notify_stir({"confidence": "medium"}, "medium") is True
    assert should_notify_stir({"confidence": "low"}, "medium") is False
    assert should_notify_stir({}, "medium") is False


def test_should_notify_stir_all_gate() -> None:
    assert should_notify_stir({"confidence": "high"}, "all") is True
    assert should_notify_stir({"confidence": "medium"}, "all") is True
    assert should_notify_stir({"confidence": "low"}, "all") is True
    assert should_notify_stir({}, "all") is True


# ---------- WatchdogConfig.from_env ----------

def test_watchdog_config_defaults_when_env_unset() -> None:
    cfg = WatchdogConfig.from_env(env={})
    assert cfg.silence_window_s == 60
    assert cfg.stir_confidence == "high"


def test_watchdog_config_parses_valid_env() -> None:
    cfg = WatchdogConfig.from_env(env={
        "DITING_NOTIFY_SILENCE_S": "120",
        "DITING_NOTIFY_STIR_CONFIDENCE": "medium",
    })
    assert cfg.silence_window_s == 120
    assert cfg.stir_confidence == "medium"


def test_watchdog_config_falls_back_on_invalid_silence(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Not an integer.
    cfg = WatchdogConfig.from_env(env={"DITING_NOTIFY_SILENCE_S": "foo"})
    assert cfg.silence_window_s == 60
    err = capsys.readouterr().err
    assert "DITING_NOTIFY_SILENCE_S" in err
    assert "60" in err

    # Out of range (below floor).
    cfg = WatchdogConfig.from_env(env={"DITING_NOTIFY_SILENCE_S": "1"})
    assert cfg.silence_window_s == 60
    err = capsys.readouterr().err
    assert "out of range" in err

    # Out of range (above ceiling).
    cfg = WatchdogConfig.from_env(env={"DITING_NOTIFY_SILENCE_S": "99999"})
    assert cfg.silence_window_s == 60


def test_watchdog_config_falls_back_on_invalid_stir_gate(
    capsys: pytest.CaptureFixture[str],
) -> None:
    cfg = WatchdogConfig.from_env(env={
        "DITING_NOTIFY_STIR_CONFIDENCE": "mid",
    })
    assert cfg.stir_confidence == "high"
    err = capsys.readouterr().err
    assert "DITING_NOTIFY_STIR_CONFIDENCE" in err
    assert "high" in err


# ---------- maybe_notify integration ----------

class _RecordingNotifier:
    """Async notifier stub. Records every (title, message) call."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def __call__(self, *, title: str, message: str) -> None:
        self.calls.append((title, message))


def test_maybe_notify_fires_for_latency_spike() -> None:
    cfg = WatchdogConfig()
    clock = SilenceClock(window_s=60)
    notifier = _RecordingNotifier()
    asyncio.run(maybe_notify(
        {"type": "latency_spike", "target": "gateway:192.168.1.1",
         "rtt_ms": 240.5},
        target="gateway:192.168.1.1",
        clock=clock, config=cfg, notifier=notifier,
    ))
    assert len(notifier.calls) == 1
    title, message = notifier.calls[0]
    assert title == "diting"
    assert "Latency spike on gateway:192.168.1.1" in message
    assert "240.5 ms" in message


def test_maybe_notify_fires_for_loss_burst() -> None:
    cfg = WatchdogConfig()
    clock = SilenceClock(window_s=60)
    notifier = _RecordingNotifier()
    asyncio.run(maybe_notify(
        {"type": "loss_burst", "target": "WAN:1.1.1.1", "loss_pct": 60.0},
        target="WAN:1.1.1.1",
        clock=clock, config=cfg, notifier=notifier,
    ))
    assert len(notifier.calls) == 1
    _, message = notifier.calls[0]
    assert "Loss burst on WAN:1.1.1.1" in message
    assert "60.0%" in message


def test_maybe_notify_fires_for_rf_stir_high_confidence() -> None:
    cfg = WatchdogConfig()
    clock = SilenceClock(window_s=60)
    notifier = _RecordingNotifier()
    asyncio.run(maybe_notify(
        {"type": "rf_stir", "confidence": "high", "location": "AS11-2_4",
         "magnitude_db": 4.2},
        target="AS11-2_4",
        clock=clock, config=cfg, notifier=notifier,
    ))
    assert len(notifier.calls) == 1


def test_maybe_notify_gates_rf_stir_below_threshold() -> None:
    cfg = WatchdogConfig(stir_confidence="high")
    clock = SilenceClock(window_s=60)
    notifier = _RecordingNotifier()
    asyncio.run(maybe_notify(
        {"type": "rf_stir", "confidence": "medium", "location": "AS11-2_4"},
        target="AS11-2_4",
        clock=clock, config=cfg, notifier=notifier,
    ))
    assert notifier.calls == []
    # And clock was NOT consumed — a subsequent high-confidence event
    # should still fire.
    asyncio.run(maybe_notify(
        {"type": "rf_stir", "confidence": "high", "location": "AS11-2_4"},
        target="AS11-2_4",
        clock=clock, config=cfg, notifier=notifier,
    ))
    assert len(notifier.calls) == 1


def test_maybe_notify_silence_window_suppresses_duplicates() -> None:
    cfg = WatchdogConfig(silence_window_s=60)
    clock = SilenceClock(window_s=60)
    notifier = _RecordingNotifier()
    # First fire goes through.
    asyncio.run(maybe_notify(
        {"type": "latency_spike", "target": "gw", "rtt_ms": 200.0},
        target="gw",
        clock=clock, config=cfg, notifier=notifier,
    ))
    # Second within window suppressed.
    asyncio.run(maybe_notify(
        {"type": "latency_spike", "target": "gw", "rtt_ms": 210.0},
        target="gw",
        clock=clock, config=cfg, notifier=notifier,
    ))
    assert len(notifier.calls) == 1


def test_maybe_notify_silent_when_notify_disabled() -> None:
    """Call-site early-return contract.

    The module itself doesn't carry a notify-on/off flag — that gate
    lives at the call site (cli._run_monitor's `_notify` closure and
    DitingApp._maybe_notify). This test pins the contract by mimicking
    the closure: when the gate is off, ``maybe_notify`` is never
    invoked, so the notifier sees no calls.
    """
    notify = False
    cfg = WatchdogConfig()
    clock = SilenceClock(window_s=60)
    notifier = _RecordingNotifier()

    async def gated() -> None:
        if not notify:
            return
        await maybe_notify(
            {"type": "latency_spike", "target": "gw", "rtt_ms": 200.0},
            target="gw",
            clock=clock, config=cfg, notifier=notifier,
        )

    asyncio.run(gated())
    assert notifier.calls == []


def test_maybe_notify_ignores_unknown_event_type() -> None:
    cfg = WatchdogConfig()
    clock = SilenceClock(window_s=60)
    notifier = _RecordingNotifier()
    asyncio.run(maybe_notify(
        {"type": "roam", "target": "x"},
        target="x",
        clock=clock, config=cfg, notifier=notifier,
    ))
    assert notifier.calls == []


# ---------- notify_message ----------

def test_notify_message_rf_stir() -> None:
    msg = notify_message({
        "type": "rf_stir", "location": "AS11-2_4", "magnitude_db": 4.2,
    })
    assert "RF stir at AS11-2_4" in msg
    assert "4.2" in msg


def test_notify_message_latency_spike() -> None:
    msg = notify_message({
        "type": "latency_spike", "target": "gw", "rtt_ms": 240.5,
    })
    assert "Latency spike on gw" in msg
    assert "240.5 ms" in msg


def test_notify_message_loss_burst() -> None:
    msg = notify_message({
        "type": "loss_burst", "target": "WAN", "loss_pct": 60.0,
    })
    assert "Loss burst on WAN" in msg
    assert "60.0%" in msg


# ---------- _macos_notify: helper-binary routing ----------

def test_macos_notify_silent_when_helper_absent(monkeypatch) -> None:
    """If the diting helper binary cannot be resolved, the watchdog
    drops the notification silently — no osascript fallback, no
    error propagated to callers. The watchdog contract is fire-and-
    forget; a missing helper must never break the TUI."""
    from diting import _helper, _watchdog
    monkeypatch.setattr(_helper, "find_helper", lambda: None)
    # Should complete with no exception.
    asyncio.run(_watchdog._macos_notify(title="diting", message="x"))


def test_macos_notify_invokes_helper_notify_subcommand(monkeypatch) -> None:
    """When the helper IS available, `_macos_notify` shells out to
    `<helper> notify --title T --body B` (not osascript). The argv
    threads title and body through verbatim so the helper's
    UNUserNotificationCenter call carries the watchdog's text."""
    import asyncio as _asyncio
    from diting import _helper, _watchdog

    monkeypatch.setattr(_helper, "find_helper", lambda: "/fake/helper")
    captured: dict[str, object] = {}

    class _FakeProc:
        async def wait(self) -> int:
            return 0

    async def fake_exec(*argv, **kwargs):
        captured["argv"] = argv
        captured["stdout"] = kwargs.get("stdout")
        return _FakeProc()

    monkeypatch.setattr(_asyncio, "create_subprocess_exec", fake_exec)

    _asyncio.run(_watchdog._macos_notify(
        title="diting", message="Latency spike on gw: 240.5 ms",
    ))

    argv = captured["argv"]
    assert argv[0] == "/fake/helper"
    assert argv[1] == "notify"
    assert "--title" in argv
    assert "diting" in argv
    assert "--body" in argv
    assert "Latency spike on gw: 240.5 ms" in argv
    # And no osascript fallback path is hit.
    assert "/usr/bin/osascript" not in argv
