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

from diting.event_log import EventLogger
from diting.events import (
    LatencySpikeEvent,
    LinkStateEvent,
    LossBurstEvent,
)
from diting.environment import RFStirEvent
from diting.models import Connection
from diting.poller import RoamEvent


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
    from diting import i18n
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
    from diting.events import NetworkChangeEvent
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


def test_event_to_jsonl_roundtrip_roam_with_ssid_pair(tmp_path):
    """RoamEvent's new `previous_ssid` / `new_ssid` fields land in
    the JSONL line under English keys after the existing
    BSSID / channel block. wifi-event-ssid-and-name-enrichment
    schema change."""
    path = tmp_path / "events.jsonl"
    logger = EventLogger.to_path(str(path))
    ev = RoamEvent(
        timestamp=datetime(2026, 5, 18, 9, 30, tzinfo=timezone.utc),
        previous_bssid="40:fe:95:8a:3c:58", previous_channel=1,
        new_bssid="40:fe:95:8a:3c:59", new_channel=11,
        previous_ssid="tedo", new_ssid="tedo",
    )
    logger.emit_roam(ev)
    logger.close()

    row = _read_jsonl(path)[0]
    assert row["previous_ssid"] == "tedo"
    assert row["new_ssid"] == "tedo"


def test_event_to_jsonl_roundtrip_rf_stir_with_ssid(tmp_path):
    """RFStirEvent.ssid lands in the JSONL line after the existing
    bssid / location keys."""
    path = tmp_path / "events.jsonl"
    logger = EventLogger.to_path(str(path))
    logger.emit_rf_stir(RFStirEvent(
        timestamp=datetime(2026, 5, 18, 9, 49, tzinfo=timezone.utc),
        bssid="1c:28:af:5e:9d:b4", location="?af:5e:9d",
        magnitude_db=4.8, duration_s=12.0,
        confidence="medium", mode="spatial_channel",
        ssid="tedo_5G",
    ))
    logger.close()
    row = _read_jsonl(path)[0]
    assert row["ssid"] == "tedo_5G"


def test_event_to_jsonl_omits_ssid_keys_when_none(tmp_path):
    """When the new SSID fields are None (pre-enrichment construct
    path, or TCC-redacted runtime), the JSONL line MUST NOT carry
    the new keys at all — keeps old log entries diff-stable."""
    path = tmp_path / "events.jsonl"
    logger = EventLogger.to_path(str(path))
    logger.emit_roam(RoamEvent(
        timestamp=datetime(2026, 5, 18, 9, 30, tzinfo=timezone.utc),
        previous_bssid="aa:bb:cc:dd:ee:01", previous_channel=1,
        new_bssid="aa:bb:cc:dd:ee:02", new_channel=11,
    ))
    logger.emit_rf_stir(RFStirEvent(
        timestamp=datetime(2026, 5, 18, 9, 49, tzinfo=timezone.utc),
        bssid="aa:bb:cc:dd:ee:01", location="?aa:bb:cc",
        magnitude_db=4.8, duration_s=12.0,
        confidence="medium", mode="spatial_channel",
    ))
    logger.close()
    rows = _read_jsonl(path)
    roam_row = rows[0]
    rf_stir_row = rows[1]
    assert "previous_ssid" not in roam_row
    assert "new_ssid" not in roam_row
    assert "ssid" not in rf_stir_row


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
    """`diting --log` (no path) generates a timestamped filename
    in the current directory. The format must be filesystem-safe
    on macOS / Linux / case-insensitive shares — no colons —
    and end in .jsonl so editors / log shippers recognise it."""
    from diting.cli import _default_log_path
    name = _default_log_path()
    assert name.startswith("diting-")
    assert name.endswith(".jsonl")
    assert ":" not in name
    # Includes a date-time block: YYYYMMDD-HHMMSS sandwiched between
    # the prefix and the extension. The exact value is "now" so we
    # can't assert it equals anything; just sanity-check the shape.
    middle = name[len("diting-"):-len(".jsonl")]
    assert "-" in middle
    date_part, time_part = middle.split("-", 1)
    assert len(date_part) == 8 and date_part.isdigit()
    assert len(time_part) == 6 and time_part.isdigit()


def test_resolve_log_path_cli_no_value_uses_default():
    """The CLI flag without a path → timestamped default. This is
    the user-friendly opt-in path: type `--log` and a sensible
    file appears in your current directory."""
    from diting.cli import _LOG_DEFAULT, _resolve_log_path
    resolved = _resolve_log_path(_LOG_DEFAULT)
    assert resolved is not None
    assert resolved.startswith("diting-")
    assert resolved.endswith(".jsonl")


def test_resolve_log_path_cli_explicit_path_wins(tmp_path, monkeypatch):
    """An explicit CLI path overrides everything else, including a
    set DITING_LOG env var that would otherwise have applied."""
    from diting.cli import _resolve_log_path
    monkeypatch.setenv("DITING_LOG", "/should/be/ignored.jsonl")
    explicit = str(tmp_path / "my.jsonl")
    assert _resolve_log_path(explicit) == explicit


def test_resolve_log_path_env_auto_uses_default(monkeypatch):
    """``DITING_LOG=auto`` is the env-var equivalent of bare
    ``--log`` — useful for cron / launchd plists where positional
    flags are awkward."""
    from diting.cli import _resolve_log_path
    monkeypatch.setenv("DITING_LOG", "auto")
    resolved = _resolve_log_path(None)
    assert resolved is not None
    assert resolved.startswith("diting-")


def test_resolve_log_path_env_blank_disables(monkeypatch):
    """Blank env var means off, even if a parent shell set the
    var globally. Lets users disable logging for one invocation
    with ``DITING_LOG= diting`` without unsetting their
    profile-level config."""
    from diting.cli import _resolve_log_path
    monkeypatch.setenv("DITING_LOG", "")
    assert _resolve_log_path(None) is None


def test_extract_log_arg_no_value_returns_sentinel():
    """`--log` followed by a subcommand or another flag (or
    nothing) parses as the no-value sentinel. Path-form still
    works alongside the sentinel form."""
    from diting.cli import _LOG_DEFAULT, _extract_log_arg
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


# ------------------------------------------------------------------
# session_meta — the JSONL session header
# ------------------------------------------------------------------

def test_session_meta_writes_header_with_all_fields(tmp_path):
    """emit_session_meta produces a single JSONL line carrying every
    field documented in the event-log spec."""
    path = tmp_path / "events.jsonl"
    logger = EventLogger.to_path(str(path))
    logger.emit_session_meta(
        scene="office", scene_source="cli",
        ssid="Meituan", gateway_ip="11.10.128.1",
    )
    logger.close()
    rows = _read_jsonl(path)
    assert len(rows) == 1
    meta = rows[0]
    assert meta["type"] == "session_meta"
    assert meta["scene"] == "office"
    assert meta["scene_source"] == "cli"
    assert meta["ssid"] == "Meituan"
    assert meta["gateway_ip"] == "11.10.128.1"
    # diting_version must be present and look like a version string.
    assert "diting_version" in meta
    assert isinstance(meta["diting_version"], str)
    # hostname comes from socket.gethostname() — just assert it's
    # populated and a string; we don't assert specific values
    # because tests run on heterogeneous machines.
    assert isinstance(meta["hostname"], str)
    assert len(meta["hostname"]) > 0
    # Timestamp must be ISO-8601 with explicit offset, matching the
    # rest of the JSONL stream.
    from datetime import datetime as _dt
    ts = _dt.fromisoformat(meta["ts"])
    assert ts.utcoffset() is not None


def test_session_meta_is_first_when_emitted_first(tmp_path):
    """The CLI calls emit_session_meta immediately after constructing
    the logger; subsequent event emits land below it. Order matters
    because downstream tools read line 1 expecting the session
    header."""
    path = tmp_path / "events.jsonl"
    logger = EventLogger.to_path(str(path))
    logger.emit_session_meta(scene="home", scene_source="default")
    logger.emit_latency_spike(LatencySpikeEvent(
        timestamp=datetime(2026, 5, 22, 12, 0, 0, tzinfo=timezone.utc),
        target="router", target_ip="192.168.1.1",
        rtt_ms=300.0, loss_pct=0.0,
    ))
    logger.close()
    rows = _read_jsonl(path)
    assert rows[0]["type"] == "session_meta"
    assert rows[1]["type"] == "latency_spike"


def test_session_meta_is_idempotent(tmp_path):
    """A second emit_session_meta call on the same logger is a no-op.
    Lets caller paths invoke it unconditionally without risking
    duplicate headers in the JSONL."""
    path = tmp_path / "events.jsonl"
    logger = EventLogger.to_path(str(path))
    logger.emit_session_meta(scene="home", scene_source="default")
    logger.emit_session_meta(scene="office", scene_source="cli")
    logger.close()
    rows = _read_jsonl(path)
    assert len(rows) == 1
    # The first call wins — the second is silently dropped.
    assert rows[0]["scene"] == "home"


def test_session_meta_disabled_logger_is_no_op():
    """The TUI uses .disabled() when --log is off; emit_session_meta
    must be safe to call unconditionally."""
    logger = EventLogger.disabled()
    # Must not raise.
    logger.emit_session_meta(scene="home", scene_source="default")


def test_session_meta_accepts_null_ssid_and_gateway(tmp_path):
    """If diting launches before the first Wi-Fi connection lands,
    SSID and gateway are not yet known. They MUST be writable as
    null without skipping the field — downstream consumers want to
    distinguish 'not known' from 'not measured'."""
    path = tmp_path / "events.jsonl"
    logger = EventLogger.to_path(str(path))
    logger.emit_session_meta(scene="home", scene_source="default")
    logger.close()
    rows = _read_jsonl(path)
    assert rows[0]["ssid"] is None
    assert rows[0]["gateway_ip"] is None


# ------------------------------------------------------------------
# Familiarity / baseline integration (add-familiarity-baseline)
# ------------------------------------------------------------------

from diting.events import (  # noqa: E402
    BLEDeviceLeftEvent,
    BLEDeviceSeenEvent,
    BonjourServiceSeenEvent,
    LANHostSeenEvent,
)
from diting.familiarity import (  # noqa: E402
    FIRST_TIME,
    HABITUAL,
    FamiliarityStore,
)


def _ble_seen(ts, *, ident="ROT-1", vendor_id=0x0157, mfg="0157a1b2c3d4"):
    return BLEDeviceSeenEvent(
        timestamp=ts, identifier=ident, name="band", vendor="Huami",
        rssi_dbm=-60, service_categories=(),
        vendor_id=vendor_id, manufacturer_hex=mfg,
    )


def test_ble_seen_omits_familiarity_without_a_store(tmp_path):
    """No store wired → the field never appears, JSONL stays byte-stable
    against pre-familiarity consumers."""
    path = tmp_path / "events.jsonl"
    logger = EventLogger.to_path(str(path))
    logger.emit_ble_device_seen(
        _ble_seen(datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc)),
    )
    logger.close()
    row = _read_jsonl(path)[0]
    assert "familiarity" not in row


def test_ble_seen_first_sighting_is_first_time(tmp_path):
    path = tmp_path / "events.jsonl"
    store = FamiliarityStore(tmp_path / "fam.json")
    logger = EventLogger.to_path(str(path))
    logger.set_familiarity_store(store)
    logger.emit_ble_device_seen(
        _ble_seen(datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc)),
    )
    logger.close()
    row = _read_jsonl(path)[0]
    assert row["familiarity"] == FIRST_TIME


def test_ble_familiarity_keys_on_payload_not_rotating_id(tmp_path):
    """The same physical device under a fresh rotating identifier each day
    must be recognised — keyed on the manufacturer payload, classified
    habitual once seen on enough distinct days."""
    path = tmp_path / "events.jsonl"
    store = FamiliarityStore(tmp_path / "fam.json")
    logger = EventLogger.to_path(str(path))
    logger.set_familiarity_store(store)
    for day, ident in enumerate(("ROT-A", "ROT-B", "ROT-C", "ROT-D"), start=1):
        logger.emit_ble_device_seen(_ble_seen(
            datetime(2026, 6, day, 9, 0, tzinfo=timezone.utc),
            ident=ident,  # different rotating UUID every day
        ))
    logger.close()
    classes = [r["familiarity"] for r in _read_jsonl(path)]
    assert classes[0] == FIRST_TIME
    # By the 4th distinct day (>= _HABITUAL_DAYS) the device is habitual.
    assert classes[-1] == HABITUAL


def test_ble_left_folds_dwell_under_payload_key(tmp_path):
    store = FamiliarityStore(tmp_path / "fam.json")
    logger = EventLogger.disabled()
    logger.set_familiarity_store(store)
    ts = datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc)
    logger.emit_ble_device_seen(_ble_seen(ts))
    logger.emit_ble_device_left(BLEDeviceLeftEvent(
        timestamp=ts, identifier="ROT-1", name="band", vendor="Huami",
        last_rssi_dbm=-60, service_categories=(), seen_for_seconds=42.0,
        vendor_id=0x0157, manufacturer_hex="0157a1b2c3d4",
    ))
    rec = store.record("ble:0157a1b2c3d4")
    assert rec is not None
    assert rec.dwell_ewma_s == 42.0


def test_baseline_accrues_even_when_logging_disabled(tmp_path):
    """A disabled logger still feeds the store so the baseline keeps
    building across --log-off sessions."""
    store = FamiliarityStore(tmp_path / "fam.json")
    logger = EventLogger.disabled()
    logger.set_familiarity_store(store)
    logger.emit_ble_device_seen(
        _ble_seen(datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc)),
    )
    assert store.record("ble:0157a1b2c3d4") is not None


def test_lan_seen_carries_familiarity_keyed_on_mac(tmp_path):
    path = tmp_path / "events.jsonl"
    store = FamiliarityStore(tmp_path / "fam.json")
    logger = EventLogger.to_path(str(path))
    logger.set_familiarity_store(store)
    logger.emit_lan_host_seen(LANHostSeenEvent(
        timestamp=datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc),
        mac="DE:AD:BE:EF:00:01", ip="192.168.1.5", vendor="Apple, Inc.",
        hostname=None, bonjour_name=None, is_randomised_mac=False,
    ))
    logger.close()
    row = _read_jsonl(path)[0]
    assert row["familiarity"] == FIRST_TIME
    assert store.record("lan:de:ad:be:ef:00:01") is not None


def test_bonjour_seen_carries_familiarity(tmp_path):
    path = tmp_path / "events.jsonl"
    store = FamiliarityStore(tmp_path / "fam.json")
    logger = EventLogger.to_path(str(path))
    logger.set_familiarity_store(store)
    logger.emit_bonjour_service_seen(BonjourServiceSeenEvent(
        timestamp=datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc),
        service_type="_airplay._tcp", name="Living Room", host=None,
        category="media", vendor=None, addresses=("192.168.1.9",),
    ))
    logger.close()
    row = _read_jsonl(path)[0]
    assert row["familiarity"] == FIRST_TIME


def test_roam_carries_ap_familiarity_on_new_bssid(tmp_path):
    path = tmp_path / "events.jsonl"
    store = FamiliarityStore(tmp_path / "fam.json")
    logger = EventLogger.to_path(str(path))
    logger.set_familiarity_store(store)
    ev = RoamEvent(
        timestamp=datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc),
        previous_bssid="40:fe:95:8a:3c:58", previous_channel=1,
        new_bssid="1C:28:AF:5E:A7:14", new_channel=161,
    )
    logger.emit_roam(ev)
    logger.close()
    row = _read_jsonl(path)[0]
    assert row["familiarity"] == FIRST_TIME
    # Keyed on the lower-cased AP roamed TO.
    assert store.record("ap:1c:28:af:5e:a7:14") is not None


# ------------------------------------------------------------------
# Salience stamping (add-event-salience)
# ------------------------------------------------------------------

def test_emit_stamps_salience_on_scored_event(tmp_path):
    """A loss_burst is intrinsically high-salience; the JSONL carries it."""
    path = tmp_path / "events.jsonl"
    logger = EventLogger.to_path(str(path))
    logger.emit_loss_burst(LossBurstEvent(
        timestamp=datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc),
        target="gateway", target_ip="192.168.1.1", loss_pct=20.0,
        lost_in_window=4,
    ))
    logger.close()
    row = _read_jsonl(path)[0]
    assert row["salience"] == "high"


def test_emit_omits_salience_on_unscored_event(tmp_path):
    """session_meta is not scored → no salience key."""
    path = tmp_path / "events.jsonl"
    logger = EventLogger.to_path(str(path))
    logger.emit_session_meta(scene="home", scene_source="default")
    logger.close()
    row = _read_jsonl(path)[0]
    assert "salience" not in row


def test_first_time_ble_seen_salience_reflects_familiarity(tmp_path):
    """The salience stamp reads the familiarity stamped just upstream in the
    same emit — a first-time close device is high."""
    path = tmp_path / "events.jsonl"
    store = FamiliarityStore(tmp_path / "fam.json")
    logger = EventLogger.to_path(str(path))
    logger.set_familiarity_store(store)
    logger.emit_ble_device_seen(BLEDeviceSeenEvent(
        timestamp=datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc),
        identifier="ROT-1", name="band", vendor="Huami", rssi_dbm=-50,
        service_categories=(), vendor_id=0x0157, manufacturer_hex="0157a1b2c3d4",
    ))
    logger.close()
    row = _read_jsonl(path)[0]
    assert row["familiarity"] == "first_time"
    assert row["salience"] == "high"


# ------------------------------------------------------------------
# Insight events + multi-observer (add-insight-events)
# ------------------------------------------------------------------

from diting.events import InsightEvent  # noqa: E402


def test_emit_insight_writes_code_severity_and_detail(tmp_path):
    path = tmp_path / "events.jsonl"
    logger = EventLogger.to_path(str(path))
    logger.emit_insight(InsightEvent(
        timestamp=datetime(2026, 6, 2, 12, 0, tzinfo=timezone.utc),
        code="new_device_cluster", severity="note", detail={"count": 4},
    ))
    logger.close()
    row = _read_jsonl(path)[0]
    assert row["type"] == "insight"
    assert row["code"] == "new_device_cluster"
    assert row["severity"] == "note"
    # detail rides as a nested object, mirroring the companion-protocol wire.
    assert row["detail"] == {"count": 4}
    # Salience is stamped from severity (note -> notable).
    assert row["salience"] == "notable"


def test_emit_insight_omits_detail_when_absent(tmp_path):
    path = tmp_path / "events.jsonl"
    logger = EventLogger.to_path(str(path))
    logger.emit_insight(InsightEvent(
        timestamp=datetime(2026, 6, 2, 12, 0, tzinfo=timezone.utc),
        code="latency_without_loss", severity="note",
    ))
    logger.close()
    row = _read_jsonl(path)[0]
    assert set(row) == {"ts", "type", "code", "severity", "salience"}


def test_warn_insight_salience_is_high(tmp_path):
    path = tmp_path / "events.jsonl"
    logger = EventLogger.to_path(str(path))
    logger.emit_insight(InsightEvent(
        timestamp=datetime(2026, 6, 2, 12, 0, tzinfo=timezone.utc),
        code="loss_observed", severity="warn", detail={"peak_loss_pct": 30.0},
    ))
    logger.close()
    assert _read_jsonl(path)[0]["salience"] == "high"


def test_multiple_observers_all_receive_payload():
    a, b = [], []
    logger = EventLogger.disabled()
    logger.add_observer(a.append)
    logger.add_observer(b.append)
    logger.emit_insight(InsightEvent(
        timestamp=datetime(2026, 6, 2, 12, 0, tzinfo=timezone.utc),
        code="band_steering", severity="info",
    ))
    assert len(a) == 1 and len(b) == 1
    assert a[0]["code"] == "band_steering"


def test_set_observer_leaves_added_observers_intact():
    primary, extra = [], []
    logger = EventLogger.disabled()
    logger.add_observer(extra.append)        # e.g. the insight engine
    logger.set_observer(primary.append)      # e.g. the companion sink
    logger.emit_loss_burst(LossBurstEvent(
        timestamp=datetime(2026, 6, 2, 12, 0, tzinfo=timezone.utc),
        target="g", target_ip="10.0.0.1", loss_pct=5.0, lost_in_window=3,
    ))
    assert len(primary) == 1 and len(extra) == 1
    # Re-pair: swapping the primary must not drop the extra observer.
    primary2 = []
    logger.set_observer(primary2.append)
    logger.emit_loss_burst(LossBurstEvent(
        timestamp=datetime(2026, 6, 2, 12, 0, 1, tzinfo=timezone.utc),
        target="g", target_ip="10.0.0.1", loss_pct=5.0, lost_in_window=3,
    ))
    assert len(primary) == 1      # old primary no longer receives
    assert len(primary2) == 1
    assert len(extra) == 2        # extra still receiving
