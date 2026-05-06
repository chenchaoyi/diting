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
from textual.containers import Center, Vertical, VerticalScroll
from textual.screen import ModalScreen
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


class ScanPanel(VerticalScroll):
    DEFAULT_CSS = """
    ScanPanel {
        height: 1fr;
        border: heavy $accent;
        padding: 0 1;
    }
    ScanPanel > #scan-body {
        height: auto;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static(Text("(scanning...)", style="dim italic"), id="scan-body")

    def on_mount(self) -> None:
        self.border_title = "Nearby BSSIDs"

    def update_scan(
        self,
        results: list[ScanResult],
        current: Connection | None,
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
            f"Nearby BSSIDs ({len(results)}){ago}{identity}{sort_label}"
        )
        if not results:
            self.query_one("#scan-body", Static).update(
                Text("(no APs from last scan — likely throttle, retrying)",
                     style="dim italic")
            )
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
        self.query_one("#scan-body", Static).update(Group(*lines))


class EnvironmentPanel(Static):
    DEFAULT_CSS = """
    EnvironmentPanel {
        height: auto;
        min-height: 7;
        border: heavy $accent;
        padding: 0 1;
    }
    """

    def on_mount(self) -> None:
        self.border_title = "Diagnostics"
        self.update(Text("(waiting for scan data...)", style="dim italic"))

    def update_environment(
        self,
        results: list[ScanResult],
        current: Connection | None,
    ) -> None:
        self.border_title = "Diagnostics"
        if not results:
            self.update(Text("(waiting for scan data...)", style="dim italic"))
            return
        self.update(Group(*_environment_lines(results, current)))


class HelpScreen(ModalScreen):
    """Modal overlay that documents the tool, the bindings, and the
    project. Triggered by the 'h' binding from WifiScopeApp; dismissed
    by Esc or h again.

    The content lives here rather than scattered around the README
    because at the moment a user reaches for help they want it in the
    terminal in front of them, not on a webpage.
    """

    BINDINGS = [
        Binding("escape,h,q", "app.pop_screen", "Close"),
    ]

    DEFAULT_CSS = """
    HelpScreen {
        align: center middle;
    }
    HelpScreen > #help-box {
        width: 78;
        height: auto;
        max-height: 90%;
        border: heavy $accent;
        padding: 1 2;
        background: $surface;
    }
    HelpScreen #help-box Static {
        height: auto;
    }
    """

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static(_help_content(), id="help-content"),
            id="help-box",
        )


def _help_content() -> Text:
    """Build the help dialog body as a Rich Text. OSC 8 link on the
    GitHub URL renders clickable in modern terminals; falls back to
    plain text where unsupported.
    """
    body = Text(no_wrap=False)

    def section(title: str) -> None:
        body.append("\n" + title + "\n", style="bold yellow")

    def line(label: str, desc: str) -> None:
        body.append("  ")
        body.append(f"{label:<6}", style="bold")
        body.append(desc + "\n")

    body.append("wifiscope", style="bold cyan")
    body.append(
        "  ·  terminal WiFi monitor for macOS, focused on roaming visibility.\n",
        style="dim",
    )

    section("What")
    body.append(
        "  See which AP you are on, when your Mac switches, and how strong\n"
        "  the signal is — the things macOS hides from its own WiFi panel.\n"
    )

    section("Panels")
    line("Conn.", "current AP, signal bar, link / IP / radio details")
    line("Scan",  "every BSSID in range, grouped by physical AP")
    line("Roam",  "band-switch and inter-AP roam events as they happen")

    section("Bindings")
    line("q", "quit")
    line("p", "pause / resume polling")
    line("r", "force a rescan now (CoreWLAN ~5s throttle still applies)")
    line("s", "cycle scan sort:  by AP  ↔  by signal")
    line("c", "force re-roam (cycle WiFi off/on so the OS re-picks the")
    body.append(" " * 8 + "strongest BSSID — fixes sticky associations)\n")
    line("h", "toggle this help")
    line("b", "open Wi-Fi basics for SSID, BSSID, channel, band, security")

    section("Inventory")
    body.append(
        "  Drop ~/.config/wifiscope/aps.yaml listing your APs by management\n"
        "  MAC; wifiscope renders friendly names ('1F-bedroom') in place of\n"
        "  MAC fragments ('?af:5e:a7'). Without inventory the tool still\n"
        "  works — it auto-clusters BSSIDs by chip serial bits — but each\n"
        "  AP is just labelled by its three middle MAC octets.\n"
    )

    section("Helper")
    body.append(
        "  macOS 14.4+ redacts the SSID and BSSID of every AP in the scan\n"
        "  list to None unless the calling process has Location Services\n"
        "  permission, and a Python CLI launched from Terminal cannot get\n"
        "  on that list. The helper is a tiny Swift `.app` bundle that\n"
        "  can — wifiscope auto-builds and `open`s it once on first launch,\n"
        "  the user clicks Allow in the macOS prompt, and from then on\n"
        "  wifiscope shells out to the bundle's binary for unredacted scan\n"
        "  data. The TCC grant is persistent; the helper window auto-\n"
        "  closes on grant. Without it the Nearby APs panel works but\n"
        "  every row shows '(redacted)' for SSID and BSSID.\n"
    )

    section("Tunables")
    body.append(
        "  WIFISCOPE_SCAN_INTERVAL=N    seconds between scans, default 7.\n"
        "                                CoreWLAN throttles around 5 s,\n"
        "                                so values below ~6 yield empty\n"
        "                                scans every other call. Min 3.\n"
        "  WIFISCOPE_INVENTORY=path     override aps.yaml location.\n"
        "  WIFISCOPE_HELPER=path        override helper.app path.\n"
    )

    body.append("\n")
    body.append("─" * 70 + "\n", style="dim")
    body.append("made by ", style="dim")
    body.append("ccy", style="bold dim")
    body.append("  ·  ", style="dim")
    body.append(
        "github.com/chenchaoyi/wifiscope",
        style="dim underline link https://github.com/chenchaoyi/wifiscope",
    )
    body.append("\n")
    body.append("Esc or h to close", style="dim italic")
    return body


class BasicsScreen(ModalScreen):
    """Short glossary for users who are not Wi-Fi specialists."""

    BINDINGS = [
        Binding("escape,b,q", "app.pop_screen", "Close"),
    ]

    DEFAULT_CSS = """
    BasicsScreen {
        align: center middle;
    }
    BasicsScreen > #basics-box {
        width: 84;
        height: auto;
        max-height: 90%;
        border: heavy $accent;
        padding: 1 2;
        background: $surface;
    }
    BasicsScreen #basics-box Static {
        height: auto;
    }
    """

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static(_basics_content(), id="basics-content"),
            id="basics-box",
        )


def _basics_content() -> Text:
    body = Text(no_wrap=False)

    def term(name: str, desc: str) -> None:
        body.append(f"\n{name}\n", style="bold yellow")
        body.append("  " + desc + "\n")

    body.append("Wi-Fi Basics", style="bold cyan")
    body.append("  ·  the words wifiscope uses in the dashboard\n", style="dim")

    term(
        "SSID",
        "The Wi-Fi name people choose from, such as Meituan or Guest. "
        "Many access points can broadcast the same SSID.",
    )
    term(
        "BSSID",
        "The radio identity behind one SSID on one AP/radio. A single "
        "physical AP may expose many BSSIDs when it broadcasts several "
        "SSIDs on 2.4 GHz and 5 GHz.",
    )
    term(
        "AP host",
        "wifiscope's best guess for the physical access point that owns "
        "a BSSID. Inventory names are most accurate; ? labels are inferred "
        "from MAC address patterns.",
    )
    term(
        "RSSI / Signal",
        "Received signal strength. Less negative is stronger: -45 dBm is "
        "excellent, -65 dBm is usable, and around -75 dBm is weak.",
    )
    term(
        "Noise / SNR",
        "Noise is background radio energy. SNR is signal minus noise; "
        "higher is better. Low SNR can cause retries even when the AP is visible.",
    )
    term(
        "Band",
        "The radio range: 2.4 GHz reaches farther but is crowded; 5 GHz is "
        "faster with shorter range; 6 GHz is newer, cleaner, and shorter range.",
    )
    term(
        "Channel",
        "The slice of a band the AP is using. APs on the same or nearby "
        "channels share airtime, so a quieter channel can help.",
    )
    term(
        "Width",
        "How much spectrum the AP uses, such as 20/40/80 MHz. Wider can be "
        "faster but also easier to interfere with, especially on 2.4 GHz.",
    )
    term(
        "Security",
        "OPEN means no Wi-Fi-layer password/encryption. ENT means enterprise "
        "authentication. WPA2/WPA3 are password or modern secured modes.",
    )
    term(
        "Roam",
        "When the Mac moves from one BSSID to another. Same SSID does not "
        "guarantee the Mac picked the strongest or best AP.",
    )
    term(
        "Roam score",
        "A simple 0-100 guide, not a standard. It rewards strong RSSI, good "
        "SNR, cleaner bands, and quieter channels, and penalizes weak signal, "
        "busy channels, open networks, and security mismatches. A better "
        "candidate is shown only when the same SSID scores clearly higher.",
    )

    body.append("\n")
    body.append("Esc or b to close", style="dim italic")
    return body


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


def _environment_lines(
    results: list[ScanResult], current: Connection | None
) -> list[Text]:
    return [
        _visible_networks_line(results),
        _environment_warnings_line(results, current),
        _recommendations_line(results),
        _health_line(results, current),
        _score_line(results, current),
    ]


def _visible_networks_line(results: list[ScanResult]) -> Text:
    counts = _band_counts(results)
    hidden = sum(1 for r in results if not r.ssid and not (r.ssid is None and r.bssid is None))
    redacted = sum(1 for r in results if r.ssid is None and r.bssid is None)
    countries = _country_codes(results)

    line = Text()
    line.append("Visible BSSIDs  ", style="bold dim")
    line.append(
        f"{len(results)} total  "
        f"2.4 GHz: {counts['2.4G']}  "
        f"5 GHz: {counts['5G']}  "
        f"6 GHz: {counts['6G']}",
        style="white",
    )
    if hidden:
        line.append(f"  hidden in this scan: {hidden}", style="dim")
    if redacted:
        line.append(f"  redacted: {redacted}", style="dim italic")
    if countries:
        style = "yellow" if len(countries) > 1 else "dim"
        line.append(f"  country codes: {'/'.join(countries)}", style=style)
    return line


def _environment_warnings_line(
    results: list[ScanResult], current: Connection | None
) -> Text:
    open_count = sum(1 for r in results if r.security == "Open")
    ht40_2g = sum(
        1 for r in results
        if _band_bucket(r) == "2.4G" and (r.channel_width_mhz or 0) >= 40
    )
    current_load = _current_channel_load(results, current)
    warnings: list[tuple[str, str]] = []
    if open_count:
        warnings.append((f"{open_count} open/no-password BSSIDs", "yellow"))
    if ht40_2g:
        warnings.append((f"{ht40_2g} wide 2.4 GHz BSSIDs", "yellow"))
    if current_load is not None:
        style = "yellow" if current_load >= 5 else "dim"
        warnings.append((f"{current_load} other BSSIDs on your channel", style))
    if len(_country_codes(results)) > 1:
        warnings.append(("mixed country codes nearby", "yellow"))

    line = Text()
    line.append("Things to notice  ", style="bold dim")
    if not warnings:
        line.append("No obvious environment warnings from the scan.", style="green")
        return line
    for i, (msg, style) in enumerate(warnings):
        if i:
            line.append("  ·  ", style="dim")
        line.append(msg, style=style)
    return line


def _recommendations_line(results: list[ScanResult]) -> Text:
    rec_2g = _recommended_channel(results, "2.4G")
    rec_5g = _recommended_channel(results, "5G")
    line = Text()
    line.append("Least crowded channels  ", style="bold dim")
    line.append("Estimated from the scan.", style="dim")
    if rec_2g is not None:
        line.append(_channel_hint("2.4 GHz", rec_2g, results))
    if rec_5g is not None:
        line.append(_channel_hint("5 GHz", rec_5g, results))
    return line


def _channel_hint(label: str, channel: int, results: list[ScanResult]) -> Text:
    text = Text()
    text.append(f"  {label}: ch{channel}", style="cyan")
    if not any(r.channel == channel for r in results):
        text.append(" (no AP heard)", style="dim")
    return text


def _environment_line(results: list[ScanResult], current: Connection | None) -> Text:
    """Compact Wireless-Diagnostics-style summary of the visible RF scene."""
    counts = _band_counts(results)
    hidden = sum(1 for r in results if not r.ssid and not (r.ssid is None and r.bssid is None))
    redacted = sum(1 for r in results if r.ssid is None and r.bssid is None)
    open_count = sum(1 for r in results if r.security == "Open")
    ht40_2g = sum(
        1 for r in results
        if _band_bucket(r) == "2.4G" and (r.channel_width_mhz or 0) >= 40
    )
    countries = _country_codes(results)
    rec_2g = _recommended_channel(results, "2.4G")
    rec_5g = _recommended_channel(results, "5G")
    country_part = "CC " + (
        "/".join(countries) if countries else "?"
    )
    current_load = _current_channel_load(results, current)

    line = Text()
    line.append("Env  ", style="bold dim")
    line.append(
        f"{len(results)} BSSIDs  "
        f"2.4G {counts['2.4G']}  5G {counts['5G']}  6G {counts['6G']}  "
        f"hidden in this scan: {hidden}",
        style="white",
    )
    if redacted:
        line.append(f"  redacted {redacted}", style="dim italic")
    if open_count:
        line.append(f"  open {open_count}", style="yellow")
    if ht40_2g:
        line.append(f"  2.4G HT40 {ht40_2g}", style="yellow")
    line.append(f"  {country_part}", style="yellow" if len(countries) > 1 else "dim")
    if current_load is not None:
        line.append(f"  current ch peers {current_load}", style="dim")
    if rec_2g is not None or rec_5g is not None:
        line.append("  best", style="dim")
        if rec_2g is not None:
            line.append(f" 2.4G ch{rec_2g}", style="cyan")
        if rec_5g is not None:
            line.append(f" 5G ch{rec_5g}", style="cyan")
    return line


def _health_line(results: list[ScanResult], current: Connection | None) -> Text:
    """Explain the current association in terms a human can act on."""
    line = Text()
    line.append("Current link  ", style="bold dim")
    if current is None:
        line.append("not associated", style="dim italic")
        return line

    issues: list[tuple[str, str]] = []
    if current.rssi_dbm is not None:
        if current.rssi_dbm <= -75:
            issues.append((f"weak signal {current.rssi_dbm} dBm", "red"))
        elif current.rssi_dbm <= -67:
            issues.append((f"fair signal {current.rssi_dbm} dBm", "yellow"))
    if current.rssi_dbm is not None and current.noise_dbm is not None:
        snr = current.rssi_dbm - current.noise_dbm
        if snr < 25:
            issues.append((f"SNR {snr} dB", "yellow"))

    better = _best_same_ssid_candidate(results, current)
    if better is not None:
        candidate, delta = better
        label = _fmt(candidate.bssid)
        if candidate.channel is not None:
            label += f" ch{candidate.channel}"
        issues.append((f"stronger same-name AP nearby: +{delta} dB ({label})", "bold cyan"))

    if not issues:
        line.append("Looks OK", style="green")
        return line
    for i, (msg, style) in enumerate(issues):
        if i:
            line.append("  ")
        line.append(msg, style=style)
    if better is not None:
        line.append("  press c to re-roam", style="dim")
    return line


def _score_line(results: list[ScanResult], current: Connection | None) -> Text:
    line = Text()
    line.append("Roam score  ", style="bold dim")
    if current is None:
        line.append("not associated", style="dim italic")
        return line
    current_score = _link_score(current, results, baseline=current)
    candidate = _best_roam_candidate(results, current)
    line.append(f"current {current_score.score}/100", style=_score_style(current_score.score))
    if current_score.reasons:
        line.append(f" ({', '.join(current_score.reasons[:2])})", style="dim")
    if candidate is None:
        line.append("  ·  no clearly better same-SSID BSSID", style="dim")
        return line
    row, score = candidate
    delta = score.score - current_score.score
    line.append(
        f"  ·  better candidate {score.score}/100",
        style=_score_style(score.score),
    )
    line.append(f" (+{delta})", style="cyan")
    if row.channel is not None:
        line.append(f" ch{row.channel}", style="dim")
    if row.bssid:
        line.append(f" {row.bssid}", style="dim")
    if score.reasons:
        line.append(f" ({', '.join(score.reasons[:2])})", style="dim")
    line.append("  press c to re-roam", style="dim")
    return line


@dataclass(frozen=True, slots=True)
class _LinkScore:
    score: int
    reasons: tuple[str, ...]


def _link_score(
    link: Connection | ScanResult,
    results: list[ScanResult],
    *,
    baseline: Connection,
) -> _LinkScore:
    score = 50
    reasons: list[str] = []
    rssi = link.rssi_dbm
    if rssi is None:
        reasons.append("no signal reading")
    elif rssi >= -55:
        score += 30
        reasons.append("strong signal")
    elif rssi >= -67:
        score += 20
        reasons.append("good signal")
    elif rssi >= -75:
        score += 8
        reasons.append("usable signal")
    else:
        score -= 15
        reasons.append("weak signal")

    noise = link.noise_dbm
    if rssi is not None and noise is not None:
        snr = rssi - noise
        if snr >= 35:
            score += 10
        elif snr >= 25:
            score += 5
        else:
            score -= 8
            reasons.append("low SNR")

    band = _band_bucket(link)
    if band == "6G":
        score += 8
        reasons.append("cleaner 6 GHz band")
    elif band == "5G":
        score += 5
        reasons.append("5 GHz")
    elif band == "2.4G":
        score -= 5
        reasons.append("2.4 GHz crowding risk")

    channel_load = _channel_load(results, link.channel, exclude_bssid=link.bssid)
    if channel_load >= 8:
        score -= 10
        reasons.append("busy channel")
    elif channel_load >= 4:
        score -= 5
        reasons.append("some channel sharing")

    if link.security and baseline.security and link.security != baseline.security:
        score -= 15
        reasons.append("different security")
    elif link.security == "Open":
        score -= 10
        reasons.append("open network")

    return _LinkScore(score=max(0, min(100, score)), reasons=tuple(reasons))


def _best_roam_candidate(
    results: list[ScanResult],
    current: Connection,
    *,
    min_score_gain: int = 10,
) -> tuple[ScanResult, _LinkScore] | None:
    if not current.ssid:
        return None
    current_score = _link_score(current, results, baseline=current)
    cur_bssid = (current.bssid or "").lower()
    candidates = [
        r for r in results
        if r.ssid == current.ssid
        and r.bssid
        and r.bssid.lower() != cur_bssid
    ]
    if not candidates:
        return None
    scored = [(r, _link_score(r, results, baseline=current)) for r in candidates]
    best = max(scored, key=lambda item: item[1].score)
    if best[1].score - current_score.score < min_score_gain:
        return None
    return best


def _score_style(score: int) -> str:
    if score >= 75:
        return "green"
    if score >= 55:
        return "yellow"
    return "red"


def _band_counts(results: list[ScanResult]) -> dict[str, int]:
    counts = {"2.4G": 0, "5G": 0, "6G": 0}
    for r in results:
        band = _band_bucket(r)
        if band in counts:
            counts[band] += 1
    return counts


def _country_codes(results: list[ScanResult]) -> list[str]:
    return sorted({r.country_code.upper() for r in results if r.country_code})


def _band_bucket(r: ScanResult) -> str | None:
    label = band_label(r.channel)
    if label is not None:
        return label
    if r.channel_band == "6 GHz":
        return "6G"
    return None


def _current_channel_load(
    results: list[ScanResult], current: Connection | None
) -> int | None:
    if current is None or current.channel is None:
        return None
    return _channel_load(results, current.channel, exclude_bssid=current.bssid)


def _channel_load(
    results: list[ScanResult],
    channel: int | None,
    *,
    exclude_bssid: str | None = None,
) -> int:
    if channel is None:
        return 0
    exclude = (exclude_bssid or "").lower()
    return sum(
        1 for r in results
        if r.channel == channel
        and not (r.bssid and r.bssid.lower() == exclude)
    )


def _recommended_channel(results: list[ScanResult], band: str) -> int | None:
    """Pick a low-observed-load channel from common non-DFS choices.

    This is scan-based occupancy, not Apple's private CCA measurement.
    Stronger APs cost more; for 2.4 GHz adjacent channels also count.
    """
    seen = [r for r in results if _band_bucket(r) == band and r.channel is not None]
    if band == "2.4G":
        candidates = [1, 6, 11]
    else:
        # Include channels actually visible in the scan so the hint
        # feels connected to the table, then add common non-DFS choices
        # for nearby open alternatives.
        visible = sorted({r.channel for r in seen if r.channel is not None})
        candidates = sorted({*visible, 36, 40, 44, 48, 149, 153, 157, 161})
    if not seen:
        return candidates[0] if candidates else None

    def score(ch: int) -> int:
        total = 0
        for r in seen:
            assert r.channel is not None
            distance = abs(r.channel - ch)
            if band == "2.4G" and distance > 4:
                continue
            if band != "2.4G" and distance != 0:
                continue
            weight = 1
            if r.rssi_dbm is not None:
                if r.rssi_dbm >= -65:
                    weight = 4
                elif r.rssi_dbm >= -75:
                    weight = 2
            total += weight
        return total

    return min(candidates, key=lambda ch: (score(ch), ch))


def _best_same_ssid_candidate(
    results: list[ScanResult],
    current: Connection,
    *,
    threshold_db: int = 15,
) -> tuple[ScanResult, int] | None:
    if not current.ssid or current.rssi_dbm is None:
        return None
    cur_bssid = (current.bssid or "").lower()
    candidates = [
        r for r in results
        if r.ssid == current.ssid
        and r.rssi_dbm is not None
        and not (r.bssid and r.bssid.lower() == cur_bssid)
    ]
    if not candidates:
        return None
    best = max(candidates, key=lambda r: r.rssi_dbm or -200)
    delta = (best.rssi_dbm or -200) - current.rssi_dbm
    if delta < threshold_db:
        return None
    return best, delta


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
_COL_CH = 8
_COL_BAND = 4
_COL_AP = 18
_COL_SSID = 22
_COL_SEC = 7
_COL_BSSID = 17
_COL_WIDTH = 6


def _header_line() -> Text:
    h = Text(style="bold dim")
    h.append(
        f" {'★':<2}{'RSSI':>{_COL_RSSI}}  {'signal':<{_COL_SIGNAL}}  "
        f"{'channel':<{_COL_CH}}  {'band':<{_COL_BAND}}  "
        f"{'AP host':<{_COL_AP}}  {'SSID':<{_COL_SSID}}  "
        f"{'security':<{_COL_SEC}}  {'BSSID':<{_COL_BSSID}}  "
        f"{'width':<{_COL_WIDTH}}"
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
        security_text, security_style = "?", "dim"
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
        security_text, security_style = _security_badge(r.security)

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
    line.append(f"{r.channel if r.channel is not None else '?':<{_COL_CH}}  ", style="white")
    line.append(f"{band_short:<{_COL_BAND}}  ", style="white")
    line.append(f"{ap_text[:_COL_AP]:<{_COL_AP}}  ", style=ap_style)
    line.append(f"{ssid_text[:_COL_SSID]:<{_COL_SSID}}  ", style=ssid_style)
    line.append(f"{security_text:<{_COL_SEC}}  ", style=security_style)
    line.append(f"{bssid_text:<{_COL_BSSID}}  ", style=bssid_style)
    width_str = f"{r.channel_width_mhz}MHz" if r.channel_width_mhz else "?"
    line.append(f"{width_str:<{_COL_WIDTH}}", style="white")
    if is_current:
        line.stylize("on grey15")
    return line


def _security_badge(security: str | None) -> tuple[str, str]:
    if security == "Open":
        return "OPEN", "bold yellow"
    if security is None:
        return "?", "dim"
    if "Enterprise" in security:
        return "ENT", "dim"
    if "WPA3" in security:
        return "WPA3", "dim"
    if "WPA2" in security:
        return "WPA2", "dim"
    if "WPA" in security:
        return "WPA", "dim"
    return security[:_COL_SEC], "dim"


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
        Binding("h", "show_help", "Help"),
        Binding("b", "show_basics", "Basics"),
    ]

    def __init__(
        self,
        backend: WiFiBackend,
        inv: NetworkInventory,
        *,
        scan_interval: float = 7.0,
    ) -> None:
        super().__init__()
        self._backend = backend
        self._inv = inv
        self._poller = WiFiPoller(backend, scan_interval=scan_interval)
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
        yield EnvironmentPanel(id="env")
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
        self.query_one("#env", EnvironmentPanel).update_environment(
            merged,
            self._latest_connection,
        )
        self.query_one("#scan", ScanPanel).update_scan(
            merged,
            self._latest_connection,
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

    def action_show_help(self) -> None:
        self.push_screen(HelpScreen())

    def action_show_basics(self) -> None:
        self.push_screen(BasicsScreen())

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
        # Header subtitle is dynamic state and live diagnostics — what
        # changes as the user interacts, plus the poll cadence so the
        # user can see when the next scan is due. Static facts
        # (inventory size, backend name, helper presence) live in the
        # AttributionBar / panel titles instead.
        scan_s = int(getattr(self._poller, "_scan_interval", 0))
        bits = [f"sort: {self._sort_mode}"]
        if scan_s:
            bits.append(f"scan {scan_s}s")
        if self._paused:
            bits.append("PAUSED")
        return " · ".join(bits)
