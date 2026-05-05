"""Textual TUI for wifiscope.

Three vertically-stacked panels driven by a single WiFiPoller:

    ┌ Connection ─────────────────────────────────────┐
    │ AP, SSID, BSSID, channel, signal bar, PHY ...   │
    ├ Nearby APs (scanned 2s ago) ────────────────────┤
    │ table of scanned APs, sorted by RSSI            │
    ├ Roam log ───────────────────────────────────────┤
    │ scrollable history of band-switch / inter-AP    │
    └─────────────────────────────────────────────────┘

Bindings: q quit · p pause · r force-rescan.
"""

from __future__ import annotations

import time
from datetime import datetime

from rich.console import Group
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Footer, Header, RichLog, Static

from .backend import WiFiBackend
from .models import Connection, ScanResult
from .network import NetworkInventory, band_label, format_bssid
from .poller import (
    ConnectionUpdate,
    RoamEvent,
    ScanUpdate,
    WiFiPoller,
)


# ---------- panels ----------

class ConnectionPanel(Static):
    DEFAULT_CSS = """
    ConnectionPanel {
        height: auto;
        min-height: 11;
        border: heavy $accent;
        padding: 0 1;
    }
    """

    def on_mount(self) -> None:
        self.border_title = "Connection"
        self._paint(None)

    def update_connection(self, conn: Connection | None, inv: NetworkInventory) -> None:
        self._paint(conn, inv)

    def _paint(self, conn: Connection | None, inv: NetworkInventory | None = None) -> None:
        if conn is None:
            self.update(Text("not associated", style="dim italic"))
            return
        assert inv is not None
        ap_name = inv.resolve(conn.bssid) or "(unknown)"
        band = band_label(conn.channel)
        # Header line: AP name in bold + band
        header = Text()
        header.append(ap_name, style="bold cyan")
        if band:
            header.append(f"  {band}", style="cyan")
        # Body: aligned key/value rows, plus a signal bar
        signal_bar = _signal_bar(conn.rssi_dbm)
        rows = [
            ("SSID", _fmt(conn.ssid)),
            ("BSSID", _fmt(conn.bssid)),
            (
                "Channel",
                f"{_fmt(conn.channel)}  {_fmt(conn.channel_width_mhz, ' MHz')}  "
                f"{_fmt(conn.channel_band)}",
            ),
            ("PHY / Sec", f"{_fmt(conn.phy_mode)}   {_fmt(conn.security)}"),
            (
                "Tx / Noise",
                f"{_fmt(conn.tx_rate_mbps, ' Mbps')}   noise {_fmt(conn.noise_dbm, ' dBm')}",
            ),
        ]
        body = Text()
        for label, value in rows:
            body.append(f"  {label:<11}", style="dim")
            body.append(f"{value}\n")
        signal_line = Text()
        signal_line.append(f"  {'Signal':<11}", style="dim")
        signal_line.append(_rssi_text(conn.rssi_dbm))
        signal_line.append("  ")
        signal_line.append(signal_bar)
        self.update(Group(header, Text(""), body, signal_line))


class ScanPanel(Static):
    DEFAULT_CSS = """
    ScanPanel {
        height: 1fr;
        border: heavy $accent;
        padding: 0 1;
    }
    """

    def on_mount(self) -> None:
        self.border_title = "Nearby APs"
        self.update(Text("(scanning...)", style="dim italic"))

    def update_scan(
        self,
        results: list[ScanResult],
        current_bssid: str | None,
        scanned_at: float | None,
        inv: NetworkInventory,
    ) -> None:
        ago = "" if scanned_at is None else f"  · scanned {int(time.monotonic() - scanned_at)}s ago"
        all_redacted = bool(results) and all(
            r.bssid is None and r.ssid is None for r in results
        )
        identity = "  · identity TCC-redacted" if all_redacted else ""
        self.border_title = f"Nearby APs ({len(results)}){ago}{identity}"
        if not results:
            self.update(Text("(no APs from last scan — likely throttle, retrying)", style="dim italic"))
            return
        rows = sorted(results, key=lambda r: r.rssi_dbm if r.rssi_dbm is not None else -200, reverse=True)
        # Hand-rolled aligned table — DataTable is overkill for read-only display
        # and adds focus / scroll behaviour we do not want here.
        lines: list[Text] = []
        lines.append(_header_line())
        for r in rows:
            lines.append(_scan_line(r, current_bssid, inv))
        self.update(Group(*lines))


class RoamLogPanel(RichLog):
    DEFAULT_CSS = """
    RoamLogPanel {
        height: 8;
        border: heavy $accent;
        padding: 0 1;
    }
    """

    def on_mount(self) -> None:
        self.border_title = "Roam log"
        self.write(Text("(no roam events yet)", style="dim italic"))

    def append_roam(self, event: RoamEvent, inv: NetworkInventory) -> None:
        ts = event.timestamp.strftime("%H:%M:%S")
        prev = format_bssid(event.previous_bssid, event.previous_channel, inv)
        new = format_bssid(event.new_bssid, event.new_channel, inv)
        if inv.is_same_ap(event.previous_bssid, event.new_bssid):
            ap = inv.resolve(event.new_bssid) or "same AP"
            prev_band = band_label(event.previous_channel) or "?"
            new_band = band_label(event.new_channel) or "?"
            tag = f"[band switch on {ap}: {prev_band} -> {new_band}]"
            style = "yellow"
        else:
            tag = "[inter-AP roam]"
            style = "bold magenta"
        line = Text()
        line.append(f"{ts}  ", style="dim")
        line.append(f"{prev}  ->  {new}   ", style="white")
        line.append(tag, style=style)
        self.write(line)


# ---------- helpers ----------

def _fmt(value, suffix: str = "") -> str:
    if value is None:
        return "n/a"
    return f"{value}{suffix}"


def _signal_bar(rssi: int | None, length: int = 12) -> Text:
    if rssi is None:
        return Text("░" * length, style="dim")
    # Map -100..-30 dBm to 0..100% (clamp).
    pct = max(0, min(100, (rssi + 100) * 100 // 70))
    filled = pct * length // 100
    bar = Text()
    bar.append("█" * filled, style=_rssi_color(rssi))
    bar.append("░" * (length - filled), style="dim")
    return bar


def _rssi_text(rssi: int | None) -> Text:
    if rssi is None:
        return Text("n/a       ", style="dim")
    return Text(f"{rssi:>4} dBm  ", style=_rssi_color(rssi))


def _rssi_color(rssi: int) -> str:
    if rssi >= -55:
        return "bold green"
    if rssi >= -75:
        return "yellow"
    return "red"


def _header_line() -> Text:
    h = Text(style="bold dim")
    h.append(f" {'★':<2}{'RSSI':>5}  {'ch':<4} {'band':<5}  {'AP / SSID':<28}  {'BSSID':<17}  {'width':<5}  {'phy':<8}")
    return h


def _scan_line(r: ScanResult, current_bssid: str | None, inv: NetworkInventory) -> Text:
    is_current = (
        r.bssid is not None
        and current_bssid is not None
        and r.bssid.lower() == current_bssid.lower()
    )
    star = "★" if is_current else " "
    rssi_color = _rssi_color(r.rssi_dbm) if r.rssi_dbm is not None else "dim"
    ap_name = inv.resolve(r.bssid)

    # On macOS without Location Services, scan-list ssid AND bssid are
    # both redacted (CoreWLAN's CWNetwork.ssid/.bssid/.ieData all come
    # back empty). The SCDynamicStore fallback that rescues the *current*
    # connection has no equivalent for the neighbor list. Make the
    # redacted state visibly distinct from "AP with empty SSID".
    redacted = r.bssid is None and r.ssid is None
    if redacted:
        label = "(redacted)"
        bssid_str = "(redacted)"
        label_style = "dim italic"
        bssid_style = "dim italic"
    else:
        label = ap_name or (r.ssid or "(no SSID)")
        bssid_str = r.bssid or "???"
        label_style = "cyan" if ap_name else "white"
        bssid_style = "dim"

    line = Text()
    line.append(f" {star:<2}", style="bold cyan" if is_current else "")
    line.append(f"{r.rssi_dbm if r.rssi_dbm is not None else '?':>4}  ", style=rssi_color)
    line.append(f"{r.channel if r.channel is not None else '?':<4} ", style="white")
    line.append(f"{r.channel_band or '?':<5}  ", style="white")
    line.append(f"{label[:28]:<28}  ", style=label_style)
    line.append(f"{bssid_str:<17}  ", style=bssid_style)
    line.append(f"{(str(r.channel_width_mhz)+'MHz') if r.channel_width_mhz else '?':<5}  ", style="white")
    line.append(f"{(r.phy_mode or '?'):<8}", style="white")
    if is_current:
        line.stylize("on grey15")
    return line


# ---------- app ----------

class WifiScopeApp(App):
    CSS = """
    Screen { layout: vertical; }
    """
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("p", "toggle_pause", "Pause"),
        Binding("r", "rescan", "Rescan"),
    ]

    def __init__(self, backend: WiFiBackend, inv: NetworkInventory) -> None:
        super().__init__()
        self._backend = backend
        self._inv = inv
        self._poller = WiFiPoller(backend)
        self._paused = False
        # Cache the most recent *non-empty* scan. CoreWLAN's throttle
        # produces empty results periodically; replacing the panel with
        # an empty list every time would make it flicker between 0 and
        # the real list, which is just noise to the user.
        self._cached_scan: list[ScanResult] = []
        self._last_successful_scan_at: float | None = None
        self._latest_bssid: str | None = None
        self.title = "wifiscope"
        self.sub_title = self._build_subtitle()

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield ConnectionPanel(id="conn")
        yield ScanPanel(id="scan")
        yield RoamLogPanel(id="roam")
        yield Footer()

    async def on_mount(self) -> None:
        self.run_worker(self._consume_events(), exclusive=True, name="poller")

    async def _consume_events(self) -> None:
        async for event in self._poller.events():
            if self._paused:
                continue
            if isinstance(event, ConnectionUpdate):
                self._latest_bssid = event.connection.bssid if event.connection else None
                self.query_one("#conn", ConnectionPanel).update_connection(
                    event.connection, self._inv
                )
            elif isinstance(event, ScanUpdate):
                if event.results:
                    self._cached_scan = event.results
                    self._last_successful_scan_at = time.monotonic()
                # Always re-render: even if results were empty, we want
                # the "scanned Ns ago" counter (which now refers to the
                # last *successful* scan) to keep ticking.
                self.query_one("#scan", ScanPanel).update_scan(
                    self._cached_scan,
                    self._latest_bssid,
                    self._last_successful_scan_at,
                    self._inv,
                )
            elif isinstance(event, RoamEvent):
                self.query_one("#roam", RoamLogPanel).append_roam(event, self._inv)

    def action_toggle_pause(self) -> None:
        self._paused = not self._paused
        self.sub_title = self._build_subtitle()

    def action_rescan(self) -> None:
        self._poller.force_rescan()

    def _build_subtitle(self) -> str:
        bits = [f"{len(self._inv.aps)} APs"]
        if self._inv.radio_overrides:
            bits.append(f"{len(self._inv.radio_overrides)} overrides")
        bits.append(self._backend.name)
        # Helper presence is informational; permission state shows up in
        # the Nearby APs panel title via the redacted-row check.
        if getattr(self._backend, "_helper_path", None):
            bits.append("helper")
        if self._paused:
            bits.append("PAUSED")
        return " · ".join(bits)
