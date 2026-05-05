"""Command-line entry point.

Two modes (no argparse — keep step-6 surface minimal):

    wifiscope         one-shot snapshot of the current connection
    wifiscope watch   streaming event log (Ctrl+C to quit)

The TUI lands in step 8 and will replace `watch` as the default.
"""

from __future__ import annotations

import asyncio
import sys
import time
from datetime import datetime

from .macos_backend import MacOSWiFiBackend
from .models import Connection
from .network import (
    NetworkInventory,
    band_label,
    format_bssid,
    load_inventory,
    resolve_config_path,
)
from .poller import (
    ConnectionUpdate,
    Event,
    RoamEvent,
    ScanUpdate,
    WiFiPoller,
)

_DENIED_HINT = (
    "WARNING: SSID and BSSID are hidden. CoreWLAN is redacted by Location\n"
    "         Services and the SCDynamicStore fallback also returned\n"
    "         nothing. Grant Location Services to your terminal app, or\n"
    "         see README's macOS 26 caveats section.\n"
)
_FALLBACK_HINT = (
    "note: SSID/BSSID via SCDynamicStore fallback (CoreWLAN is redacted).\n"
)


def _fmt(value: object, suffix: str = "") -> str:
    if value is None:
        return "n/a"
    return f"{value}{suffix}"


# ---------- one-shot mode ----------

def _print_connection(c: Connection, inv: NetworkInventory) -> None:
    rows: list[tuple[str, str]] = [
        ("SSID", _fmt(c.ssid)),
        ("BSSID", format_bssid(c.bssid, c.channel, inv)),
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


def _run_once() -> None:
    backend = MacOSWiFiBackend()
    inv = load_inventory()
    conn = backend.get_connection()
    print(f"backend:    {backend.name}")
    if conn is None:
        print("status:     not associated")
        sys.exit(1)
    print(f"timestamp:  {conn.timestamp.isoformat(timespec='seconds')}")
    print()
    _print_connection(conn, inv)
    state = backend.permission_state()
    if state == "denied":
        print()
        print(_DENIED_HINT, end="")
    elif state == "fallback":
        print()
        print(_FALLBACK_HINT, end="")


# ---------- watch mode ----------

# Identity tuple — the parts of a Connection that, if any change, mean
# something a human would care about. RSSI / noise / tx rate are noisy
# fluctuating fields handled with a separate threshold.
_IDENTITY_FIELDS = (
    "ssid",
    "bssid",
    "channel",
    "channel_width_mhz",
    "channel_band",
    "phy_mode",
    "security",
)
_RSSI_DELTA_THRESHOLD_DB = 5
_HEARTBEAT_SECONDS = 10.0


def _identity_key(c: Connection | None) -> tuple:
    if c is None:
        return ("disconnected",)
    return tuple(getattr(c, f) for f in _IDENTITY_FIELDS)


def _format_conn_line(c: Connection | None, inv: NetworkInventory) -> str:
    if c is None:
        return "conn   <not associated>"
    return (
        f"conn   ssid={_fmt(c.ssid)}  bssid={format_bssid(c.bssid, c.channel, inv)}  "
        f"rssi={_fmt(c.rssi_dbm, 'dBm')}  "
        f"ch{c.channel or 0}/{c.channel_band or '?'}/{_fmt(c.channel_width_mhz, 'MHz')}  "
        f"{c.phy_mode or '?'}  {c.security or '?'}"
    )


def _format_scan_line(results: list) -> str:
    return f"scan   {len(results)} APs visible"


def _format_roam_line(event: RoamEvent, inv: NetworkInventory) -> str:
    same = inv.is_same_ap(event.previous_bssid, event.new_bssid)
    prev = format_bssid(event.previous_bssid, event.previous_channel, inv)
    new = format_bssid(event.new_bssid, event.new_channel, inv)
    if same:
        prev_band = band_label(event.previous_channel) or "?"
        new_band = band_label(event.new_channel) or "?"
        ap_name = inv.resolve(event.new_bssid) or "same AP"
        tag = f"[band switch on {ap_name}: {prev_band} -> {new_band}]"
    else:
        tag = "[inter-AP roam]"
    return f"ROAM   {prev}  ->  {new}   {tag}"


async def _run_watch() -> None:
    backend = MacOSWiFiBackend()
    inv = load_inventory()
    print(f"backend: {backend.name}  (Ctrl+C to quit)")
    if inv.aps or inv.radio_overrides:
        print(
            f"inventory: {len(inv.aps)} APs, "
            f"{len(inv.radio_overrides)} overrides — {resolve_config_path()}"
        )
    perm = backend.permission_state()
    if perm == "denied":
        print()
        print(_DENIED_HINT, end="")
    elif perm == "fallback":
        print(_FALLBACK_HINT, end="")
    print()

    poller = WiFiPoller(backend)
    state: dict = {"last_key": None, "last_rssi": None, "last_print_at": 0.0}

    async for event in poller.events():
        line = _render(event, state, inv)
        if line is not None:
            now_str = datetime.now().strftime("%H:%M:%S")
            print(f"{now_str}  {line}", flush=True)


def _render(event: Event, state: dict, inv: NetworkInventory) -> str | None:
    """Decide whether and how to render this event.

    Mutates `state` to track last-printed identity / RSSI / timestamp
    for connection dedup. Returns the formatted line, or None to skip.
    """
    if isinstance(event, ScanUpdate):
        return _format_scan_line(event.results)
    if isinstance(event, RoamEvent):
        return _format_roam_line(event, inv)
    assert isinstance(event, ConnectionUpdate)

    c = event.connection
    key = _identity_key(c)
    rssi = c.rssi_dbm if c is not None else None
    now = time.monotonic()

    identity_changed = key != state["last_key"]
    rssi_jumped = (
        rssi is not None
        and state["last_rssi"] is not None
        and abs(rssi - state["last_rssi"]) >= _RSSI_DELTA_THRESHOLD_DB
    )
    heartbeat_due = now - state["last_print_at"] >= _HEARTBEAT_SECONDS
    first_print = state["last_print_at"] == 0.0

    if not (identity_changed or rssi_jumped or heartbeat_due or first_print):
        return None

    state["last_key"] = key
    state["last_rssi"] = rssi
    state["last_print_at"] = now
    return _format_conn_line(c, inv)


# ---------- entry ----------

def main() -> None:
    args = sys.argv[1:]
    if args and args[0] == "watch":
        try:
            asyncio.run(_run_watch())
        except KeyboardInterrupt:
            pass
        return
    if args and args[0] in ("-h", "--help"):
        print("usage: wifiscope [watch]")
        print("  (no args)   one-shot snapshot of current connection")
        print("  watch       stream events until Ctrl+C")
        return
    _run_once()
