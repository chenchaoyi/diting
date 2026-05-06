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
from dataclasses import dataclass
from datetime import datetime

from rich.console import Group
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Footer, Header, RichLog, Static

from .backend import WiFiBackend
from .models import Connection, ScanResult
from .network import NetworkInventory, band_label, cluster_label, format_bssid
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
        min-height: 16;
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
        header = Text()
        header.append(ap_name, style="bold cyan")
        if band:
            header.append(f"  {band}", style="cyan")
        if conn.country_code:
            header.append(f"  · country {conn.country_code}", style="dim")

        signal_bar = _signal_bar(conn.rssi_dbm)

        # Group of rows. Empty-valued rows (e.g. no IP yet) are omitted
        # rather than printing 'n/a' lines that take vertical space and
        # tell the user nothing.
        rows: list[tuple[str, str]] = [
            ("SSID", _fmt(conn.ssid)),
            ("BSSID", _fmt(conn.bssid)),
            (
                "Channel",
                f"{_fmt(conn.channel)}  {_fmt(conn.channel_width_mhz, ' MHz')}  "
                f"{_fmt(conn.channel_band)}",
            ),
            ("PHY / Sec", f"{_fmt(conn.phy_mode)}   {_fmt(conn.security)}"),
            (
                "Tx / Max",
                f"{_fmt(conn.tx_rate_mbps, ' Mbps')}  /  "
                f"{_fmt(conn.max_link_speed_mbps, ' Mbps')} max",
            ),
            (
                "MCS / NSS",
                f"{_fmt(conn.mcs_index)}  ·  {_fmt(conn.nss, ' streams')}",
            ),
            ("Noise", _fmt(conn.noise_dbm, " dBm")),
        ]
        if conn.ip_address or conn.router_ip:
            rows.append((
                "IP / Router",
                f"{_fmt(conn.ip_address)}  →  {_fmt(conn.router_ip)}",
            ))
        if conn.interface_mac:
            rows.append(("This Mac", conn.interface_mac))

        body = Text()
        for label, value in rows:
            body.append(f"  {label:<11}", style="dim")
            body.append(f"{value}\n")
        signal_line = Text()
        signal_line.append(f"  {'Signal':<11}", style="dim")
        signal_line.append(_rssi_text(conn.rssi_dbm))
        signal_line.append("  ")
        signal_line.append(signal_bar)

        # Footnote: Apple's transmitRate (current data rate, can include
        # frame aggregation) and maximumLinkSpeed (radio capability max
        # at the negotiated PHY/MCS) come from different APIs and do not
        # always satisfy "current ≤ max". The WiFi panel in System
        # Settings shows transmitRate only; we expose both, with this
        # caveat.
        if conn.tx_rate_mbps is not None and conn.max_link_speed_mbps is not None:
            footnote = Text()
            footnote.append(
                "  * Tx and Max use different CoreWLAN APIs and may diverge.",
                style="dim italic",
            )
            self.update(Group(header, Text(""), body, signal_line, Text(""), footnote))
        else:
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
        sort_mode: str = "signal",
    ) -> None:
        ago = "" if scanned_at is None else f"  · scanned {int(time.monotonic() - scanned_at)}s ago"
        all_redacted = bool(results) and all(
            r.bssid is None and r.ssid is None for r in results
        )
        identity = "  · identity TCC-redacted" if all_redacted else ""
        sort_label = f"  · sort: {sort_mode}"
        self.border_title = (
            f"Nearby APs ({len(results)}){ago}{identity}{sort_label}"
        )
        if not results:
            self.update(Text("(no APs from last scan — likely throttle, retrying)", style="dim italic"))
            return

        lines: list[Text] = [_header_line()]
        if sort_mode == "ap":
            # Group by physical AP (inventory name or cluster_label),
            # sort within each group by RSSI desc, sort groups by best
            # RSSI desc with the current AP's group floated to position
            # 0. Each group gets a 1-line summary header above its rows.
            for group in _group_by_ap(results, current_bssid, inv):
                lines.append(_group_header(group, inv))
                for r in group.rows:
                    lines.append(_scan_line(r, current_bssid, inv))
        else:
            # Default 'signal' mode. Pin the currently associated AP at
            # the top, sort everything else by RSSI desc — without the
            # pin a corporate scan with 100+ rows would push the user's
            # own row off the viewport.
            cur = (current_bssid or "").lower()
            current_rows = [r for r in results if r.bssid and r.bssid.lower() == cur]
            other_rows = [r for r in results if not (r.bssid and r.bssid.lower() == cur)]
            other_rows.sort(
                key=lambda r: r.rssi_dbm if r.rssi_dbm is not None else -200,
                reverse=True,
            )
            for r in current_rows + other_rows:
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

@dataclass(frozen=True, slots=True)
class _APGroup:
    """One physical AP and the BSSIDs we observed it broadcasting."""
    key: str            # inventory name when matched, else cluster_label
    is_current: bool    # whether the user's current connection is in here
    rows: tuple[ScanResult, ...]


def _group_by_ap(
    results: list[ScanResult],
    current_bssid: str | None,
    inv: NetworkInventory,
) -> list[_APGroup]:
    """Bucket scan rows by their physical AP, then sort.

    Group key is `inv.resolve(bssid)` if known, else `cluster_label(bssid)`
    — this means inventory names and auto-clustered MACs share the same
    grouping space (an AP that has both is impossible since a name can
    only resolve to one inventory entry).

    Within each group rows are sorted by RSSI desc. Groups themselves
    are sorted by the best RSSI in each group, with the group containing
    the user's current connection floated to the top regardless of
    signal — same rationale as the pin in 'signal' mode.
    """
    buckets: dict[str, list[ScanResult]] = {}
    for r in results:
        key = inv.resolve(r.bssid)
        if key is None:
            key = cluster_label(r.bssid) if r.bssid else "(redacted)"
        buckets.setdefault(key, []).append(r)
    cur = (current_bssid or "").lower()
    groups: list[_APGroup] = []
    for key, rows in buckets.items():
        rows.sort(
            key=lambda r: r.rssi_dbm if r.rssi_dbm is not None else -200,
            reverse=True,
        )
        is_current = any(r.bssid and r.bssid.lower() == cur for r in rows)
        groups.append(_APGroup(key=key, is_current=is_current, rows=tuple(rows)))
    groups.sort(
        key=lambda g: (
            0 if g.is_current else 1,
            -max(
                (r.rssi_dbm if r.rssi_dbm is not None else -200) for r in g.rows
            ),
        )
    )
    return groups


def _group_header(group: _APGroup, inv: NetworkInventory) -> Text:
    """Render a one-line summary above each group in 'ap' mode."""
    rssis = [r.rssi_dbm for r in group.rows if r.rssi_dbm is not None]
    best = max(rssis) if rssis else None
    worst = min(rssis) if rssis else None
    ssids = sorted({r.ssid for r in group.rows if r.ssid})
    n = len(group.rows)
    bssid_word = "BSSID" if n == 1 else "BSSIDs"
    rssi_part = (
        f"{best} dBm" if best == worst or best is None or worst is None
        else f"{best}..{worst} dBm"
    )
    ssid_part = (
        f"  ·  {len(ssids)} SSID{'s' if len(ssids) != 1 else ''}"
        if ssids else ""
    )
    line = Text()
    line.append("  ── ", style="dim")
    # cluster labels start with '?'; inventory names never do.
    name_style = "bold dim" if group.key.startswith("?") else "bold cyan"
    line.append(group.key, style=name_style)
    line.append(f"  ·  {n} {bssid_word}  ·  {rssi_part}{ssid_part}",
                style="dim")
    if group.is_current:
        line.append("  · current", style="bold cyan")
    return line


def _merge_current(
    scan: list[ScanResult], conn: Connection | None
) -> list[ScanResult]:
    """Ensure the panel shows a row for the currently associated AP, with
    Connection-derived values, even when CoreWLAN's scan omitted it or
    reported stale channel data.

    Two behaviours combined:
    - If the scan list does not include the associated BSSID, prepend a
      synthetic row built from the Connection.
    - If it does, replace the existing scan row with the synthetic row
      so the user sees the same RSSI / channel as the Connection panel
      above. Scan beacons can lag the radio's actual association state
      (DFS / channel hops) and we do not want the panel to show two
      different channels for the same BSSID at the same instant.
    """
    if conn is None or conn.bssid is None:
        return scan
    target = conn.bssid.lower()
    synth = ScanResult(
        ssid=conn.ssid,
        bssid=conn.bssid,
        rssi_dbm=conn.rssi_dbm,
        noise_dbm=conn.noise_dbm,
        channel=conn.channel,
        channel_width_mhz=conn.channel_width_mhz,
        channel_band=conn.channel_band,
        phy_mode=conn.phy_mode,
        security=conn.security,
        timestamp=conn.timestamp,
        country_code=conn.country_code,
    )
    out: list[ScanResult] = []
    replaced = False
    for r in scan:
        if r.bssid and r.bssid.lower() == target:
            out.append(synth)
            replaced = True
        else:
            out.append(r)
    if not replaced:
        return [synth, *out]
    return out


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


_COL_RSSI = 4
_COL_SIGNAL = 8
_COL_CH = 4
_COL_BAND = 4
_COL_AP = 18
_COL_SSID = 22
_COL_BSSID = 17
_COL_WIDTH = 6


def _header_line() -> Text:
    h = Text(style="bold dim")
    h.append(
        f" {'★':<2}{'RSSI':>{_COL_RSSI}}  {'signal':<{_COL_SIGNAL}}  "
        f"{'ch':<{_COL_CH}}{'band':<{_COL_BAND}}  "
        f"{'AP host':<{_COL_AP}}  {'SSID':<{_COL_SSID}}  "
        f"{'BSSID':<{_COL_BSSID}}  {'width':<{_COL_WIDTH}}"
    )
    return h


def _scan_line(r: ScanResult, current_bssid: str | None, inv: NetworkInventory) -> Text:
    is_current = (
        r.bssid is not None
        and current_bssid is not None
        and r.bssid.lower() == current_bssid.lower()
    )
    star = "★" if is_current else " "
    rssi_color = _rssi_color(r.rssi_dbm) if r.rssi_dbm is not None else "dim"

    # When CoreWLAN is fully TCC-redacted (no helper, no Location grant),
    # ssid AND bssid both come back None. Render that state distinctly so
    # it does not look like an AP with an empty SSID.
    redacted = r.bssid is None and r.ssid is None
    if redacted:
        ap_text, ap_style = "(redacted)", "dim italic"
        ssid_text, ssid_style = "(redacted)", "dim italic"
        bssid_text, bssid_style = "(redacted)", "dim italic"
    else:
        ap_name = inv.resolve(r.bssid)
        if ap_name is not None:
            ap_text, ap_style = ap_name, "cyan"
        else:
            # Auto-discovery: cluster_label gives the same string for every
            # radio / VAP of the same physical AP, even when the user has
            # not added it to inventory. Lets a brand-new install make
            # sense of the scan without any config.
            ap_text, ap_style = cluster_label(r.bssid), "dim"
        # An empty SSID in a beacon is the 802.11 'hidden' bit — the AP
        # is broadcasting normally, just with the SSID IE blanked. Use
        # "(hidden)" rather than "(no SSID)" since the SSID does exist,
        # it just is not in the air.
        ssid_text = r.ssid or "(hidden)"
        ssid_style = "white" if r.ssid else "dim italic"
        bssid_text = r.bssid or "???"
        bssid_style = "dim"

    # band display uses the short form (2.4G / 5G) derived from the
    # channel number — fixed width 4 keeps subsequent columns aligned.
    # The verbose "2.4 GHz" form would overflow column 4 and shift
    # every column to the right by two characters on 2.4 GHz rows.
    band_short = band_label(r.channel) or "?"

    line = Text()
    line.append(f" {star:<2}", style="bold cyan" if is_current else "")
    line.append(f"{r.rssi_dbm if r.rssi_dbm is not None else '?':>{_COL_RSSI}}  ", style=rssi_color)
    line.append(_signal_bar(r.rssi_dbm, length=_COL_SIGNAL))
    line.append("  ")
    line.append(f"{r.channel if r.channel is not None else '?':<{_COL_CH}}", style="white")
    line.append(f"{band_short:<{_COL_BAND}}  ", style="white")
    line.append(f"{ap_text[:_COL_AP]:<{_COL_AP}}  ", style=ap_style)
    line.append(f"{ssid_text[:_COL_SSID]:<{_COL_SSID}}  ", style=ssid_style)
    line.append(f"{bssid_text:<{_COL_BSSID}}  ", style=bssid_style)
    width_str = f"{r.channel_width_mhz}MHz" if r.channel_width_mhz else "?"
    line.append(f"{width_str:<{_COL_WIDTH}}", style="white")
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
        Binding("s", "cycle_sort", "Sort"),
        Binding("c", "reroam", "Re-roam"),
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
        # Latest Connection — merged into the scan list as a synthetic
        # row when CoreWLAN's scan omits the currently associated AP
        # (it usually does; the OS treats scan as "find roam targets",
        # not "list everything").
        self._latest_connection: Connection | None = None
        # Scan-list sort mode — toggled by the 's' binding. 'ap' (the
        # default) groups by physical AP with a per-group summary line;
        # 'signal' falls back to a flat RSSI-sorted list with the
        # current AP pinned. The grouped view is more readable on dense
        # corporate networks where one AP broadcasts many BSSIDs.
        self._sort_mode: str = "ap"
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
                self._latest_connection = event.connection
                self._latest_bssid = (
                    event.connection.bssid if event.connection else None
                )
                self.query_one("#conn", ConnectionPanel).update_connection(
                    event.connection, self._inv
                )
                # Refresh the scan panel too so the synthesised row for
                # the current AP picks up live RSSI / channel changes
                # between scans (1 Hz vs 7 Hz).
                self._refresh_scan_panel()
            elif isinstance(event, ScanUpdate):
                if event.results:
                    self._cached_scan = event.results
                    self._last_successful_scan_at = time.monotonic()
                self._refresh_scan_panel()
            elif isinstance(event, RoamEvent):
                self.query_one("#roam", RoamLogPanel).append_roam(event, self._inv)

    def _refresh_scan_panel(self) -> None:
        merged = _merge_current(self._cached_scan, self._latest_connection)
        self.query_one("#scan", ScanPanel).update_scan(
            merged,
            self._latest_bssid,
            self._last_successful_scan_at,
            self._inv,
            self._sort_mode,
        )

    def action_toggle_pause(self) -> None:
        self._paused = not self._paused
        self.sub_title = self._build_subtitle()

    def action_rescan(self) -> None:
        self._poller.force_rescan()

    def action_cycle_sort(self) -> None:
        self._sort_mode = "ap" if self._sort_mode == "signal" else "signal"
        self.sub_title = self._build_subtitle()
        # Rebuild the scan panel immediately so the user sees the change
        # without waiting for the next 1 Hz connection update.
        self._refresh_scan_panel()

    def action_reroam(self) -> None:
        """Force a fresh association so the OS reselects the best BSSID.

        macOS does not roam off a 'good enough' AP (~ -75 dBm threshold,
        independent of nearby alternatives). This binding cycles the
        WiFi radio off then on, which is the same path as
        click-menu-off, click-menu-on — full auto-join with Keychain
        credentials, works for both WPA personal and 802.1X Enterprise.
        """
        ok = bool(getattr(self._backend, "force_reroam", lambda: False)())
        if ok:
            self.notify(
                "WiFi off → on — reconnecting via auto-join (2-5 s)"
            )
        else:
            self.notify("no WiFi interface", severity="warning")

    def _build_subtitle(self) -> str:
        bits = [f"{len(self._inv.aps)} APs"]
        if self._inv.radio_overrides:
            bits.append(f"{len(self._inv.radio_overrides)} overrides")
        bits.append(self._backend.name)
        # Helper presence is informational; permission state shows up in
        # the Nearby APs panel title via the redacted-row check.
        if getattr(self._backend, "_helper_path", None):
            bits.append("helper")
        bits.append(f"sort: {self._sort_mode}")
        if self._paused:
            bits.append("PAUSED")
        return " · ".join(bits)
