"""Single source of truth for the event wire shape.

Every entry mirrors exactly what ``diting.event_log.EventLogger`` emits
for that ``type`` (English keys, ``None`` fields omitted, empty tuples as
``[]``). ``events_schema.py`` reads this to validate events and to build
the vendored ``event.schema.json``; the fixture generator reads it for
coverage. Keep this in lockstep with ``EventLogger.emit_*`` — the
fixture reproducibility test fails loudly if they drift.

Field type tags::

    str        string
    int        integer (not bool)
    num        number (int or float, not bool)
    bool       boolean
    strarray   array of strings
    str|null   string or null (key always present, value may be null)
    int|null   integer or null
"""

from __future__ import annotations

# ISO-8601 with a required numeric offset (local-TZ + offset, never 'Z').
# Microseconds optional. Matches EventLogger._iso output.
TS_PATTERN = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?[+-]\d{2}:\d{2}$"

# type -> {"required": {field: tag}, "optional": {field: tag},
#          "enums": {field: [allowed, ...]}}
EVENT_SPEC: dict[str, dict[str, dict]] = {
    "session_meta": {
        "required": {
            "scene": "str",
            "scene_source": "str",
            "diting_version": "str",
            "ssid": "str|null",
            "gateway_ip": "str|null",
            "hostname": "str",
        },
        "optional": {},
        "enums": {},
    },
    "link_state": {
        "required": {"state": "str", "ssid": "str|null", "bssid": "str|null"},
        "optional": {"vendor": "str"},
        "enums": {"state": ["associated", "disassociated"]},
    },
    "roam": {
        "required": {
            "previous_bssid": "str|null",
            "new_bssid": "str|null",
            "previous_channel": "int|null",
            "new_channel": "int|null",
        },
        "optional": {
            "kind": "str",
            "ssid": "str",
            "previous_ssid": "str",
            "new_ssid": "str",
            "previous_vendor": "str",
            "new_vendor": "str",
        },
        "enums": {"kind": ["inter_ap", "band_switch"]},
    },
    "rf_stir": {
        "required": {
            "magnitude_db": "num",
            "location": "str|null",
            "bssid": "str|null",
            "duration_s": "num",
            "confidence": "str",
            "mode": "str",
        },
        "optional": {"ssid": "str"},
        "enums": {
            "confidence": ["low", "medium", "high"],
            "mode": ["co_located", "spatial_channel"],
        },
    },
    "latency_spike": {
        "required": {
            "target": "str",
            "target_ip": "str",
            "rtt_ms": "num",
            "loss_pct": "num",
        },
        "optional": {},
        "enums": {"target": ["router", "wan"]},
    },
    "loss_burst": {
        "required": {
            "target": "str",
            "target_ip": "str",
            "loss_pct": "num",
            "lost_in_window": "int",
        },
        "optional": {},
        "enums": {"target": ["router", "wan"]},
    },
    "network_change": {
        "required": {"previous_router_ip": "str|null", "new_router_ip": "str|null"},
        "optional": {
            "previous_ssid": "str",
            "new_ssid": "str",
            "previous_bssid": "str",
            "new_bssid": "str",
        },
        "enums": {},
    },
    "ble_device_seen": {
        "required": {"identifier": "str", "service_categories": "strarray"},
        "optional": {
            "name": "str",
            "vendor": "str",
            "rssi_dbm": "int",
            "device_type": "str",
            "device_class": "str",
            "at_launch": "bool",
        },
        "enums": {},
    },
    "ble_device_left": {
        "required": {
            "identifier": "str",
            "service_categories": "strarray",
            "seen_for_seconds": "num",
        },
        "optional": {
            "name": "str",
            "vendor": "str",
            "last_rssi_dbm": "int",
            "device_type": "str",
            "device_class": "str",
        },
        "enums": {},
    },
    "bonjour_service_seen": {
        "required": {
            "service_type": "str",
            "name": "str",
            "addresses": "strarray",
        },
        "optional": {"host": "str", "category": "str", "vendor": "str"},
        "enums": {},
    },
    "bonjour_service_left": {
        "required": {
            "service_type": "str",
            "name": "str",
            "seen_for_seconds": "num",
        },
        "optional": {"host": "str", "category": "str", "vendor": "str"},
        "enums": {},
    },
    "lan_host_seen": {
        "required": {"mac": "str", "ip": "str", "is_randomised_mac": "bool"},
        "optional": {"vendor": "str", "hostname": "str", "bonjour_name": "str"},
        "enums": {},
    },
    "lan_host_left": {
        "required": {
            "mac": "str",
            "ip": "str",
            "is_randomised_mac": "bool",
            "seen_for_seconds": "num",
        },
        "optional": {
            "vendor": "str",
            "hostname": "str",
            "bonjour_name": "str",
            "last_reachable_ago_seconds": "num",
        },
        "enums": {},
    },
    "lan_host_dhcp_rotation": {
        "required": {"mac": "str", "previous_ip": "str", "new_ip": "str"},
        "optional": {"vendor": "str", "hostname": "str", "bonjour_name": "str"},
        "enums": {},
    },
    "lan_active_probe_consented": {
        "required": {
            "scene": "str",
            "nbns_packets": "int",
            "ssdp_packets": "int",
            "mdns_packets": "int",
        },
        "optional": {"ssid": "str"},
        "enums": {},
    },
}

# Wire types that are not part of the in-memory EventRing but still appear
# as JSONL lines (and so in the report file). session_meta is the header;
# network_change is control-plane. Pushed-event gating is a separate concern.
HEADER_TYPES = frozenset({"session_meta"})
