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
identity data without bundling diting as a `.app`.

The fallback fails gracefully: if the key is gone, the structure
shifts, or the cached record is too stale (`AGE` is reported in
milliseconds), we return None and the caller stays in the
"BSSID hidden" state it already handles.
"""

from __future__ import annotations

import plistlib
from dataclasses import dataclass

from SystemConfiguration import SCDynamicStoreCopyValue, SCDynamicStoreCreate

# macOS uses this as the placeholder when redacting BSSID. Any other
# locally-administered MAC starting with 02 is technically valid, so
# we only filter the exact placeholder value.
_REDACTED_BSSID = "02:00:00:00:00:00"

# Reject scan records older than this. macOS in practice updates
# CachedScanRecord on the order of a second or two; anything stale
# is more likely to misrepresent post-roam state.
_MAX_AGE_MS = 30_000


@dataclass(frozen=True, slots=True)
class CachedAssociation:
    """What we can recover for the currently associated AP."""
    bssid: str | None
    ssid: str | None
    channel: int | None  # operating channel of the associated AP


def read_current_identity(interface_name: str) -> CachedAssociation:
    """Return identity + operating channel of the currently associated AP.

    Pure read — does not require any permission grant. Safe to call on
    every poll tick (cheap; a single SCDynamicStore lookup plus a small
    bplist parse).

    Channel comes from the **top-level CHANNEL** field of the AirPort
    state dict, which the OS maintains as the radio's current associated
    channel. It is updated when the link changes and is not affected by
    background scans like CoreWLAN.wlanChannel() is. We do NOT use
    CachedScanRecord.CHANNEL as the primary source because that field is
    a beacon-scan snapshot and can lag if the AP has hopped to another
    channel since (DFS, dynamic channel selection on enterprise APs).
    """
    empty = CachedAssociation(bssid=None, ssid=None, channel=None)
    ds = SCDynamicStoreCreate(None, "diting", None, None)
    if ds is None:
        return empty
    val = SCDynamicStoreCopyValue(
        ds, f"State:/Network/Interface/{interface_name}/AirPort"
    )
    if val is None:
        return empty

    # Top-level CHANNEL is reliable; SSID and BSSID at the top level are
    # redacted to a placeholder when TCC is not granted, so for those we
    # parse the bplist below (which is *not* redacted — see header).
    top_channel = val.get("CHANNEL")
    channel = (
        top_channel
        if isinstance(top_channel, int) and top_channel > 0
        else None
    )

    bssid: str | None = None
    ssid: str | None = None
    csr = val.get("CachedScanRecord")
    if csr is not None:
        try:
            plist = plistlib.loads(bytes(csr))
            root = _resolve_ns_dict(plist["$objects"], plist["$top"]["root"])
        except Exception:
            root = None
        if root is not None:
            age_ms = root.get("AGE")
            stale = isinstance(age_ms, (int, float)) and age_ms > _MAX_AGE_MS
            if not stale:
                raw_b = root.get("BSSID")
                if isinstance(raw_b, str) and raw_b != _REDACTED_BSSID:
                    bssid = raw_b.lower()
                raw_s = root.get("SSID_STR")
                if isinstance(raw_s, str) and raw_s:
                    ssid = raw_s
                # Last-ditch channel source if the top-level field was
                # missing for some reason. Possibly stale, but better
                # than None.
                if channel is None:
                    raw_c = root.get("CHANNEL")
                    if isinstance(raw_c, int) and raw_c > 0:
                        channel = raw_c

    return CachedAssociation(bssid=bssid, ssid=ssid, channel=channel)


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
