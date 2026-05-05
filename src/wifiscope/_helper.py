"""Discover and call the wifiscope-helper Swift sidecar.

The helper is a tiny `.app` bundle (sources at <repo>/helper/) that owns
Location Services permission and, when invoked as a subprocess with
`scan`, prints one JSON document of unredacted scan results. When the
helper is missing or unreachable, callers fall back to direct CoreWLAN
(which still works for RSSI / channel but leaves SSID / BSSID
redacted on macOS 26 without permission).

Search order for the bundle:

1. ``WIFISCOPE_HELPER`` env var — full path to either the bundle or
   the binary inside it
2. ``/Applications/wifiscope-helper.app``
3. ``~/Applications/wifiscope-helper.app``
4. ``<repo>/helper/wifiscope-helper.app`` — picks up a developer build
   without copying anywhere
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime
from pathlib import Path

from .models import ScanResult

# Mirrors CoreWLAN enum values; the helper passes the raw integers
# straight through so we can decode them once on this side.
_BAND = {0: None, 1: "2.4 GHz", 2: "5 GHz", 3: "6 GHz"}
_WIDTH_MHZ = {0: None, 1: 20, 2: 40, 3: 80, 4: 160}


def find_helper() -> str | None:
    """Return the path to a runnable wifiscope-helper binary, or None."""
    override = os.environ.get("WIFISCOPE_HELPER")
    if override:
        return _resolve(Path(override).expanduser())
    candidates = [
        Path("/Applications/wifiscope-helper.app"),
        Path("~/Applications/wifiscope-helper.app").expanduser(),
        # Developer build inside this repo. wifiscope is typically
        # installed editable so __file__ traces back to the source tree.
        Path(__file__).resolve().parents[2] / "helper" / "wifiscope-helper.app",
    ]
    for c in candidates:
        resolved = _resolve(c)
        if resolved is not None:
            return resolved
    return None


def _resolve(path: Path) -> str | None:
    if path.is_file() and os.access(path, os.X_OK):
        return str(path)
    if path.suffix == ".app" and path.is_dir():
        binary = path / "Contents" / "MacOS" / "wifiscope-helper"
        if binary.is_file() and os.access(binary, os.X_OK):
            return str(binary)
    return None


def scan(binary: str, timeout: float = 12.0) -> list[ScanResult]:
    """Run `<binary> scan` and decode the JSON payload.

    Returns an empty list if the helper exits non-zero or its output
    is malformed; callers can then fall back to a direct CoreWLAN scan.
    """
    try:
        proc = subprocess.run(
            [binary, "scan"],
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        return []
    if proc.returncode != 0:
        return []
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return []
    nets = payload.get("networks") or []
    ts = datetime.now()
    out: list[ScanResult] = []
    for net in nets:
        bssid = net.get("bssid")
        if isinstance(bssid, str):
            bssid = bssid.lower() or None
        else:
            bssid = None
        out.append(
            ScanResult(
                ssid=net.get("ssid") or None,
                bssid=bssid,
                rssi_dbm=_or_none_zero(net.get("rssi_dbm")),
                noise_dbm=_or_none_zero(net.get("noise_dbm")),
                channel=net.get("channel"),
                channel_width_mhz=_WIDTH_MHZ.get(net.get("channel_width_raw") or 0),
                channel_band=_BAND.get(net.get("channel_band_raw") or 0),
                phy_mode=None,   # CWNetwork does not expose activePHYMode
                security=None,   # helper only sends a coarse probe, not a label
                timestamp=ts,
            )
        )
    return out


def _or_none_zero(value):
    if value is None:
        return None
    v = int(value)
    return v if v != 0 else None
