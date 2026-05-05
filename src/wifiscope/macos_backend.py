"""macOS WiFi backend backed by CoreWLAN (via pyobjc).

Why CoreWLAN and not `wdutil info` / `airport`:
- `wdutil info` redacts BSSID on macOS 14.4+
- the `airport` binary was removed in recent macOS releases
- CoreWLAN is the supported public API and is what System Settings uses

Permissions caveat: BSSID is only returned when the host process (Terminal /
iTerm) has been granted Location Services permission. Without it, all other
fields still work and `bssid` comes back as None — the UI surfaces this.
"""

from datetime import datetime

from CoreWLAN import CWWiFiClient

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


class MacOSWiFiBackend(WiFiBackend):
    name = "macOS CoreWLAN"

    def __init__(self) -> None:
        self._client = CWWiFiClient.sharedWiFiClient()

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
        return Connection(
            ssid=iface.ssid(),    # None if redacted by Location Services
            bssid=iface.bssid(),  # None without Location Services permission
            rssi_dbm=_maybe_int(iface.rssiValue()),
            noise_dbm=_maybe_int(iface.noiseMeasurement()),
            tx_rate_mbps=_maybe_float(iface.transmitRate()),
            channel=ch_num,
            channel_width_mhz=ch_width,
            channel_band=ch_band,
            phy_mode=_PHY_MODE.get(int(iface.activePHYMode())),
            security=_SECURITY.get(int(iface.security())),
            mcs_index=None,  # not exposed by CoreWLAN public API
            nss=None,        # not exposed by CoreWLAN public API
            timestamp=datetime.now(),
        )

    def permission_state(self) -> PermissionState:
        # CoreLocation could give a definitive answer, but it requires the
        # process to be a bundled .app to even prompt the user — useless
        # for a CLI. Instead infer from CoreWLAN: when associated (channel
        # populated), BSSID is None iff Location Services is denied.
        iface = self._interface()
        if iface is None or iface.wlanChannel() is None:
            return "unknown"
        return "granted" if iface.bssid() else "denied"

    def scan(self) -> list[ScanResult]:
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
