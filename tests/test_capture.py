"""CaptureEngine tests — headless assembly + emit routing.

These drive the engine with fake pollers (no helper / network / Textual)
so the construct → drive → drain → emit contract is deterministic.
"""
from __future__ import annotations

import asyncio
import inspect
from datetime import datetime, timezone

import pytest

from diting import capture
from diting.capture import CaptureEngine
from diting.events import (
    BLEDeviceLeftEvent,
    BLEDeviceSeenEvent,
    BonjourServiceSeenEvent,
    LANHostSeenEvent,
)


# ---------- fakes ----------

class RecordingLogger:
    """Records every method call (emit_* / set_* / close) by name."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple, dict]] = []

    def __getattr__(self, name):
        def f(*a, **k):
            self.calls.append((name, a, k))
        return f

    def names(self) -> list[str]:
        return [c[0] for c in self.calls]

    def kwargs_of(self, name: str) -> dict:
        for n, _a, k in self.calls:
            if n == name:
                return k
        raise KeyError(name)


class FakePoller:
    """Yields one update, surfaces preset transitions once, then idles
    until cancelled."""

    def __init__(self, *args, **kwargs) -> None:
        self.args = args
        self.kwargs = kwargs
        self.stopped = False
        self._transitions: list = []
        self._raise: Exception | None = None

    def feed(self, transitions: list) -> "FakePoller":
        self._transitions = list(transitions)
        return self

    def will_raise(self, exc: Exception) -> "FakePoller":
        self._raise = exc
        return self

    async def events(self):
        if self._raise is not None:
            raise self._raise
        yield object()
        await asyncio.Event().wait()  # stay alive until cancelled

    def drain_transitions(self) -> list:
        t, self._transitions = self._transitions, []
        return t

    def stop(self) -> None:
        self.stopped = True


class Backend:
    name = "fake"

    def __init__(self, conn=None) -> None:
        self._conn = conn

    def get_connection(self):
        return self._conn

    def permission_state(self):
        return "granted"


class Inv:
    def is_same_ap(self, a, b):
        return False


def _engine(sensors, *, logger=None, helper=None, **kw) -> CaptureEngine:
    return CaptureEngine(
        Backend(), Inv(),
        logger=logger or RecordingLogger(),
        sensors=sensors,
        ble_helper_path=helper,
        **kw,
    )


def _patch_pollers(monkeypatch, **seeded):
    """Patch each poller class to return a (possibly pre-seeded) FakePoller,
    recording every constructed instance. Returns a dict name -> list."""
    built: dict[str, list] = {k: [] for k in
                              ("wifi", "ble", "bonjour", "lan", "latency")}

    def factory(key):
        def make(*a, **k):
            p = seeded.get(key) or FakePoller(*a, **k)
            p.args, p.kwargs = a, k
            built[key].append(p)
            return p
        return make

    monkeypatch.setattr(capture, "WiFiPoller", factory("wifi"))
    monkeypatch.setattr("diting.ble.BLEPoller", factory("ble"))
    monkeypatch.setattr("diting.mdns.BonjourPoller", factory("bonjour"))
    monkeypatch.setattr("diting.lan.LANInventoryPoller", factory("lan"))
    monkeypatch.setattr("diting.latency.LatencyPoller", factory("latency"))
    return built


# ---------- sensor resolution + manifest ----------

def test_engine_constructs_only_requested_sensors(monkeypatch):
    built = _patch_pollers(monkeypatch)
    eng = _engine({"wifi", "rf", "ble"}, helper="/x")
    assert eng.active_sensors() == {
        "wifi": True, "latency": False, "rf": True,
        "ble": True, "lan": False, "mdns": False,
    }
    asyncio.run(eng.run(duration_s=0.05))
    assert len(built["wifi"]) == 1
    assert len(built["ble"]) == 1
    assert built["lan"] == [] and built["bonjour"] == []
    assert built["latency"] == []


def test_engine_has_no_widget_coupling():
    src = inspect.getsource(capture)
    for token in ("query_one", "EventsPanel", "run_worker", "self.query"):
        assert token not in src


def test_manifest_reflects_active_set():
    log = RecordingLogger()
    eng = _engine({"wifi", "latency", "rf", "ble"}, logger=log, helper="/x")
    eng._setup()
    monitors = log.kwargs_of("emit_session_meta")["monitors"]
    assert monitors["ble"]["active"] is True
    assert monitors["lan"]["active"] is False
    assert monitors["latency"]["active"] is True


def test_unavailable_sensor_marked_inactive(capsys):
    log = RecordingLogger()
    eng = _engine({"ble"}, logger=log, helper=None)  # no helper → BLE can't run
    assert eng.active_sensors()["ble"] is False
    eng._setup()
    monitors = log.kwargs_of("emit_session_meta")["monitors"]
    assert monitors["ble"]["active"] is False
    assert "without BLE" in capsys.readouterr().err


# ---------- emit routing ----------

def test_transition_routes_to_emit(monkeypatch):
    seen = BLEDeviceSeenEvent(
        timestamp=datetime.now(timezone.utc), identifier="a", name="x",
        vendor="Acme", rssi_dbm=-50, service_categories=(),
    )
    left = BLEDeviceLeftEvent(
        timestamp=datetime.now(timezone.utc), identifier="a", name="x",
        vendor="Acme", last_rssi_dbm=-50, service_categories=(),
        seen_for_seconds=12.0,
    )
    ble = FakePoller().feed([seen, left])
    _patch_pollers(monkeypatch, ble=ble)
    log = RecordingLogger()
    eng = _engine({"ble"}, logger=log, helper="/x")
    asyncio.run(eng.run(duration_s=0.1))
    assert ("emit_ble_device_seen", (seen,), {}) in log.calls
    assert ("emit_ble_device_left", (left,), {}) in log.calls


def test_capture_roundtrips_through_analyze(tmp_path, monkeypatch):
    # A real (file) logger + a fake BLE poller feeding one seen event →
    # the JSONL file parses + analyzes like any other capture.
    from diting.event_log import EventLogger
    from diting import analyze
    seen = BLEDeviceSeenEvent(
        timestamp=datetime.now(timezone.utc), identifier="a", name="x",
        vendor="Acme", rssi_dbm=-50, service_categories=(),
    )
    _patch_pollers(monkeypatch, ble=FakePoller().feed([seen]))
    out = tmp_path / "cap.jsonl"
    eng = _engine({"ble"}, logger=EventLogger.to_path(str(out)), helper="/x")
    asyncio.run(eng.run(duration_s=0.1))
    events = analyze.parse_jsonl(out)
    types = {e.get("type") for e in events}
    assert "session_meta" in types and "ble_device_seen" in types
    report = analyze.analyze(events, source_paths=[str(out)], since=None)
    assert report is not None


# ---------- degradation + isolation ----------

def test_missing_ble_helper_skips_ble_others_continue(monkeypatch, capsys):
    built = _patch_pollers(monkeypatch)
    eng = _engine({"wifi", "ble"}, helper=None)
    asyncio.run(eng.run(duration_s=0.05))
    assert len(built["wifi"]) == 1      # Wi-Fi still ran
    assert built["ble"] == []           # BLE skipped
    assert "without BLE" in capsys.readouterr().err


def test_runtime_poller_error_isolated(monkeypatch):
    # BLE poller raises immediately; the engine must not crash and the
    # other consumers keep running.
    ble = FakePoller().will_raise(RuntimeError("boom"))
    built = _patch_pollers(monkeypatch, ble=ble)
    eng = _engine({"wifi", "ble"}, helper="/x")
    asyncio.run(eng.run(duration_s=0.1))  # must not raise
    assert len(built["wifi"]) == 1


# ---------- construction order + network change ----------

def test_bonjour_shared_into_lan(monkeypatch):
    built = _patch_pollers(monkeypatch)
    eng = _engine({"lan", "mdns"})
    asyncio.run(eng.run(duration_s=0.1))
    assert len(built["bonjour"]) == 1 and len(built["lan"]) == 1
    lan = built["lan"][0]
    assert lan.kwargs.get("bonjour_poller") is built["bonjour"][0]


def test_network_change_on_gateway_shift():
    log = RecordingLogger()
    eng = _engine({"wifi", "latency"}, logger=log)
    eng._fire_network_change(previous_router_ip="10.0.0.1", new_router_ip="10.0.1.1")
    assert "emit_network_change" in log.names()


# ---------- teardown ----------

def test_teardown_cancels_tasks_and_closes_logger(monkeypatch):
    built = _patch_pollers(monkeypatch)
    log = RecordingLogger()
    eng = _engine({"wifi", "lan", "mdns"}, logger=log)
    asyncio.run(eng.run(duration_s=0.1))
    assert "close" in log.names()
    assert all(t.done() for t in eng._tasks)
    # bonjour + lan pollers were stopped
    assert built["bonjour"][0].stopped is True
    assert built["lan"][0].stopped is True
