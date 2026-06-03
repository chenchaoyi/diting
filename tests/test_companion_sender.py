"""Desktop companion sender tests — crypto, pairing state, push policy,
relay client (queue/flush), and the sink that joins them."""

from __future__ import annotations

import json

import pytest

from diting._watchdog import WatchdogConfig
from diting.companion import state as state_mod
from diting.companion.crypto import open_envelope, seal_event
from diting.companion.protocol import pairing
from diting.companion.protocol.errors import ProtocolError
from diting.companion.push_policy import PushPolicy
from diting.companion.push_summary import push_summary
from diting.companion.relay_client import RelayClient
from diting.companion.sink import CompanionSink
from diting.companion.state import PairingState, clear_state, load_state, render_qr


def test_event_logger_observer_sees_exact_written_payload():
    import io
    from datetime import datetime, timezone

    from diting.event_log import EventLogger
    from diting.events import LatencySpikeEvent

    seen: list = []
    buf = io.StringIO()
    log = EventLogger(buf, owns_sink=False)
    log.set_observer(seen.append)
    log.emit_latency_spike(LatencySpikeEvent(
        timestamp=datetime(2026, 5, 20, 4, 0, 0, tzinfo=timezone.utc),
        target="router", target_ip="192.168.1.1", rtt_ms=250.5, loss_pct=0.0,
    ))
    written = json.loads(buf.getvalue().strip())
    assert seen == [written]  # observer gets exactly what is logged


def test_event_logger_observer_fires_without_a_sink():
    from datetime import datetime, timezone

    from diting.event_log import EventLogger
    from diting.events import LossBurstEvent

    seen: list = []
    log = EventLogger.disabled()  # no file sink, e.g. TUI default
    log.set_observer(seen.append)
    log.emit_loss_burst(LossBurstEvent(
        timestamp=datetime(2026, 5, 20, 4, 0, 0, tzinfo=timezone.utc),
        target="wan", target_ip="8.8.8.8", loss_pct=20.0, lost_in_window=3,
    ))
    assert len(seen) == 1 and seen[0]["type"] == "loss_burst"


def _lan_seen(mac="de:ad:be:ef:00:01"):
    return {
        "ts": "2026-05-20T12:00:00+08:00",
        "type": "lan_host_seen",
        "mac": mac,
        "ip": "192.168.1.42",
        "is_randomised_mac": False,
        "vendor": "Apple, Inc.",
        "hostname": "客厅设备.local",
    }


# ---------- crypto ----------

def test_seal_open_round_trip():
    key = bytes(range(32))
    payload = _lan_seen()
    env = seal_event(key, channel="c", seq=1, ts="2026-05-20T12:00:00+08:00", payload=payload)
    assert env["v"] == 1 and env["ch"] == "c" and env["seq"] == 1
    assert open_envelope(key, env) == payload


def test_open_rejects_tampered_ciphertext():
    key = bytes(range(32))
    env = seal_event(key, channel="c", seq=1, ts="2026-05-20T12:00:00+08:00", payload=_lan_seen())
    env["ct"] = env["ct"][:-4] + ("AAAA" if not env["ct"].endswith("AAAA") else "BBBB")
    with pytest.raises(ProtocolError):
        open_envelope(key, env)


def test_open_rejects_wrong_key():
    env = seal_event(bytes(range(32)), channel="c", seq=1, ts="t+", payload=_lan_seen())
    with pytest.raises(ProtocolError):
        open_envelope(bytes([7]) * 32, env)


def test_seal_rejects_bad_key_length():
    with pytest.raises(ProtocolError):
        seal_event(b"short", channel="c", seq=1, ts="t", payload=_lan_seen())


# ---------- pairing state ----------

def test_generate_state_is_well_formed():
    st = PairingState.generate("https://relay.example")
    assert len(st.key_bytes()) == 32
    decoded = pairing.decode_pairing(st.qr_uri())
    assert decoded.channel == st.channel
    assert decoded.key_bytes() == st.key_bytes()
    assert st.relay_token() == st.relay_token()  # deterministic


def test_state_save_load_round_trip(tmp_path):
    path = tmp_path / "companion.json"
    st = PairingState.generate("https://relay.example")
    st.save(path)
    loaded = load_state(path)
    assert loaded.channel == st.channel
    assert loaded.key_b64 == st.key_b64
    assert loaded.last_seq == 0


def test_next_seq_persists_monotonically(tmp_path):
    path = tmp_path / "companion.json"
    st = PairingState.generate("https://relay.example")
    st.save(path)
    assert st.next_seq(path) == 1
    assert st.next_seq(path) == 2
    assert load_state(path).last_seq == 2  # survived to disk


def test_load_absent_is_none_and_clear(tmp_path):
    path = tmp_path / "companion.json"
    assert load_state(path) is None
    assert clear_state(path) is False
    PairingState.generate("https://relay.example").save(path)
    assert clear_state(path) is True
    assert load_state(path) is None


def test_render_qr_produces_block_art():
    art = render_qr("diting-pair://v1/abc?k=x&relay=https://r")
    assert art.strip()
    assert any(ch in art for ch in "█▀▄ ")


def test_default_state_path_env_override(monkeypatch, tmp_path):
    target = tmp_path / "elsewhere.json"
    monkeypatch.setenv("DITING_COMPANION_STATE", str(target))
    assert state_mod.default_state_path() == target


# ---------- push policy ----------

def test_policy_skips_non_pushable_types():
    p = PushPolicy()
    assert not p.should_push({"type": "session_meta"}, now=1.0)
    assert not p.should_push({"type": "ble_device_left", "identifier": "x"}, now=1.0)


def test_policy_forwards_insight_salience_gated():
    # forward-insights-over-companion: insights are now push-worthy, gated by
    # salience. A warn/critical/note insight (salience notable/high) forwards;
    # an info insight (salience noise) is dropped by the default `low` floor.
    p = PushPolicy()
    warn = {"type": "insight", "code": "loss_observed", "severity": "warn", "salience": "high"}
    info = {"type": "insight", "code": "band_steering", "severity": "info", "salience": "noise"}
    assert p.should_push(warn, now=1.0) is True
    assert p.should_push(info, now=2.0) is False


def test_policy_insight_silence_window_keyed_per_code():
    p = PushPolicy(config=WatchdogConfig(silence_window_s=60))
    a = {"type": "insight", "code": "evil_twin", "severity": "critical", "salience": "high"}
    b = {"type": "insight", "code": "deauth_storm", "severity": "critical", "salience": "high"}
    assert p.should_push(a, now=10.0) is True
    assert p.should_push(a, now=20.0) is False   # same code, within window
    assert p.should_push(b, now=20.0) is True    # distinct code fires


def test_policy_silence_window_coalesces_same_target():
    p = PushPolicy(config=WatchdogConfig(silence_window_s=60))
    ev = _lan_seen()
    assert p.should_push(ev, now=100.0) is True
    assert p.should_push(ev, now=130.0) is False  # within window
    assert p.should_push(ev, now=170.0) is True   # window elapsed


def test_policy_distinct_targets_independent():
    p = PushPolicy(config=WatchdogConfig(silence_window_s=60))
    assert p.should_push(_lan_seen("aa:aa:aa:aa:aa:aa"), now=10.0)
    assert p.should_push(_lan_seen("bb:bb:bb:bb:bb:bb"), now=10.0)


def test_policy_rf_stir_confidence_gate():
    p = PushPolicy(config=WatchdogConfig(silence_window_s=60, stir_confidence="high"))
    low = {"type": "rf_stir", "confidence": "low", "location": "L"}
    high = {"type": "rf_stir", "confidence": "high", "location": "L"}
    assert p.should_push(low, now=1.0) is False
    assert p.should_push(high, now=2.0) is True


def test_policy_salience_gate_suppresses_noise():
    # A habitual arrival stamped `noise` is dropped even though its type is
    # push-worthy — this is the flood fix.
    p = PushPolicy(min_salience="low")
    ev = _lan_seen()
    ev["salience"] = "noise"
    assert p.should_push(ev, now=1.0) is False


def test_policy_salience_gate_passes_when_field_absent():
    # No salience field (no familiarity store, or pre-Phase-2 log) → no-op
    # pass-through, preserving prior behaviour.
    p = PushPolicy(min_salience="notable")
    assert p.should_push(_lan_seen(), now=1.0) is True


def test_policy_salience_threshold_override():
    p = PushPolicy(min_salience="notable")
    low = _lan_seen("aa:aa:aa:aa:aa:aa")
    low["salience"] = "low"
    notable = _lan_seen("bb:bb:bb:bb:bb:bb")
    notable["salience"] = "notable"
    assert p.should_push(low, now=1.0) is False     # below the raised bar
    assert p.should_push(notable, now=1.0) is True  # meets it


def test_policy_min_salience_reads_env(monkeypatch):
    monkeypatch.setenv("DITING_PUSH_MIN_SALIENCE", "notable")
    p = PushPolicy()
    ev = _lan_seen()
    ev["salience"] = "low"
    assert p.should_push(ev, now=1.0) is False


# ---------- relay client ----------

class _FakeTransport:
    def __init__(self, status=200):
        self.calls = []
        self._status = status

    def __call__(self, url, headers, body):
        self.calls.append({"url": url, "headers": headers, "body": json.loads(body)})
        return self._status(len(self.calls)) if callable(self._status) else self._status


def _client(transport, **kw):
    return RelayClient("https://r.example/", "chan-1", "tok", transport=transport, **kw)


def test_flush_sends_all_in_order_on_success():
    tx = _FakeTransport(200)
    c = _client(tx)
    for s in (1, 2, 3):
        c.enqueue({"v": 1, "ch": "chan-1", "seq": s, "ts": "t", "n": "n", "ct": "c"})
    report = c.flush()
    assert report.sent == 3 and report.pending == 0
    assert [call["body"]["seq"] for call in tx.calls] == [1, 2, 3]
    assert tx.calls[0]["url"] == "https://r.example/v1/channel/chan-1"
    assert tx.calls[0]["headers"]["authorization"] == "Bearer tok"


def test_flush_stops_and_preserves_order_on_failure():
    # First POST 200, second 500 -> sent 1, two left queued.
    tx = _FakeTransport(lambda n: 200 if n == 1 else 500)
    c = _client(tx)
    for s in (1, 2, 3):
        c.enqueue({"seq": s})
    report = c.flush()
    assert report.sent == 1 and report.pending == 2
    # Retry once relay recovers.
    tx._status = 200
    report2 = c.flush()
    assert report2.sent == 2 and report2.pending == 0


def test_queue_overflow_drops_oldest_and_counts():
    c = _client(_FakeTransport(200), max_queue=2)
    for s in (1, 2, 3):
        c.enqueue({"seq": s})
    assert c.dropped == 1 and c.pending == 2  # seq 1 dropped


def test_category_header_forwarded():
    tx = _FakeTransport(200)
    c = _client(tx)
    c.enqueue({"seq": 1}, category="lan")
    c.flush()
    assert tx.calls[0]["headers"]["X-Diting-Category"] == "lan"


def test_summary_rides_as_push_sibling_without_touching_envelope():
    tx = _FakeTransport(200)
    c = _client(tx)
    env = {"v": 1, "ch": "chan-1", "seq": 1, "ts": "t", "n": "n", "ct": "c"}
    c.enqueue(dict(env), category="ble", summary="BLE nearby: 客厅电视")
    c.flush()
    body = tx.calls[0]["body"]
    # Envelope fields stay top-level; the summary is a separate `push`.
    assert {k: body[k] for k in env} == env
    assert body["push"] == {"body": "BLE nearby: 客厅电视", "category": "ble"}


def test_no_push_sibling_when_no_summary_or_category():
    tx = _FakeTransport(200)
    c = _client(tx)
    c.enqueue({"v": 1, "ch": "c", "seq": 1, "ts": "t", "n": "n", "ct": "c"})
    c.flush()
    assert "push" not in tx.calls[0]["body"]


# ---------- push summary ----------

def test_push_summary_is_specific_per_type():
    assert push_summary(_lan_seen()) == "New on Wi-Fi: 客厅设备.local"
    assert push_summary({"type": "roam", "new_bssid": "aa:bb:cc:dd:ee:ff"}) == "Roamed to aa:bb:cc:dd:ee:ff"
    assert push_summary({"type": "ble_device_seen", "name": "Magic Keyboard"}) == "BLE nearby: Magic Keyboard"
    spike = {"type": "latency_spike", "target_ip": "192.168.1.1", "rtt_ms": 250}
    assert push_summary(spike) == "Latency spike on 192.168.1.1: 250 ms"


def test_push_summary_falls_back_to_a_label_then_type():
    # No name/vendor/identifier -> placeholder, never a crash.
    assert push_summary({"type": "ble_device_seen"}) == "BLE nearby: ?"
    assert push_summary({"type": "session_meta"}) == "session_meta"


# ---------- sink ----------

def test_sink_seals_pushable_event_and_advances_seq(tmp_path):
    path = tmp_path / "companion.json"
    st = PairingState.generate("https://r.example")
    st.save(path)
    tx = _FakeTransport(200)
    client = RelayClient(st.relay_url, st.channel, st.relay_token(), transport=tx)
    sink = CompanionSink(st, client, PushPolicy(), state_path=path)

    payload = _lan_seen()
    assert sink.offer(payload) is True
    assert client.pending == 1
    # The enqueued envelope decrypts back to the original payload.
    env, _cat, _summary = client._queue[0]
    assert open_envelope(st.key_bytes(), env) == payload
    assert env["seq"] == 1
    assert load_state(path).last_seq == 1


def test_sink_strips_familiarity_before_sealing(tmp_path):
    # `familiarity` is a desktop-local field; the sealed copy the phone
    # decrypts must not carry it (mobile runs strict validate_event, which
    # rejects unknown keys). The original dict is left untouched.
    path = tmp_path / "companion.json"
    st = PairingState.generate("https://r.example")
    st.save(path)
    tx = _FakeTransport(200)
    client = RelayClient(st.relay_url, st.channel, st.relay_token(), transport=tx)
    sink = CompanionSink(st, client, PushPolicy(), state_path=path)

    payload = _lan_seen()
    payload["familiarity"] = "first_time"
    payload["salience"] = "notable"
    assert sink.offer(payload) is True
    env, _cat, _summary = client._queue[0]
    sealed = open_envelope(st.key_bytes(), env)
    assert "familiarity" not in sealed
    assert "salience" not in sealed
    # Everything else survives.
    assert sealed["mac"] == payload["mac"]
    # Caller's dict is not mutated.
    assert payload["familiarity"] == "first_time"
    assert payload["salience"] == "notable"


def test_sink_declines_non_pushable(tmp_path):
    path = tmp_path / "companion.json"
    st = PairingState.generate("https://r.example")
    st.save(path)
    sink = CompanionSink(
        st,
        RelayClient(st.relay_url, st.channel, st.relay_token(), transport=_FakeTransport(200)),
        PushPolicy(),
        state_path=path,
    )
    assert sink.offer({"type": "session_meta"}) is False
    assert sink.client.pending == 0
    assert load_state(path).last_seq == 0  # seq not advanced


# ---------- per-envelope protocol version (forward-insights-over-companion) ----------

def test_seal_stamps_per_event_envelope_version():
    key = bytes(range(32))
    # An existing event type stays v1 so a v1-only consumer still receives it.
    lan = seal_event(key, channel="c", seq=1, ts="2026-06-03T12:00:00+08:00",
                     payload=_lan_seen())
    assert lan["v"] == 1
    # An insight rides a v2 envelope (a v1 consumer abstains on just these).
    insight_payload = {
        "ts": "2026-06-03T12:00:00+08:00", "type": "insight",
        "code": "evil_twin", "severity": "critical", "detail": {"ssid": "cafe"},
    }
    insight = seal_event(key, channel="c", seq=2, ts="2026-06-03T12:00:00+08:00",
                         payload=insight_payload)
    assert insight["v"] == 2
    # Round-trips back to the original insight object.
    assert open_envelope(key, insight) == insight_payload


def test_sink_forwards_and_seals_insight_as_v2(tmp_path):
    # End-to-end: a critical threat insight forwards, seals at v2, strips the
    # local-only salience field, and the doorbell summary is its one-liner.
    path = tmp_path / "companion.json"
    st = PairingState.generate("https://r.example")
    st.save(path)
    client = RelayClient(st.relay_url, st.channel, st.relay_token(), transport=_FakeTransport(200))
    sink = CompanionSink(st, client, PushPolicy(), state_path=path)
    payload = {
        "ts": "2026-06-03T12:00:00+08:00", "type": "insight", "code": "evil_twin",
        "severity": "critical", "detail": {"ssid": "cafe", "new_vendor": "TP-Link"},
        "salience": "high",
    }
    assert sink.offer(payload) is True
    env, cat, summary = client._queue[0]
    assert env["v"] == 2                      # insight rides a v2 envelope
    assert cat == "insight"
    assert "evil twin" in summary             # localised one-liner on the doorbell
    sealed = open_envelope(st.key_bytes(), env)
    assert sealed["type"] == "insight"
    assert "salience" not in sealed           # local-only field stripped
    assert sealed["detail"] == {"ssid": "cafe", "new_vendor": "TP-Link"}
