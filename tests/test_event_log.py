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


def test_emit_network_change_carries_router_ip_transition(tmp_path):
    """The network_change event records the gateway-IP shift that
    triggers a LatencyPoller rebuild. SSID / BSSID are optional
    context; previous-side fields are typically None because the
    previous network's metadata isn't recorded long-term."""
    from wifiscope.events import NetworkChangeEvent
    path = tmp_path / "events.jsonl"
    logger = EventLogger.to_path(str(path))
    logger.emit_network_change(NetworkChangeEvent(
        timestamp=datetime(2026, 5, 8, 9, 30, tzinfo=timezone.utc),
        previous_router_ip="192.168.124.1",
        new_router_ip="10.20.30.1",
        previous_ssid=None,
        new_ssid="office-wifi",
        previous_bssid=None,
        new_bssid="AA:BB:CC:11:22:33",
    ))
    logger.close()

    row = _read_jsonl(path)[0]
    assert row["type"] == "network_change"
    assert row["previous_router_ip"] == "192.168.124.1"
    assert row["new_router_ip"] == "10.20.30.1"
    # BSSID should be lower-cased like the rest of the schema.
    assert row["new_bssid"] == "aa:bb:cc:11:22:33"
    # Optional fields: emitted only when set on the dataclass.
    assert "previous_ssid" not in row
    assert "previous_bssid" not in row


def test_emit_roam_includes_vendor_and_ssid_when_supplied(tmp_path):
    """Roam events carry SSID + previous/new vendor when the
    consumer can compute them. Vendor change across a roam is
    the clearest single signal of a physical-network crossing
    (home Xiaomi → office Aruba)."""
    path = tmp_path / "events.jsonl"
    logger = EventLogger.to_path(str(path))
    ev = RoamEvent(
        timestamp=datetime(2026, 5, 8, 9, 30, tzinfo=timezone.utc),
        previous_bssid="40:fe:95:8a:3c:58", previous_channel=1,
        new_bssid="1c:28:af:5e:a7:14", new_channel=161,
    )
    logger.emit_roam(
        ev, kind="inter_ap", ssid="tedo_5G",
        previous_vendor="Xiaomi Communications",
        new_vendor="Liteon Technology",
    )
    logger.close()

    row = _read_jsonl(path)[0]
    assert row["kind"] == "inter_ap"
    assert row["ssid"] == "tedo_5G"
    assert row["previous_vendor"] == "Xiaomi Communications"
    assert row["new_vendor"] == "Liteon Technology"


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

def test_line_buffered_writes_are_visible_before_close(tmp_path):
    """Durability guarantee: every emit_X call should land on disk
    before the next one returns. A reader opening the file mid-
    session must see fully-formed JSONL lines, not buffered
    fragments. This is the property that protects already-emitted
    events from crashes / kills — the kernel page cache holds the
    bytes even if Python dies between events."""
    path = tmp_path / "events.jsonl"
    logger = EventLogger.to_path(str(path))
    logger.emit_connection_update(_conn("aa:bb:cc:11:22:33"))
    # Read the file WITHOUT closing the logger first. The line
    # must be fully present + terminated by \n; if buffering is
    # broken we'd see "" or a fragment.
    contents = path.read_text(encoding="utf-8")
    assert contents.endswith("\n")
    parsed = json.loads(contents.strip())
    assert parsed["state"] == "associated"
    logger.close()


def test_default_log_path_is_timestamped_jsonl():
    """`wifiscope --log` (no path) generates a timestamped filename
    in the current directory. The format must be filesystem-safe
    on macOS / Linux / case-insensitive shares — no colons —
    and end in .jsonl so editors / log shippers recognise it."""
    from wifiscope.cli import _default_log_path
    name = _default_log_path()
    assert name.startswith("wifiscope-")
    assert name.endswith(".jsonl")
    assert ":" not in name
    # Includes a date-time block: YYYYMMDD-HHMMSS sandwiched between
    # the prefix and the extension. The exact value is "now" so we
    # can't assert it equals anything; just sanity-check the shape.
    middle = name[len("wifiscope-"):-len(".jsonl")]
    assert "-" in middle
    date_part, time_part = middle.split("-", 1)
    assert len(date_part) == 8 and date_part.isdigit()
    assert len(time_part) == 6 and time_part.isdigit()


def test_resolve_log_path_cli_no_value_uses_default():
    """The CLI flag without a path → timestamped default. This is
    the user-friendly opt-in path: type `--log` and a sensible
    file appears in your current directory."""
    from wifiscope.cli import _LOG_DEFAULT, _resolve_log_path
    resolved = _resolve_log_path(_LOG_DEFAULT)
    assert resolved is not None
    assert resolved.startswith("wifiscope-")
    assert resolved.endswith(".jsonl")


def test_resolve_log_path_cli_explicit_path_wins(tmp_path, monkeypatch):
    """An explicit CLI path overrides everything else, including a
    set WIFISCOPE_LOG env var that would otherwise have applied."""
    from wifiscope.cli import _resolve_log_path
    monkeypatch.setenv("WIFISCOPE_LOG", "/should/be/ignored.jsonl")
    explicit = str(tmp_path / "my.jsonl")
    assert _resolve_log_path(explicit) == explicit


def test_resolve_log_path_env_auto_uses_default(monkeypatch):
    """``WIFISCOPE_LOG=auto`` is the env-var equivalent of bare
    ``--log`` — useful for cron / launchd plists where positional
    flags are awkward."""
    from wifiscope.cli import _resolve_log_path
    monkeypatch.setenv("WIFISCOPE_LOG", "auto")
    resolved = _resolve_log_path(None)
    assert resolved is not None
    assert resolved.startswith("wifiscope-")


def test_resolve_log_path_env_blank_disables(monkeypatch):
    """Blank env var means off, even if a parent shell set the
    var globally. Lets users disable logging for one invocation
    with ``WIFISCOPE_LOG= wifiscope`` without unsetting their
    profile-level config."""
    from wifiscope.cli import _resolve_log_path
    monkeypatch.setenv("WIFISCOPE_LOG", "")
    assert _resolve_log_path(None) is None


def test_extract_log_arg_no_value_returns_sentinel():
    """`--log` followed by a subcommand or another flag (or
    nothing) parses as the no-value sentinel. Path-form still
    works alongside the sentinel form."""
    from wifiscope.cli import _LOG_DEFAULT, _extract_log_arg
    # Bare --log at the end.
    args = ["--log"]
    assert _extract_log_arg(args) is _LOG_DEFAULT
    assert args == []
    # --log followed by a subcommand → no-value.
    args = ["--log", "monitor"]
    assert _extract_log_arg(args) is _LOG_DEFAULT
    assert args == ["monitor"]
    # --log followed by another flag → no-value.
    args = ["--log", "--lang", "zh"]
    assert _extract_log_arg(args) is _LOG_DEFAULT
    assert args == ["--lang", "zh"]
    # --log path → explicit path.
    args = ["--log", "/tmp/x.jsonl"]
    assert _extract_log_arg(args) == "/tmp/x.jsonl"
    assert args == []
    # --log= (empty value) → sentinel too, since `--log=` is
    # equivalent to bare `--log` in user intent.
    args = ["--log="]
    assert _extract_log_arg(args) is _LOG_DEFAULT
    assert args == []


def test_timestamps_are_iso_utc(tmp_path):
    """Every event row carries a top-level 'ts' in ISO-8601 with an
    explicit local-timezone offset. The offset is what makes
    cross-timezone analysis still work (sorting, AI consumers,
    comparing logs from different machines); the local-clock
    value is what makes the file readable to a user grepping
    their own log without doing mental arithmetic."""
    from datetime import datetime as _dt
    path = tmp_path / "events.jsonl"
    logger = EventLogger.to_path(str(path))
    logger.emit_connection_update(_conn("aa:bb:cc:11:22:33"))
    logger.close()

    row = _read_jsonl(path)[0]
    ts = row["ts"]
    assert "T" in ts  # date-time separator
    # ISO-8601 with explicit offset (either ±HH:MM or 'Z').
    parsed = _dt.fromisoformat(ts.replace("Z", "+00:00"))
    assert parsed.utcoffset() is not None


def test_naive_datetime_treated_as_local_not_utc(tmp_path):
    """Regression for the 'log shows two events 8 hours apart that
    actually fired one second apart' bug. Producers (the TUI's
    EnvironmentMonitor, RFStirEvent.timestamp setters) hand us
    naive ``datetime.now()`` values which are by Python convention
    LOCAL time, not UTC. The previous _iso implementation labelled
    them as UTC, silently shifting every event by the local offset
    and corrupting cross-timezone analysis.

    Verify: an aware UTC timestamp and a naive local timestamp
    that represent the *same wall-clock moment* should produce
    'ts' fields that resolve to the same instant in time, even
    though both are now serialised in the producer's local
    timezone (with explicit offset preserving correctness).
    """
    from datetime import datetime as _dt
    path = tmp_path / "events.jsonl"
    logger = EventLogger.to_path(str(path))
    # Pick a fixed local moment, then derive the UTC-aware
    # equivalent of that same moment.
    naive_local = _dt(2026, 5, 7, 22, 44, 6)
    aware_utc = naive_local.astimezone().astimezone(timezone.utc)
    logger.emit_link_state(LinkStateEvent(
        timestamp=naive_local, state="associated",
        bssid="aa:bb:cc:11:22:33", ssid="X",
    ))
    logger.emit_link_state(LinkStateEvent(
        timestamp=aware_utc, state="associated",
        bssid="aa:bb:cc:11:22:34", ssid="X",
    ))
    logger.close()

    rows = _read_jsonl(path)
    # Both rows describe the same moment in time. Parsing back
    # yields aware datetimes which compare equal regardless of
    # which offset they happen to carry on the wire.
    ts0 = _dt.fromisoformat(rows[0]["ts"])
    ts1 = _dt.fromisoformat(rows[1]["ts"])
    assert abs((ts0 - ts1).total_seconds()) < 1e-6
    # Both must carry an explicit offset — never naive.
    assert ts0.utcoffset() is not None
    assert ts1.utcoffset() is not None
