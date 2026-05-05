"""One-shot CLI: print the current WiFi connection.

Step-4 smoke test — no TUI, no polling, no scan. A single Connection
snapshot is printed and the process exits. Real-time polling and scan
output land in steps 6 and 8.
"""

from __future__ import annotations

import sys

from .macos_backend import MacOSWiFiBackend
from .models import Connection


def _fmt(value: object, suffix: str = "") -> str:
    if value is None:
        return "n/a"
    return f"{value}{suffix}"


def _print_connection(c: Connection) -> None:
    rows: list[tuple[str, str]] = [
        ("SSID", _fmt(c.ssid)),
        ("BSSID", _fmt(c.bssid)),
        ("RSSI", _fmt(c.rssi_dbm, " dBm")),
        ("Noise", _fmt(c.noise_dbm, " dBm")),
        ("Tx Rate", _fmt(c.tx_rate_mbps, " Mbps")),
        ("Channel", _fmt(c.channel)),
        ("Width", _fmt(c.channel_width_mhz, " MHz")),
        ("Band", _fmt(c.channel_band)),
        ("PHY Mode", _fmt(c.phy_mode)),
        ("Security", _fmt(c.security)),
        ("MCS", _fmt(c.mcs_index)),
        ("NSS", _fmt(c.nss)),
    ]
    label_w = max(len(label) for label, _ in rows)
    for label, value in rows:
        print(f"  {label:<{label_w}}  {value}")


_PERMISSION_HINT = (
    "WARNING: SSID and BSSID are hidden because this terminal lacks "
    "Location Services permission.\n"
    "         Grant it under: System Settings -> Privacy & Security -> "
    "Location Services\n"
    "         Enable the entry for your terminal app (Terminal / iTerm / "
    "Ghostty / etc.) and rerun.\n"
)


def main() -> None:
    backend = MacOSWiFiBackend()
    conn = backend.get_connection()
    print(f"backend:    {backend.name}")
    if conn is None:
        print("status:     not associated")
        sys.exit(1)
    print(f"timestamp:  {conn.timestamp.isoformat(timespec='seconds')}")
    print()
    _print_connection(conn)
    if backend.permission_state() == "denied":
        print()
        print(_PERMISSION_HINT, end="")
