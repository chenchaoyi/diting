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
