"""EventLogger tests.

Cover: schema stability (event-type names + field names stay
English regardless of UI locale), Unicode preservation in user-
supplied strings (Chinese SSID survives readable in the file),
link_state edge detection from raw connection updates, and the
no-op disabled logger that the TUI uses by default.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from wifiscope.event_log import EventLogger
from wifiscope.events import (
    LatencySpikeEvent,
    LinkStateEvent,
    LossBurstEvent,
)
from wifiscope.environment import RFStirEvent
from wifiscope.models import Connection
from wifiscope.poller import RoamEvent


def _conn(bssid: str, ssid: str = "office-wifi") -> Connection:
    return Connection(
        ssid=ssid, bssid=bssid, rssi_dbm=-55, noise_dbm=-94,
        tx_rate_mbps=300.0, channel=48, channel_width_mhz=80,
        channel_band="5 GHz", phy_mode=None, security="WPA2 Personal",
        mcs_index=None, nss=None,
        timestamp=datetime(2026, 5, 7, 21, 30, tzinfo=timezone.utc),
    )


def _read_jsonl(path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()]


# ------------------------------------------------------------------
# 1. Sink construction + lifecycle
# ------------------------------------------------------------------

def test_disabled_logger_is_a_no_op():
    """A logger constructed via .disabled() must accept every emit
    without writing anywhere. The TUI uses this when --log is not
    set, so any emit_X call must be safe to invoke unconditionally."""
    logger = EventLogger.disabled()
    logger.emit_connection_update(_conn("aa:bb:cc:11:22:33"))
    logger.emit_roam(RoamEvent(
        timestamp=datetime(2026, 5, 7, 21, 30, tzinfo=timezone.utc),
        previous_bssid="aa:bb:cc:11:22:33",
        previous_channel=36,
        new_bssid="aa:bb:cc:11:22:34",
        new_channel=149,
    ))
    logger.emit_rf_stir(RFStirEvent(
        timestamp=datetime(2026, 5, 7, 21, 30, tzinfo=timezone.utc),
        bssid="aa:bb:cc:11:22:33", location="?ab:cd:ef",
        magnitude_db=8.3, duration_s=12.0, confidence="high",
        mode="co_located",
    ))
    logger.close()  # must not raise


def test_to_path_writes_appendable_jsonl(tmp_path):
    """File sink opens in append mode so a TUI restart adds to the
    log instead of clobbering it. close() flushes before exit so
    the last line is persisted even if Python skips its atexit."""
    path = tmp_path / "events.jsonl"

    # First session: associate, then disassociate. Two rows.
    logger = EventLogger.to_path(str(path))
    logger.emit_connection_update(_conn("aa:bb:cc:11:22:33"))
    logger.emit_connection_update(None)
    logger.close()

    # Second session opens the same file in append mode — first
    # session's rows persist; new session starts with its own
    # state machine and re-associates to a different BSSID.
    logger2 = EventLogger.to_path(str(path))
    logger2.emit_connection_update(_conn("aa:bb:cc:11:22:99"))
    logger2.close()

    rows = _read_jsonl(path)
    assert len(rows) == 3
    assert rows[0]["state"] == "associated"
    assert rows[0]["bssid"] == "aa:bb:cc:11:22:33"
    assert rows[1]["state"] == "disassociated"
    assert rows[2]["state"] == "associated"
    assert rows[2]["bssid"] == "aa:bb:cc:11:22:99"


# ------------------------------------------------------------------
# 2. Schema is locale-stable English
# ------------------------------------------------------------------

def test_schema_keys_stay_english_under_zh_locale(tmp_path, monkeypatch):
    """Switching the UI to Chinese must not affect the JSONL log —
    log analysis scripts (jq, AI consumers) need a stable schema.
    The locale toggle changes ``t()`` resolution, but EventLogger
    bypasses i18n entirely for keys and discriminators."""
    from wifiscope import i18n
    original = i18n.get_lang()
    i18n.set_lang(i18n.ZH)
    try:
        path = tmp_path / "events.jsonl"
        logger = EventLogger.to_path(str(path))
        logger.emit_connection_update(_conn("aa:bb:cc:11:22:33"))
        logger.emit_rf_stir(RFStirEvent(
            timestamp=datetime(2026, 5, 7, 21, 30, tzinfo=timezone.utc),
            bssid="aa:bb:cc:11:22:33", location="1F-bedroom",
            magnitude_db=8.3, duration_s=12.0, confidence="high",
            mode="co_located",
        ))
        logger.close()

        rows = _read_jsonl(path)
        assert rows[0]["type"] == "link_state"
        assert rows[0]["state"] == "associated"  # not 已连接
        assert rows[1]["type"] == "rf_stir"
        assert rows[1]["mode"] == "co_located"   # not 同位
        assert rows[1]["confidence"] == "high"    # not 高
    finally:
        i18n.set_lang(original)


def test_unicode_user_strings_survive_readable(tmp_path):
    """User-supplied strings (SSID, AP location from aps.yaml) flow
    through unchanged. The log writes UTF-8 directly via
    ensure_ascii=False so a Chinese AP name like ``一楼书房`` is
    grep-able instead of becoming ``\\u4e00\\u697c\\u4e66\\u623f``."""
    path = tmp_path / "events.jsonl"
    logger = EventLogger.to_path(str(path))
    logger.emit_connection_update(_conn("aa:bb:cc:11:22:33", ssid="咖啡馆"))
    logger.emit_rf_stir(RFStirEvent(
        timestamp=datetime(2026, 5, 7, 21, 30, tzinfo=timezone.utc),
        bssid="aa:bb:cc:11:22:33", location="一楼书房",
        magnitude_db=8.3, duration_s=12.0, confidence="high",
        mode="co_located",
    ))
    logger.close()

    raw = path.read_text(encoding="utf-8")
    assert "咖啡馆" in raw
    assert "一楼书房" in raw
    # Make sure we did NOT escape these — that would mean
    # ensure_ascii=True regressed.
    assert "\\u" not in raw


# ------------------------------------------------------------------
# 3. Connection-update edge detection → link_state events
# ------------------------------------------------------------------

def test_connection_update_emits_associated_on_first_poll(tmp_path):
    """First call with a non-None connection emits an 'associated'
    event so the log has a clear session-start marker. Without
    this the first concrete event a long-running session would
    log might be a stir 30 minutes in, leaving no 'we're on AP X'
    anchor for an AI consumer to start from."""
    path = tmp_path / "events.jsonl"
    logger = EventLogger.to_path(str(path))
    logger.emit_connection_update(_conn("aa:bb:cc:11:22:33"))
    logger.close()

    rows = _read_jsonl(path)
    assert len(rows) == 1
    assert rows[0]["type"] == "link_state"
    assert rows[0]["state"] == "associated"
    assert rows[0]["bssid"] == "aa:bb:cc:11:22:33"


def test_connection_update_silent_when_first_poll_is_disassociated(tmp_path):
    """Starting the TUI while disconnected must NOT emit a
    'disassociated' event from the first poll — that would be
    noise. The first interesting log line is the eventual
    'associated' transition."""
    path = tmp_path / "events.jsonl"
    logger = EventLogger.to_path(str(path))
    logger.emit_connection_update(None)
    logger.close()

    assert path.read_text() == ""


def test_connection_update_emits_disassociate_on_drop(tmp_path):
    """Going from associated → disassociated emits one event.
    Subsequent None polls do not re-emit; the previous-state
    bookkeeping de-bounces them."""
    path = tmp_path / "events.jsonl"
    logger = EventLogger.to_path(str(path))
    logger.emit_connection_update(_conn("aa:bb:cc:11:22:33"))
    logger.emit_connection_update(None)
    logger.emit_connection_update(None)  # no-op
    logger.emit_connection_update(None)  # no-op
    logger.close()

    rows = _read_jsonl(path)
    states = [r["state"] for r in rows]
    assert states == ["associated", "disassociated"]


def test_connection_update_does_not_emit_on_bssid_to_bssid_change(tmp_path):
    """A BSSID-to-BSSID change without going through None is a
    roam event — emitted by the consumer separately. The
    connection-update path must NOT also emit a link_state edge,
    or we double-count the same observation."""
    path = tmp_path / "events.jsonl"
    logger = EventLogger.to_path(str(path))
    logger.emit_connection_update(_conn("aa:bb:cc:11:22:33"))
    logger.emit_connection_update(_conn("aa:bb:cc:11:22:99"))
    logger.close()

    rows = _read_jsonl(path)
    # Only the initial associate; no spurious "associated" repeat
    # for the BSSID change.
    assert len(rows) == 1
    assert rows[0]["bssid"] == "aa:bb:cc:11:22:33"


# ------------------------------------------------------------------
# 4. Other event emit shapes
# ------------------------------------------------------------------

def test_emit_roam_includes_kind_when_supplied(tmp_path):
    """The optional ``kind`` discriminator (band_switch / inter_ap)
    is computed by the consumer (which has inventory). The logger
    just attaches it when supplied; absence is still valid JSON."""
    path = tmp_path / "events.jsonl"
    logger = EventLogger.to_path(str(path))
    ev = RoamEvent(
        timestamp=datetime(2026, 5, 7, 21, 30, tzinfo=timezone.utc),
        previous_bssid="aa:bb:cc:11:22:33", previous_channel=36,
        new_bssid="aa:bb:cc:11:22:34", new_channel=149,
    )
    logger.emit_roam(ev, kind="band_switch")
    logger.emit_roam(ev)  # no kind
    logger.close()

    rows = _read_jsonl(path)
    assert rows[0]["kind"] == "band_switch"
    assert "kind" not in rows[1]


def test_emit_latency_spike_carries_target_and_rtt(tmp_path):
    path = tmp_path / "events.jsonl"
    logger = EventLogger.to_path(str(path))
    logger.emit_latency_spike(LatencySpikeEvent(
        timestamp=datetime(2026, 5, 7, 21, 30, tzinfo=timezone.utc),
        target="router", target_ip="192.168.1.1",
        rtt_ms=412.0, loss_pct=25.0,
    ))
    logger.close()

    row = _read_jsonl(path)[0]
    assert row["type"] == "latency_spike"
    assert row["target"] == "router"
    assert row["rtt_ms"] == 412.0


def test_emit_loss_burst_carries_lost_in_window(tmp_path):
    path = tmp_path / "events.jsonl"
    logger = EventLogger.to_path(str(path))
    logger.emit_loss_burst(LossBurstEvent(
        timestamp=datetime(2026, 5, 7, 21, 30, tzinfo=timezone.utc),
        target="wan", target_ip="114.114.114.114",
        loss_pct=80.0, lost_in_window=4,
    ))
    logger.close()

    row = _read_jsonl(path)[0]
    assert row["type"] == "loss_burst"
    assert row["lost_in_window"] == 4
    assert row["target"] == "wan"


def test_emit_link_state_dataclass_passthrough(tmp_path):
    """The pre-built LinkStateEvent path is for callers that
    have their own state machine. Just verify the field map."""
    path = tmp_path / "events.jsonl"
    logger = EventLogger.to_path(str(path))
    logger.emit_link_state(LinkStateEvent(
        timestamp=datetime(2026, 5, 7, 21, 30, tzinfo=timezone.utc),
        state="associated", bssid="aa:bb:cc:11:22:33", ssid="X",
    ))
    logger.close()

    row = _read_jsonl(path)[0]
    assert row["state"] == "associated"
    assert row["bssid"] == "aa:bb:cc:11:22:33"
    assert row["ssid"] == "X"


# ------------------------------------------------------------------
# 5. ts is ISO-8601 UTC
# ------------------------------------------------------------------

def test_timestamps_are_iso_utc(tmp_path):
    """Every event row carries a top-level 'ts' in ISO-8601 with an
    explicit UTC offset. AI consumers rely on this for sorting /
    bucketing across files; a missing tz would let DST corrupt
    relative ordering."""
    path = tmp_path / "events.jsonl"
    logger = EventLogger.to_path(str(path))
    logger.emit_connection_update(_conn("aa:bb:cc:11:22:33"))
    logger.close()

    row = _read_jsonl(path)[0]
    ts = row["ts"]
    # Either a +00:00 offset or a 'Z' suffix; both are ISO-8601 UTC.
    assert ts.endswith("+00:00") or ts.endswith("Z")
    assert "T" in ts  # date-time separator
