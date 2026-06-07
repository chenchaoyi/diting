"""_dynamic_store — the SCDynamicStore CachedScanRecord fallback.

Hermetic: the SCDynamicStore* calls are monkeypatched; the
NSKeyedArchiver bplist is built with plistlib so the parse path runs
for real. The interesting contract is BSSID normalization — macOS
formats these octets without zero-padding (``3c:b``), which must heal
to the canonical spelling at this boundary.
"""

from __future__ import annotations

import plistlib

import diting._dynamic_store as ds


def _keyed_archive(fields: dict[str, object]) -> bytes:
    """A minimal NSKeyedArchiver-shaped bplist _resolve_ns_dict accepts."""
    objects: list[object] = ["$null"]
    keys, vals = [], []
    for k, v in fields.items():
        objects.append(k)
        keys.append(plistlib.UID(len(objects) - 1))
        objects.append(v)
        vals.append(plistlib.UID(len(objects) - 1))
    objects.append({"NS.keys": keys, "NS.objects": vals})
    root = plistlib.UID(len(objects) - 1)
    return plistlib.dumps(
        {"$top": {"root": root}, "$objects": objects},
        fmt=plistlib.FMT_BINARY,
    )


def test_cached_bssid_normalized(monkeypatch):
    csr = _keyed_archive({
        "BSSID": "40:fe:95:8a:3c:b",   # macOS's un-padded spelling
        "SSID_STR": "tedo_5G",
        "AGE": 100,
    })
    monkeypatch.setattr(ds, "SCDynamicStoreCreate", lambda *a: object())
    monkeypatch.setattr(
        ds, "SCDynamicStoreCopyValue",
        lambda store, key: {"CHANNEL": 157, "CachedScanRecord": csr},
    )
    out = ds.read_current_identity("en0")
    assert out.bssid == "40:fe:95:8a:3c:0b"  # healed
    assert out.ssid == "tedo_5G"
    assert out.channel == 157


def test_stale_record_ignored(monkeypatch):
    csr = _keyed_archive({
        "BSSID": "40:fe:95:8a:3c:0b",
        "SSID_STR": "tedo_5G",
        "AGE": 60_000,  # > _MAX_AGE_MS
    })
    monkeypatch.setattr(ds, "SCDynamicStoreCreate", lambda *a: object())
    monkeypatch.setattr(
        ds, "SCDynamicStoreCopyValue",
        lambda store, key: {"CHANNEL": 157, "CachedScanRecord": csr},
    )
    out = ds.read_current_identity("en0")
    assert out.bssid is None
    assert out.ssid is None
    assert out.channel == 157  # top-level field still trusted
