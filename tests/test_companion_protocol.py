"""companion-protocol contract tests.

Covers the canonical wire-contract artifacts: golden-fixture
reproducibility + drift, per-type coverage, event-shape validation
(accept + fail-closed), pairing encode/decode, envelope validation +
version tolerance, and the content-free APNs trigger.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from diting.companion import protocol
from diting.companion.protocol import apns, auth, envelope, pairing
from diting.companion.protocol._generate import generate
from diting.companion.protocol._schema_spec import EVENT_SPEC
from diting.companion.protocol.errors import ProtocolError
from diting.companion.protocol.events_schema import build_json_schema, validate_event
from diting.companion.protocol.version import PROTOCOL_VERSION, is_supported_version

_BASE = Path(protocol.__file__).resolve().parent
_FIXTURES = _BASE / "fixtures"


def _manifest() -> dict:
    return json.loads((_BASE / "manifest.json").read_text("utf-8"))


def _event_lines() -> list[dict]:
    text = (_FIXTURES / "events.jsonl").read_text(encoding="utf-8")
    return [json.loads(ln) for ln in text.splitlines() if ln.strip()]


# ---------- reproducibility + drift ----------

def test_committed_artifacts_match_generator(tmp_path):
    """Regenerating must reproduce the committed bytes exactly — nobody
    can hand-edit the vendored artifacts out of sync with the writer."""
    generate(tmp_path)
    rels = [*_manifest()["artifacts"], "manifest.json"]
    for rel in rels:
        regenerated = (tmp_path / rel).read_bytes()
        committed = (_BASE / rel).read_bytes()
        assert regenerated == committed, f"{rel} drifted from generator output"


def test_manifest_hashes_match_files():
    """The drift check the consumer runs: each artifact's sha256 equals
    the manifest entry."""
    manifest = _manifest()
    assert manifest["protocol_version"] == PROTOCOL_VERSION
    for rel, digest in manifest["artifacts"].items():
        actual = hashlib.sha256((_BASE / rel).read_bytes()).hexdigest()
        assert actual == digest, f"{rel} hash drifted"


def test_event_schema_on_disk_matches_builder():
    on_disk = json.loads((_BASE / "schema/event.schema.json").read_text("utf-8"))
    assert on_disk == build_json_schema()


# ---------- fixture coverage + validation ----------

def test_fixtures_cover_every_event_type():
    seen = {obj["type"] for obj in _event_lines()}
    assert seen == set(EVENT_SPEC), (
        f"missing fixtures for: {set(EVENT_SPEC) - seen}; "
        f"extra: {seen - set(EVENT_SPEC)}"
    )


def test_every_fixture_line_validates():
    for obj in _event_lines():
        assert validate_event(obj) is obj


def test_json_schema_has_one_branch_per_type():
    schema = build_json_schema()
    consts = {b["properties"]["type"]["const"] for b in schema["oneOf"]}
    assert consts == set(EVENT_SPEC)


# ---------- validate_event fails closed ----------

def test_validate_rejects_unknown_type():
    with pytest.raises(ProtocolError):
        validate_event({"ts": "2026-05-20T12:00:00+08:00", "type": "nope"})


def test_validate_rejects_missing_required():
    with pytest.raises(ProtocolError):
        validate_event({"ts": "2026-05-20T12:00:00+08:00", "type": "latency_spike",
                        "target": "router", "target_ip": "1.1.1.1", "rtt_ms": 9.0})


def test_validate_rejects_unknown_field():
    with pytest.raises(ProtocolError):
        validate_event({"ts": "2026-05-20T12:00:00+08:00", "type": "loss_burst",
                        "target": "wan", "target_ip": "8.8.8.8", "loss_pct": 1.0,
                        "lost_in_window": 3, "surprise": 1})


def test_validate_rejects_bad_enum():
    with pytest.raises(ProtocolError):
        validate_event({"ts": "2026-05-20T12:00:00+08:00", "type": "link_state",
                        "state": "sideways", "ssid": None, "bssid": None})


def test_validate_rejects_bad_timestamp():
    with pytest.raises(ProtocolError):
        validate_event({"ts": "2026-05-20 12:00:00Z", "type": "link_state",
                        "state": "associated", "ssid": "x", "bssid": "y"})


def test_validate_rejects_non_object():
    with pytest.raises(ProtocolError):
        validate_event(["not", "an", "object"])


# ---------- version tolerance ----------

def test_supported_version():
    assert is_supported_version(1)
    assert not is_supported_version(2)
    assert not is_supported_version(True)   # bool is not a version
    assert not is_supported_version("1")    # str is not a version
    assert not is_supported_version(None)


# ---------- pairing ----------

def test_pairing_round_trip():
    key = pairing.encode_key(bytes(range(32)))
    payload = pairing.PairingPayload(
        version=PROTOCOL_VERSION, channel="chan-1", key_b64=key,
        relay_url="https://relay.example", fingerprint="ab:cd",
    )
    decoded = pairing.decode_pairing(pairing.encode_pairing(payload))
    assert decoded == payload
    assert decoded.key_bytes() == bytes(range(32))


def test_committed_pairing_fixture_decodes():
    uri = (_FIXTURES / "pairing.txt").read_text("utf-8").strip()
    decoded = pairing.decode_pairing(uri)
    assert decoded.version == PROTOCOL_VERSION
    assert decoded.channel == "demo-channel"
    assert len(decoded.key_bytes()) == pairing.KEY_BYTES
    assert decoded.relay_url == "https://relay.diting.dev"


@pytest.mark.parametrize("bad", [
    "https://relay.example?k=x",                       # wrong scheme
    "diting-pair://v1/chan?relay=https://r.example",   # missing key
    "diting-pair://v1/chan?k=AAA&relay=https://r.x",   # key not 32 bytes
    "diting-pair://v9/chan?k=%s&relay=https://r.x" % pairing.encode_key(bytes(32)),  # unsupported version
    "diting-pair://v1/?k=%s&relay=https://r.x" % pairing.encode_key(bytes(32)),      # empty channel
])
def test_pairing_rejects_malformed(bad):
    with pytest.raises(ProtocolError):
        pairing.decode_pairing(bad)


def test_encode_key_rejects_wrong_length():
    with pytest.raises(ProtocolError):
        pairing.encode_key(b"too short")


# ---------- envelope ----------

def test_envelope_build_and_validate():
    env = envelope.build_envelope(
        version=PROTOCOL_VERSION, channel="c", seq=1,
        ts="2026-05-20T12:00:00+08:00", nonce_b64="bm9uY2U=", ciphertext_b64="Y3Q=",
    )
    assert envelope.validate_envelope(env) is env


@pytest.mark.parametrize("mutate", [
    lambda e: e.pop("ct"),                 # missing field
    lambda e: e.update(seq=0),             # seq < 1
    lambda e: e.update(seq="1"),           # seq not int
    lambda e: e.update(v=2),               # unsupported (future) version
    lambda e: e.update(ch=""),             # empty channel
])
def test_envelope_validate_fails_closed(mutate):
    env = envelope.build_envelope(
        version=PROTOCOL_VERSION, channel="c", seq=1,
        ts="2026-05-20T12:00:00+08:00", nonce_b64="n", ciphertext_b64="c",
    )
    mutate(env)
    with pytest.raises(ProtocolError):
        envelope.validate_envelope(env)


# ---------- APNs trigger ----------

def test_coarse_category_covers_pushable_types():
    for etype in EVENT_SPEC:
        cat = apns.coarse_category(etype)
        if etype == "session_meta":
            assert cat is None
        else:
            assert cat in apns.CATEGORIES


def test_trigger_is_content_free():
    trig = apns.build_trigger(channel="c", count=2, category="lan")
    assert set(trig) == {"ch", "n", "c"}  # no field can carry an identifier


@pytest.mark.parametrize("kwargs", [
    {"channel": "c", "count": 1, "category": "bogus"},
    {"channel": "c", "count": 0, "category": "ble"},
    {"channel": "", "count": 1, "category": "ble"},
])
def test_trigger_rejects_bad_input(kwargs):
    with pytest.raises(ProtocolError):
        apns.build_trigger(**kwargs)


def test_committed_trigger_fixture_shape():
    trig = json.loads((_FIXTURES / "apns-trigger.json").read_text("utf-8"))
    assert set(trig) == {"ch", "n", "c"}
    assert trig["c"] in apns.CATEGORIES


# ---------- relay auth token ----------

def test_relay_token_is_deterministic_and_key_bound():
    k = bytes(range(32))
    assert auth.derive_relay_token(k) == auth.derive_relay_token(k)
    other = bytes([255]) + bytes(range(1, 32))
    assert auth.derive_relay_token(k) != auth.derive_relay_token(other)


def test_relay_token_is_not_the_key():
    k = bytes(range(32))
    token = auth.derive_relay_token(k)
    # One-way: the relay seeing the token cannot recover the key bytes.
    assert k.hex() not in token
    assert pairing.encode_key(k) != token


def test_committed_relay_auth_fixture_matches_derivation():
    fx = json.loads((_FIXTURES / "relay-auth.json").read_text("utf-8"))
    key = pairing.decode_pairing(
        f"diting-pair://v{PROTOCOL_VERSION}/{fx['channel']}"
        f"?k={fx['key_b64']}&relay=https://r.example"
    ).key_bytes()
    assert auth.derive_relay_token(key) == fx["token"]
    assert auth.token_hash(fx["token"]) == fx["token_hash"]
