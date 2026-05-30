"""Generate the canonical protocol artifacts (schema + fixtures + manifest).

Run as ``python -m diting.companion.protocol._generate`` to (re)write the
committed artifacts under this package. The reproducibility test
re-invokes :func:`generate` into a temp dir and asserts byte-equality, so
the committed files can never be hand-edited out of sync with the writer.

Golden event fixtures are produced by the REAL
``diting.event_log.EventLogger`` against fixed inputs with the timezone
forced to ``Asia/Shanghai`` (so the local-TZ offset renders as a stable
``+08:00``). ``session_meta`` is the one line whose dynamic fields
(hostname, package version) are normalised to fixture-stable placeholders
after capture, since those are environment-derived.
"""

from __future__ import annotations

import hashlib
import io
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ..protocol import apns, pairing
from ..protocol.events_schema import build_json_schema
from ..protocol.version import PROTOCOL_VERSION
from ...event_log import EventLogger
from ...events import (
    BLEDeviceLeftEvent,
    BLEDeviceSeenEvent,
    BonjourServiceLeftEvent,
    BonjourServiceSeenEvent,
    LANActiveProbeConsentedEvent,
    LANHostDHCPRotationEvent,
    LANHostLeftEvent,
    LANHostSeenEvent,
    LatencySpikeEvent,
    LinkStateEvent,
    LossBurstEvent,
    NetworkChangeEvent,
    RFStirEvent,
)
from ...poller import RoamEvent

# A fixed instant rendered in a canonical +08:00 zone, so fixtures are
# reproducible on any host regardless of its clock zone. EventLogger._iso
# renders in system-local tz; we capture the real line then pin its `ts`
# to this canonical value (the format is identical: ``.astimezone(tz)
# .isoformat()``), the same normalisation used for session_meta's
# environment-derived fields.
_CANON_TZ = timezone(timedelta(hours=8))
_BASE = datetime(2026, 5, 20, 4, 0, 0, tzinfo=timezone.utc)
_FIXTURE_HOSTNAME = "mac-fixture"
_FIXTURE_VERSION = "0.0.0-fixture"


def _canon_ts(i: int) -> str:
    return (_BASE + timedelta(seconds=i)).astimezone(_CANON_TZ).isoformat()


def _ts(i: int) -> datetime:
    return _BASE + timedelta(seconds=i)


def _emit_event_lines() -> list[str]:
    """Run the real EventLogger over one constructed event per wire type,
    in EVENT_SPEC order, and return the captured JSONL lines."""
    buf = io.StringIO()
    log = EventLogger(buf, owns_sink=False)

    # 0 session_meta (dynamic fields normalised below)
    log.emit_session_meta(
        scene="home", scene_source="env_var",
        ssid="咖啡馆", gateway_ip="192.168.1.1", now=_ts(0),
    )
    # 1 link_state
    log.emit_link_state(LinkStateEvent(
        timestamp=_ts(1), state="associated",
        bssid="AA:BB:CC:DD:EE:01", ssid="咖啡馆",
    ))
    # 2 roam (exercises optional kind/ssid/vendor fields)
    log.emit_roam(
        RoamEvent(
            timestamp=_ts(2),
            previous_bssid="AA:BB:CC:DD:EE:01", previous_channel=36,
            new_bssid="AA:BB:CC:DD:EE:02", new_channel=149,
            previous_ssid="咖啡馆", new_ssid="咖啡馆",
        ),
        kind="inter_ap", ssid="咖啡馆",
        previous_vendor="Xiaomi, Inc.", new_vendor="Apple, Inc.",
    )
    # 3 rf_stir
    log.emit_rf_stir(RFStirEvent(
        timestamp=_ts(3), bssid="AA:BB:CC:DD:EE:01", location="2F-书房",
        magnitude_db=4.2, duration_s=5.0, confidence="high",
        mode="co_located", ssid="咖啡馆",
    ))
    # 4 latency_spike
    log.emit_latency_spike(LatencySpikeEvent(
        timestamp=_ts(4), target="router", target_ip="192.168.1.1",
        rtt_ms=250.5, loss_pct=0.0,
    ))
    # 5 loss_burst
    log.emit_loss_burst(LossBurstEvent(
        timestamp=_ts(5), target="wan", target_ip="8.8.8.8",
        loss_pct=20.0, lost_in_window=3,
    ))
    # 6 network_change
    log.emit_network_change(NetworkChangeEvent(
        timestamp=_ts(6),
        previous_router_ip="192.168.1.1", new_router_ip="10.0.0.1",
        previous_ssid="咖啡馆", new_ssid="Home",
        previous_bssid="AA:BB:CC:DD:EE:01", new_bssid="AA:BB:CC:DD:EE:09",
    ))
    # 7 ble_device_seen (all optionals + at_launch)
    log.emit_ble_device_seen(BLEDeviceSeenEvent(
        timestamp=_ts(7), identifier="abc123", name="Magic Keyboard",
        vendor="Apple, Inc.", rssi_dbm=-55, service_categories=("HID",),
        device_type="Find My target", device_class="iPhone", at_launch=True,
    ))
    # 8 ble_device_left (None-omit + empty [] categories)
    log.emit_ble_device_left(BLEDeviceLeftEvent(
        timestamp=_ts(8), identifier="abc123", name=None,
        vendor="Apple, Inc.", last_rssi_dbm=-60, service_categories=(),
        seen_for_seconds=300.5, device_type=None, device_class=None,
    ))
    # 9 bonjour_service_seen (CJK instance name)
    log.emit_bonjour_service_seen(BonjourServiceSeenEvent(
        timestamp=_ts(9), service_type="_airplay._tcp.local.",
        name="客厅电视._airplay._tcp.local.", host="Living-TV",
        category="AirPlay", vendor="Apple, Inc.", addresses=("192.168.1.42",),
    ))
    # 10 bonjour_service_left (None-omit)
    log.emit_bonjour_service_left(BonjourServiceLeftEvent(
        timestamp=_ts(10), service_type="_airplay._tcp.local.",
        name="客厅电视._airplay._tcp.local.", host=None, category=None,
        vendor=None, seen_for_seconds=7200.0,
    ))
    # 11 lan_host_seen
    log.emit_lan_host_seen(LANHostSeenEvent(
        timestamp=_ts(11), mac="DE:AD:BE:EF:00:01", ip="192.168.1.42",
        vendor="Apple, Inc.", hostname="my-mbp.local", bonjour_name="ccy-MBP",
        is_randomised_mac=False,
    ))
    # 12 lan_host_left (None-omit + last_reachable_ago_seconds present)
    log.emit_lan_host_left(LANHostLeftEvent(
        timestamp=_ts(12), mac="DE:AD:BE:EF:00:01", ip="192.168.1.42",
        vendor="Apple, Inc.", hostname=None, bonjour_name=None,
        is_randomised_mac=False, seen_for_seconds=3600.0,
        last_reachable_ago_seconds=120.5,
    ))
    # 13 lan_host_dhcp_rotation
    log.emit_lan_host_dhcp_rotation(LANHostDHCPRotationEvent(
        timestamp=_ts(13), mac="DE:AD:BE:EF:00:01",
        previous_ip="192.168.1.42", new_ip="192.168.1.77",
        vendor="Apple, Inc.", hostname="my-mbp.local", bonjour_name=None,
    ))
    # 14 lan_active_probe_consented
    log.emit_lan_active_probe_consented(LANActiveProbeConsentedEvent(
        timestamp=_ts(14), scene="public", ssid="HotelGuest",
        nbns_packets=8, ssdp_packets=1, mdns_packets=1,
    ))

    raw = buf.getvalue().splitlines()
    lines: list[str] = []
    for i, line in enumerate(raw):
        obj = json.loads(line)
        obj["ts"] = _canon_ts(i)  # pin timestamp deterministically
        if i == 0:  # session_meta: normalise environment-derived fields
            obj["diting_version"] = _FIXTURE_VERSION
            obj["hostname"] = _FIXTURE_HOSTNAME
        lines.append(json.dumps(obj, separators=(",", ":"), ensure_ascii=False))
    return lines


def _envelope_schema() -> dict[str, Any]:
    from ..protocol._schema_spec import TS_PATTERN
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://diting.dev/companion-protocol/v1/envelope.schema.json",
        "title": "diting companion-protocol relay envelope",
        "type": "object",
        "required": ["v", "ch", "seq", "ts", "n", "ct"],
        "additionalProperties": False,
        "properties": {
            "v": {"type": "integer", "enum": [PROTOCOL_VERSION]},
            "ch": {"type": "string", "minLength": 1},
            "seq": {"type": "integer", "minimum": 1},
            "ts": {"type": "string", "pattern": TS_PATTERN},
            "n": {"type": "string", "minLength": 1},
            "ct": {"type": "string", "minLength": 1},
        },
    }


def _pairing_schema() -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://diting.dev/companion-protocol/v1/pairing.schema.json",
        "title": "diting companion-protocol pairing payload (decoded form)",
        "description": (
            "The decoded form of the diting-pair:// QR URI. The key_b64 "
            "decodes to a 32-byte secretbox key and never reaches the relay."
        ),
        "type": "object",
        "required": ["version", "channel", "key_b64", "relay_url"],
        "additionalProperties": False,
        "properties": {
            "version": {"type": "integer", "enum": [PROTOCOL_VERSION]},
            "channel": {"type": "string", "minLength": 1},
            "key_b64": {"type": "string", "minLength": 1},
            "relay_url": {"type": "string", "format": "uri"},
            "fingerprint": {"type": ["string", "null"]},
        },
    }


def _apns_trigger_schema() -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://diting.dev/companion-protocol/v1/apns-trigger.schema.json",
        "title": "diting companion-protocol APNs trigger (content-free)",
        "type": "object",
        "required": ["ch", "n", "c"],
        "additionalProperties": False,
        "properties": {
            "ch": {"type": "string", "minLength": 1},
            "n": {"type": "integer", "minimum": 1},
            "c": {"type": "string", "enum": sorted(apns.CATEGORIES)},
        },
    }


def _dumps(obj: Any) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=False) + "\n"


def generate(base_dir: Path) -> dict[str, str]:
    """Write all artifacts under ``base_dir`` and return the manifest
    artifact->sha256 map. Output is reproducible on any host."""
    (base_dir / "schema").mkdir(parents=True, exist_ok=True)
    (base_dir / "fixtures").mkdir(parents=True, exist_ok=True)

    files: dict[str, str] = {
        "schema/event.schema.json": _dumps(build_json_schema()),
        "schema/envelope.schema.json": _dumps(_envelope_schema()),
        "schema/pairing.schema.json": _dumps(_pairing_schema()),
        "schema/apns-trigger.schema.json": _dumps(_apns_trigger_schema()),
        "fixtures/events.jsonl": "\n".join(_emit_event_lines()) + "\n",
    }

    # Example pairing URI + APNs trigger, deterministic.
    demo_key = pairing.encode_key(bytes(range(32)))
    pair_uri = pairing.encode_pairing(pairing.PairingPayload(
        version=PROTOCOL_VERSION, channel="demo-channel",
        key_b64=demo_key, relay_url="https://relay.diting.dev",
    ))
    files["fixtures/pairing.txt"] = pair_uri + "\n"
    files["fixtures/apns-trigger.json"] = _dumps(
        apns.build_trigger(channel="demo-channel", count=3, category="ble")
    )

    manifest_hashes: dict[str, str] = {}
    for rel, content in files.items():
        data = content.encode("utf-8")
        (base_dir / rel).write_bytes(data)
        manifest_hashes[rel] = hashlib.sha256(data).hexdigest()

    manifest = {
        "protocol_version": PROTOCOL_VERSION,
        "generated_by": "diting.companion.protocol._generate",
        "artifacts": manifest_hashes,
    }
    (base_dir / "manifest.json").write_bytes(_dumps(manifest).encode("utf-8"))
    return manifest_hashes


def main() -> None:
    base = Path(__file__).resolve().parent
    hashes = generate(base)
    print(f"wrote {len(hashes)} artifacts to {base}")
    for rel, digest in hashes.items():
        print(f"  {digest[:12]}  {rel}")


if __name__ == "__main__":
    main()
