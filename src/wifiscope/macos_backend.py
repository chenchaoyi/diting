"""macOS WiFi backend backed by CoreWLAN (via pyobjc).

Why CoreWLAN and not `wdutil info` / `airport`:
- `wdutil info` redacts BSSID on macOS 14.4+
- the `airport` binary was removed in recent macOS releases
- CoreWLAN is the supported public API and is what System Settings uses

Permissions caveat: BSSID is only returned when the host process (Terminal /
iTerm) has been granted Location Services permission. Without it, all other
fields still work and `bssid` comes back as None — the UI surfaces this.
"""

import subprocess
import time
from datetime import datetime

from CoreWLAN import CWWiFiClient

from . import _dynamic_store, _helper
from .backend import PermissionState, WiFiBackend
from .models import Connection, ScanResult

# CoreWLAN enums → human strings. Values mirror the CoreWLAN headers; we
# look them up by integer rather than importing constants so a future macOS
# release that adds, e.g., 802.11be just falls through to None instead of
# crashing the import.
_PHY_MODE = {
    0: None,        # CWPHYModeNone
    1: "802.11a",
    2: "802.11b",
    3: "802.11g",
    4: "802.11n",
    5: "802.11ac",
    6: "802.11ax",
}

_BAND = {
    0: None,        # CWChannelBandUnknown
    1: "2.4 GHz",
    2: "5 GHz",
    3: "6 GHz",
}

_WIDTH_MHZ = {
    0: None,        # CWChannelWidthUnknown
    1: 20,
    2: 40,
    3: 80,
    4: 160,
}

_SECURITY = {
    -1: None,       # CWSecurityUnknown
    0: "Open",      # None
    1: "WEP",
    2: "WPA Personal",
    3: "WPA Personal Mixed",
    4: "WPA2 Personal",
    5: "Personal",
    6: "Dynamic WEP",
    7: "WPA Enterprise",
    8: "WPA Enterprise Mixed",
    9: "WPA2 Enterprise",
    10: "Enterprise",
    11: "WPA3 Personal",
    12: "WPA3 Enterprise",
    13: "WPA3 Transition",
    14: "OWE",
    15: "OWE Transition",
}


def _maybe_int(value):
    """CoreWLAN returns 0 for several fields when no measurement is
    available; treat those as None so the UI can show 'n/a'."""
    if value is None:
        return None
    v = int(value)
    return v if v != 0 else None


def _maybe_float(value):
    if value is None:
        return None
    v = float(value)
    return v if v != 0.0 else None


def _channel_fields(channel):
    if channel is None:
        return None, None, None
    return (
        int(channel.channelNumber()) or None,
        _WIDTH_MHZ.get(int(channel.channelWidth())),
        _BAND.get(int(channel.channelBand())),
    )


def _safe_call(obj, name: str):
    """Call a possibly-undocumented Obj-C method, returning None on miss."""
    fn = getattr(obj, name, None)
    if fn is None or not callable(fn):
        return None
    try:
        return fn()
    except Exception:
        return None


def _get_ipv4_address(iface_name: str) -> str | None:
    """`ipconfig getifaddr <iface>` — empty output when the interface
    has no IPv4. ~1ms call, so safe to issue on every connection
    poll tick rather than caching."""
    if not iface_name:
        return None
    try:
        proc = subprocess.run(
            ["/usr/sbin/ipconfig", "getifaddr", iface_name],
            capture_output=True, text=True, timeout=2.0, check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    return proc.stdout.strip() or None


def _get_default_router() -> str | None:
    """First-line `default` entry of `netstat -rn -f inet`."""
    try:
        proc = subprocess.run(
            ["/usr/sbin/netstat", "-rn", "-f", "inet"],
            capture_output=True, text=True, timeout=2.0, check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    for line in proc.stdout.splitlines():
        parts = line.split()
        if parts and parts[0] == "default":
            return parts[1] if len(parts) >= 2 else None
    return None


def _band_from_channel_number(ch: int) -> str | None:
    """Infer the band label from a channel number.

    Used when channel comes from CachedScanRecord (which has no band
    field). 6 GHz overlaps with 2.4 GHz channel numbers (1..233 vs
    1..14), so this can be wrong if the AP is on 6 GHz channel 1; v0.1
    accepts that ambiguity (most home gear is still 2.4/5 only).
    """
    if 1 <= ch <= 14:
        return "2.4 GHz"
    if 32 <= ch <= 177:
        return "5 GHz"
    return None


class MacOSWiFiBackend(WiFiBackend):
    name = "macOS CoreWLAN"

    def __init__(self) -> None:
        self._client = CWWiFiClient.sharedWiFiClient()
        # Resolved once at construction; if the user installs / removes
        # the helper later, they restart wifiscope. Avoids a stat() on
        # every scan tick.
        self._helper_path: str | None = _helper.find_helper()
        # Interface metadata last seen from a successful helper scan
        # (country_code, hardware_address). Lets get_connection() show
        # fields like country code that are TCC-redacted in the Python
        # process but visible to the helper bundle.
        self._helper_iface_meta: dict = {}

    def _interface(self):
        return self._client.interface()

    def get_connection(self) -> Connection | None:
        iface = self._interface()
        if iface is None:
            return None
        # `wlanChannel()` is the reliable "associated?" signal — it's None
        # when not connected, populated when connected. SSID/BSSID alone
        # cannot be used: macOS 14.4+ redacts both to None when the host
        # process lacks Location Services permission, even mid-connection.
        channel = iface.wlanChannel()
        if channel is None:
            return None
        ch_num, ch_width, ch_band = _channel_fields(channel)
        ssid = iface.ssid()
        bssid = iface.bssid()
        # Always consult SCDynamicStore. Two reasons:
        #   1. ssid/bssid are TCC-redacted to None for unprivileged
        #      processes; the CachedScanRecord side-channel still has
        #      them.
        #   2. wlanChannel().channelNumber follows the radio's *current*
        #      tune, which momentarily moves to scan targets during
        #      macOS background scans, even when the user has Location
        #      Services granted. CachedScanRecord.CHANNEL describes the
        #      AP itself and is stable regardless of our radio's state.
        # The dynamic-store read is microseconds, so doing it on every
        # 1 Hz tick is negligible.
        cached = _dynamic_store.read_current_identity(iface.interfaceName())
        ssid = ssid or cached.ssid
        bssid = bssid or cached.bssid
        if cached.channel is not None:
            ch_num = cached.channel
            ch_band = _band_from_channel_number(cached.channel)
        # MCS index and spatial-stream count are private CoreWLAN
        # methods (mcsIndex / numberOfSpatialStreams). They are not in
        # the public docs but exist as ObjC selectors and back the
        # macOS WiFi panel's display, so we use them. Wrapped in
        # getattr() so a future macOS that drops the method degrades
        # to None instead of crashing the backend.
        mcs = _safe_call(iface, "mcsIndex")
        nss = _safe_call(iface, "numberOfSpatialStreams")
        max_link = _safe_call(iface, "maximumLinkSpeed")
        return Connection(
            ssid=ssid,
            bssid=bssid,
            rssi_dbm=_maybe_int(iface.rssiValue()),
            noise_dbm=_maybe_int(iface.noiseMeasurement()),
            tx_rate_mbps=_maybe_float(iface.transmitRate()),
            channel=ch_num,
            channel_width_mhz=ch_width,
            channel_band=ch_band,
            phy_mode=_PHY_MODE.get(int(iface.activePHYMode())),
            security=_SECURITY.get(int(iface.security())),
            mcs_index=_maybe_int(mcs),
            nss=_maybe_int(nss),
            timestamp=datetime.now(),
            interface_mac=iface.hardwareAddress() or None,
            # CoreWLAN.countryCode is TCC-redacted in unprivileged
            # processes; the helper sees it. Cache the last value the
            # helper reported (refreshed on every scan) so the field
            # is available across the 1 Hz connection-poll cadence.
            country_code=(
                iface.countryCode()
                or self._helper_iface_meta.get("country_code")
                or None
            ),
            ip_address=_get_ipv4_address(iface.interfaceName()),
            router_ip=_get_default_router(),
            max_link_speed_mbps=_maybe_int(max_link),
        )

    def force_reroam(self) -> bool:
        """Cycle WiFi power so macOS re-associates with the strongest
        BSSID for the currently saved SSID, the same path the user
        gets by toggling the WiFi menu icon off then on.

        We do not use `iface.disassociate()`: it tears down the link
        but does not always trigger auto-rejoin on Enterprise / 802.1X
        networks (no Keychain unlock prompt fires, the OS sees a clean
        manual disconnect, and you sit there disconnected). Power-
        cycling the radio goes through the full Network Manager flow
        — auto-join, EAP / RADIUS handshake, Keychain credential
        lookup — which is exactly what 'click WiFi menu, click my SSID'
        ends up doing.

        Returns True if both setPower calls were issued; the caller
        should not assume the link is already back up — re-association
        takes 2-5 seconds for personal, longer for Enterprise.
        """
        iface = self._interface()
        if iface is None:
            return False
        iface.setPower_error_(False, None)
        # Brief pause so the OS commits the off state before we flip
        # back. ~0.3 s is empirically enough; faster cycles sometimes
        # collapse into a no-op.
        time.sleep(0.3)
        iface.setPower_error_(True, None)
        return True

    def permission_state(self) -> PermissionState:
        # CoreLocation could give a definitive answer, but it requires the
        # process to be a bundled .app to even prompt the user — useless
        # for a CLI. Instead infer from observable behaviour:
        #   CoreWLAN returns BSSID            -> "granted"
        #   CoreWLAN redacted, fallback works -> "fallback"
        #   CoreWLAN redacted, fallback fails -> "denied"
        iface = self._interface()
        if iface is None or iface.wlanChannel() is None:
            return "unknown"
        if iface.bssid():
            return "granted"
        cached = _dynamic_store.read_current_identity(iface.interfaceName())
        return "fallback" if cached.bssid else "denied"

    def scan(self) -> list[ScanResult]:
        # Helper-first: if the wifiscope-helper.app is installed it owns
        # the Location Services grant and returns unredacted SSID /
        # BSSID. Empty result (helper not installed, or installed but
        # crashed) falls through to direct CoreWLAN, which still yields
        # RSSI / channel even when identity is redacted.
        if self._helper_path is not None:
            results, meta = _helper.scan(self._helper_path)
            if meta:
                self._helper_iface_meta = meta
            if results:
                return results
        iface = self._interface()
        if iface is None:
            return []
        result, error = iface.scanForNetworksWithName_error_(None, None)
        if error is not None or result is None:
            return []
        ts = datetime.now()
        out: list[ScanResult] = []
        for net in result:
            ch_num, ch_width, ch_band = _channel_fields(net.wlanChannel())
            out.append(
                ScanResult(
                    ssid=net.ssid(),
                    bssid=net.bssid(),
                    rssi_dbm=_maybe_int(net.rssiValue()),
                    noise_dbm=_maybe_int(net.noiseMeasurement()),
                    channel=ch_num,
                    channel_width_mhz=ch_width,
                    channel_band=ch_band,
                    phy_mode=None,  # CWNetwork has no activePHYMode
                    security=None,  # CWNetwork.security is a different enum domain; defer
                    timestamp=ts,
                )
            )
        return out
