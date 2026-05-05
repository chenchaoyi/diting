"""SCDynamicStore-based fallback for SSID and BSSID.

CoreWLAN's `bssid()` and `ssid()` are redacted to None on macOS 14.4+
when the host process lacks Location Services permission. The same
data is mirrored into SCDynamicStore at
`State:/Network/Interface/<iface>/AirPort`, where the top-level
`BSSID` and `SSID_STR` fields are also redacted (BSSID becomes the
placeholder `02:00:00:00:00:00`, SSID_STR becomes empty).

However, that dictionary also contains a `CachedScanRecord` field —
an NSKeyedArchiver-serialized bplist describing the AP we are
currently associated with — and **its** BSSID and SSID_STR fields
are NOT redacted. This is presumably an oversight; Apple may close
it in a future release. Until then it is a clean way to get real
identity data without bundling wifiscope as a `.app`.

The fallback fails gracefully: if the key is gone, the structure
shifts, or the cached record is too stale (`AGE` is reported in
milliseconds), we return None and the caller stays in the
"BSSID hidden" state it already handles.
"""

from __future__ import annotations

import plistlib

from SystemConfiguration import SCDynamicStoreCopyValue, SCDynamicStoreCreate

# macOS uses this as the placeholder when redacting BSSID. Any other
# locally-administered MAC starting with 02 is technically valid, so
# we only filter the exact placeholder value.
_REDACTED_BSSID = "02:00:00:00:00:00"

# Reject scan records older than this. macOS in practice updates
# CachedScanRecord on the order of a second or two; anything stale
# is more likely to misrepresent post-roam state.
_MAX_AGE_MS = 30_000


def read_current_identity(interface_name: str) -> tuple[str | None, str | None]:
    """Return (bssid, ssid) for the currently associated AP, or (None, None).

    Pure read — does not require any permission grant. Safe to call on
    every poll tick (cheap; a single SCDynamicStore lookup plus a small
    bplist parse).
    """
    ds = SCDynamicStoreCreate(None, "wifiscope", None, None)
    if ds is None:
        return None, None
    val = SCDynamicStoreCopyValue(
        ds, f"State:/Network/Interface/{interface_name}/AirPort"
    )
    if val is None:
        return None, None
    csr = val.get("CachedScanRecord")
    if csr is None:
        return None, None

    try:
        plist = plistlib.loads(bytes(csr))
        root = _resolve_ns_dict(plist["$objects"], plist["$top"]["root"])
    except Exception:
        return None, None
    if root is None:
        return None, None

    age_ms = root.get("AGE")
    if isinstance(age_ms, (int, float)) and age_ms > _MAX_AGE_MS:
        return None, None

    bssid = root.get("BSSID")
    ssid = root.get("SSID_STR")
    if not isinstance(bssid, str) or bssid == _REDACTED_BSSID:
        bssid = None
    else:
        bssid = bssid.lower()
    if not isinstance(ssid, str) or ssid == "":
        ssid = None
    return bssid, ssid


def _resolve(objs, ref):
    if isinstance(ref, plistlib.UID):
        return objs[ref.data]
    return ref


def _resolve_ns_dict(objs, ref):
    """Materialize an archived NSDictionary into a plain dict."""
    d = _resolve(objs, ref)
    if not isinstance(d, dict) or "NS.keys" not in d or "NS.objects" not in d:
        return None
    keys = [_resolve(objs, k) for k in d["NS.keys"]]
    vals = [_resolve(objs, v) for v in d["NS.objects"]]
    return dict(zip(keys, vals))
