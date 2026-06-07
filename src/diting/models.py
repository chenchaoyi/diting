"""Data models for WiFi state snapshots.

All numeric fields are typed `int | None` / `float | None` because:

- BSSID can be None on macOS 14.4+ when Terminal lacks Location Services
  permission (handled in the UI as a permission hint).
- MCS index and spatial-stream count are not always exposed by the public
  CoreWLAN API — when unavailable, we report None rather than fabricate.
- A backend that can't report a field for any other reason (e.g. radio
  off, transient error) does the same.
"""

from dataclasses import dataclass
from datetime import datetime

_HEX = set("0123456789abcdef")


def normalize_bssid(raw: str | None) -> str | None:
    """Canonical BSSID spelling: lowercase, colon-separated, each octet
    zero-padded to two hex digits.

    macOS formats some surfaces without octet padding — the
    SCDynamicStore ``CachedScanRecord`` renders ``…:3c:0b`` as
    ``…:3c:b`` — while scan paths return padded octets. Un-normalized,
    the same radio becomes two identities downstream (duplicate Nearby
    rows, phantom roams, split familiarity history), so every producer
    applies this at its boundary. Fail-soft: a string that doesn't
    parse as six 1–2-char hex octets is returned lowercased as-is,
    never raised on — same convention as the ARP / MiBeacon MAC
    parsers that fixed this quirk at their own boundaries.
    """
    if raw is None:
        return None
    s = raw.lower()
    parts = s.split(":")
    if len(parts) != 6:
        return s
    if any(not p or len(p) > 2 or any(c not in _HEX for c in p) for p in parts):
        return s
    return ":".join(p.zfill(2) for p in parts)


@dataclass(frozen=True, slots=True)
class Connection:
    """Snapshot of the local WiFi association at a point in time."""

    ssid: str | None
    bssid: str | None
    rssi_dbm: int | None
    noise_dbm: int | None
    tx_rate_mbps: float | None
    channel: int | None
    channel_width_mhz: int | None
    channel_band: str | None
    phy_mode: str | None
    security: str | None
    mcs_index: int | None
    nss: int | None
    timestamp: datetime
    # Local-host context fields populated alongside the negotiated link
    # state. Each may be None when its source is unavailable; we never
    # synthesise. interface_mac is the Mac's own WiFi MAC (distinct
    # from BSSID); router_ip is the default IPv4 gateway as seen from
    # this interface; max_link_speed_mbps is what the radio is
    # *capable* of, not what is currently negotiated.
    interface_mac: str | None = None
    country_code: str | None = None
    ip_address: str | None = None
    router_ip: str | None = None
    max_link_speed_mbps: int | None = None
    # When True, ``tx_rate_mbps`` is a cached value substituted in for
    # a poll that observed an idle radio (transmitRate() == 0). The
    # TUI renders this as "144.0 Mbps (idle) / 867 Mbps" instead of
    # "n/a / 867 Mbps", which flickers on an otherwise-stable
    # association. Cache lives on the backend, scoped to (ssid, bssid)
    # — see MacOSWiFiBackend.
    tx_rate_idle: bool = False


@dataclass(frozen=True, slots=True)
class ScanResult:
    """One AP visible in an active scan."""

    ssid: str | None
    bssid: str | None
    rssi_dbm: int | None
    noise_dbm: int | None
    channel: int | None
    channel_width_mhz: int | None
    channel_band: str | None
    phy_mode: str | None
    security: str | None
    timestamp: datetime
    # Country code from the AP's beacon information element, when the
    # data path can read it (helper or granted CoreWLAN).
    country_code: str | None = None
    # Beacon-IE-derived diagnostics fields (helper schema=3 + v0.7.0+).
    # Each is None when the IE was absent from the beacon, when the
    # data path cannot read IE bytes (CoreWLAN without permission), or
    # when an older helper schema does not surface them.
    bss_load_pct: int | None = None
    bss_station_count: int | None = None
    supports_802_11r: bool | None = None
    supports_802_11k: bool | None = None
    supports_802_11v: bool | None = None
