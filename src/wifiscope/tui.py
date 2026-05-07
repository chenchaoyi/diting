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
from .ble import BLEDevice, BLEPoller, BLEScanUpdate, service_category
from .i18n import fit_cells, pad_cells, t
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
        self.border_title = t("Connection")
        self._paint(None)

    def update_connection(self, conn: Connection | None, inv: NetworkInventory) -> None:
        self._paint(conn, inv)

    def _paint(self, conn: Connection | None, inv: NetworkInventory | None = None) -> None:
        if conn is None:
            self.update(Text(t("not associated"), style="dim italic"))
            return
        assert inv is not None
        ap_name = inv.resolve(conn.bssid) or t("(unknown)")
        band = band_label(conn.channel)
        header = Text()
        header.append(ap_name, style="bold cyan")
        if band:
            header.append(f"  {band}", style="cyan")
        if conn.country_code:
            header.append(t("  · country {cc}", cc=conn.country_code), style="dim")

        signal_bar = _signal_bar(conn.rssi_dbm)

        # Group of rows. Empty-valued rows (e.g. no IP yet) are omitted
        # rather than printing 'n/a' lines that take vertical space and
        # tell the user nothing.
        rows: list[tuple[str, str]] = [
            (t("SSID"), _fmt(conn.ssid)),
            (t("BSSID"), _fmt(conn.bssid)),
            (
                t("Channel"),
                f"{_fmt(conn.channel)}  {_fmt(conn.channel_width_mhz, ' MHz')}  "
                f"{_fmt(conn.channel_band)}",
            ),
            (t("PHY / Sec"), f"{_fmt(conn.phy_mode)}   {_fmt(conn.security)}"),
            (
                t("Tx / Max"),
                t("{tx}  /  {max} max",
                  tx=_fmt(conn.tx_rate_mbps, " Mbps"),
                  max=_fmt(conn.max_link_speed_mbps, " Mbps")),
            ),
            (
                t("MCS / NSS"),
                t("{mcs}  ·  {nss}",
                  mcs=_fmt(conn.mcs_index),
                  nss=_fmt(conn.nss, t(" streams"))),
            ),
            (t("Noise"), _fmt(conn.noise_dbm, " dBm")),
        ]
        if conn.ip_address or conn.router_ip:
            rows.append((
                t("IP / Router"),
                f"{_fmt(conn.ip_address)}  →  {_fmt(conn.router_ip)}",
            ))
        if conn.interface_mac:
            rows.append((t("This Mac"), conn.interface_mac))

        body = Text()
        for label, value in rows:
            body.append("  " + pad_cells(label, 11), style="dim")
            body.append(f"{value}\n")
        signal_line = Text()
        signal_line.append("  " + pad_cells(t("Signal"), 11), style="dim")
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
                t("  * Tx and Max use different CoreWLAN APIs and may diverge."),
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
        yield Static(Text(t("(scanning...)"), style="dim italic"), id="scan-body")

    def on_mount(self) -> None:
        self.border_title = t("Nearby BSSIDs")

    def update_scan(
        self,
        results: list[ScanResult],
        current: Connection | None,
        current_bssid: str | None,
        scanned_at: float | None,
        inv: NetworkInventory,
        sort_mode: str = "signal",
    ) -> None:
        ago = "" if scanned_at is None else t(
            "  · scanned {n}s ago", n=int(time.monotonic() - scanned_at)
        )
        all_redacted = bool(results) and all(
            r.bssid is None and r.ssid is None for r in results
        )
        identity = t("  · identity TCC-redacted") if all_redacted else ""
        sort_label = t("  · sort: {mode}", mode=t(sort_mode))
        self.border_title = (
            t("Nearby BSSIDs") + f" ({len(results)}){ago}{identity}{sort_label}"
        )
        if not results:
            self.query_one("#scan-body", Static).update(
                Text(t("(no APs from last scan — likely throttle, retrying)"),
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
        self.border_title = t("Diagnostics")
        self.update(Text(t("(waiting for scan data...)"), style="dim italic"))

    def update_environment(
        self,
        results: list[ScanResult],
        current: Connection | None,
    ) -> None:
        self.border_title = t("Diagnostics")
        if not results:
            self.update(Text(t("(waiting for scan data...)"), style="dim italic"))
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
        Binding("escape,h,q", "app.pop_screen", t("Close")),
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

    Each section header and paragraph is fed through ``t()`` so the
    Chinese reader sees a complete translation rather than a mix of
    English structure and Chinese inserts. Single-character bindings
    (``q`` / ``p`` / ``r`` …) stay literal — translating them would
    detach the description from the actual key the user has to press.
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
        t("  ·  terminal WiFi monitor for macOS, focused on roaming visibility.\n"),
        style="dim",
    )

    section(t("What"))
    body.append(t(
        "  See which AP you are on, when your Mac switches, and how strong\n"
        "  the signal is — the things macOS hides from its own WiFi panel.\n"
    ))

    section(t("Panels"))
    line("Conn.", t("current AP, signal bar, link / IP / radio details"))
    line("Scan",  t("every BSSID in range, grouped by physical AP"))
    line("Roam",  t("band-switch and inter-AP roam events as they happen"))

    section(t("Bindings"))
    line("q", t("quit"))
    line("p", t("pause / resume polling"))
    line("r", t("force a rescan now (CoreWLAN ~5s throttle still applies)"))
    line("s", t("cycle scan sort:  by AP  ↔  by signal"))
    line("c", t("force re-roam (cycle WiFi off/on so the OS re-picks the"))
    body.append(" " * 8 + t("strongest BSSID — fixes sticky associations)\n"))
    line("n", t("toggle Nearby view: Wi-Fi BSSIDs ↔ BLE devices"))
    line("h", t("toggle this help"))
    line("b", t("open Wi-Fi basics for SSID, BSSID, channel, band, security"))

    section(t("AP aliases (optional)"))
    body.append(t(
        "  Drop ./aps.yaml (next to aps.example.yaml in the cloned repo)\n"
        "  listing your APs by management MAC; wifiscope renders friendly\n"
        "  names ('1F-bedroom') in place of MAC fragments ('?af:5e:a7').\n"
        "  Without the file the tool still works — every BSSID gets an\n"
        "  auto-cluster label like '?AB:CD:EF' so radios of the same\n"
        "  physical AP still group together.\n"
    ))

    section(t("Helper"))
    body.append(t(
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
    ))

    section(t("Tunables"))
    body.append(t(
        "  WIFISCOPE_SCAN_INTERVAL=N    seconds between scans, default 7.\n"
        "                                CoreWLAN throttles around 5 s,\n"
        "                                so values below ~6 yield empty\n"
        "                                scans every other call. Min 3.\n"
        "  WIFISCOPE_INVENTORY=path     override aps.yaml location.\n"
        "  WIFISCOPE_HELPER=path        override helper.app path.\n"
        "  WIFISCOPE_LANG=en|zh         override interface language.\n"
    ))

    body.append("\n")
    body.append("─" * 70 + "\n", style="dim")
    body.append(t("made by "), style="dim")
    body.append("ccy", style="bold dim")
    body.append("  ·  ", style="dim")
    body.append(
        "github.com/chenchaoyi/wifiscope",
        style="dim underline link https://github.com/chenchaoyi/wifiscope",
    )
    body.append("\n")
    body.append(t("Esc or h to close"), style="dim italic")
    return body


class BasicsScreen(ModalScreen):
    """Short glossary for users who are not Wi-Fi specialists."""

    BINDINGS = [
        Binding("escape,b,q", "app.pop_screen", t("Close")),
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

    body.append(t("Wi-Fi Basics"), style="bold cyan")
    body.append(t("  ·  the words wifiscope uses in the dashboard\n"), style="dim")

    # Term names that are themselves industry acronyms (SSID, BSSID,
    # RSSI) keep their English form in the heading; the explanation
    # paragraph is what changes between languages.
    term(
        "SSID",
        t(
            "The Wi-Fi name people choose from, such as Meituan or Guest. "
            "Many access points can broadcast the same SSID."
        ),
    )
    term(
        "BSSID",
        t(
            "The radio identity behind one SSID on one AP/radio. A single "
            "physical AP may expose many BSSIDs when it broadcasts several "
            "SSIDs on 2.4 GHz and 5 GHz."
        ),
    )
    term(
        t("AP host"),
        t(
            "wifiscope's best guess for the physical access point that owns "
            "a BSSID. Names you set in ./aps.yaml (optional, next to "
            "aps.example.yaml in the repo) are most accurate; ? labels are "
            "auto-inferred from MAC address patterns when no aps.yaml entry "
            "matches."
        ),
    )
    term(
        t("RSSI / Signal"),
        t(
            "Received signal strength. Less negative is stronger: -45 dBm is "
            "excellent, -65 dBm is usable, and around -75 dBm is weak."
        ),
    )
    term(
        t("Noise / SNR"),
        t(
            "Noise is background radio energy. SNR is signal minus noise; "
            "higher is better. Low SNR can cause retries even when the AP is visible."
        ),
    )
    term(
        t("Band"),
        t(
            "The radio range: 2.4 GHz reaches farther but is crowded; 5 GHz is "
            "faster with shorter range; 6 GHz is newer, cleaner, and shorter range."
        ),
    )
    term(
        t("Channel"),
        t(
            "The slice of a band the AP is using. APs on the same or nearby "
            "channels share airtime, so a quieter channel can help."
        ),
    )
    term(
        t("Width"),
        t(
            "How much spectrum the AP uses, such as 20/40/80 MHz. Wider can be "
            "faster but also easier to interfere with, especially on 2.4 GHz."
        ),
    )
    term(
        t("Security"),
        t(
            "OPEN means no Wi-Fi-layer password/encryption. ENT means enterprise "
            "authentication. WPA2/WPA3 are password or modern secured modes."
        ),
    )
    term(
        t("Roam"),
        t(
            "When the Mac moves from one BSSID to another. Same SSID does not "
            "guarantee the Mac picked the strongest or best AP."
        ),
    )
    term(
        t("Roam score"),
        t(
            "A simple 0-100 guide, not a standard. It rewards strong RSSI, good "
            "SNR, cleaner bands, and quieter channels, and penalizes weak signal, "
            "busy channels, open networks, and security mismatches. A better "
            "candidate is shown only when the same SSID scores clearly higher."
        ),
    )

    body.append("\n")
    body.append(t("Esc or b to close"), style="dim italic")
    return body


class BLEPanel(VerticalScroll):
    """Nearby BLE devices, swapped into the third panel slot when the
    user toggles to the BLE view via the `n` binding.

    Sort order is RSSI desc by default. The rolling map of devices is
    owned by :class:`wifiscope.ble.BLEPoller`; this widget renders
    whatever the latest snapshot contained, including merge-folded
    rows (which carry a ``(merged N)`` badge so the user can see the
    fuzzy-merge happening rather than wondering where rotated UUIDs
    went).
    """

    DEFAULT_CSS = """
    BLEPanel {
        height: 1fr;
        border: heavy $accent;
        padding: 0 1;
    }
    BLEPanel > #ble-body {
        height: auto;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static(
            Text(t("(no BLE devices yet — scanning...)"), style="dim italic"),
            id="ble-body",
        )

    def on_mount(self) -> None:
        self.border_title = t("Nearby BLE devices")

    def update_devices(
        self,
        devices: list[BLEDevice],
        permission_state: str,
    ) -> None:
        # Only show a "(N)" device-count suffix when scanning is actually
        # working. In every other state the count would be 0 and the
        # body explains why — putting (0) in the title alongside a
        # "permission required" / "Bluetooth off" message reads as a
        # contradiction (did the scan run and find nothing? did it
        # never start?). The Swift helper distinguishes 'denied' /
        # 'unavailable' / 'error' / 'unknown' on purpose; surface each
        # with its own actionable placeholder rather than collapsing
        # everything except 'denied' into "scanning...".
        base_title = t("Nearby BLE devices")
        body = self.query_one("#ble-body", Static)

        if permission_state == "granted":
            self.border_title = base_title + f" ({len(devices)})"
            if not devices:
                body.update(Text(t("(no BLE devices yet — scanning...)"),
                                 style="dim italic"))
                return
            lines: list[Text] = [_ble_header_line()]
            now = datetime.now(devices[0].last_seen.tzinfo)
            for d in devices:
                lines.append(_ble_row_line(d, now))
            body.update(Group(*lines))
            return

        # Non-granted: drop the count, show a state-specific message.
        self.border_title = base_title
        if permission_state == "denied":
            body.update(Text(t("(BLE permission required)"),
                             style="dim italic"))
        elif permission_state == "unavailable":
            body.update(Text(
                t("(BLE helper unavailable — run `make helper` then re-open it)"),
                style="dim italic",
            ))
        elif permission_state == "incompatible":
            body.update(Text(
                t("(installed helper is too old; rebuild with `make helper`)"),
                style="dim italic",
            ))
        elif permission_state == "error":
            body.update(Text(
                t("(BLE error — Bluetooth may be off in Control Center)"),
                style="dim italic",
            ))
        else:  # 'unknown' or any future state
            body.update(Text(t("(BLE state unknown — waiting for helper)"),
                             style="dim italic"))


class RoamLogPanel(RichLog):
    DEFAULT_CSS = """
    RoamLogPanel {
        height: 8;
        border: heavy $accent;
        padding: 0 1;
    }
    """

    def on_mount(self) -> None:
        self.border_title = t("Roam log")
        self.write(Text(t("(no roam events yet)"), style="dim italic"))

    def append_roam(self, event: RoamEvent, inv: NetworkInventory) -> None:
        ts = event.timestamp.strftime("%H:%M:%S")
        prev = format_bssid(event.previous_bssid, event.previous_channel, inv)
        new = format_bssid(event.new_bssid, event.new_channel, inv)
        if inv.is_same_ap(event.previous_bssid, event.new_bssid):
            ap = inv.resolve(event.new_bssid) or t("same AP")
            prev_band = band_label(event.previous_channel) or "?"
            new_band = band_label(event.new_channel) or "?"
            tag = t(
                "[band switch on {ap}: {prev_band} -> {new_band}]",
                ap=ap, prev_band=prev_band, new_band=new_band,
            )
            style = "yellow"
        else:
            tag = t("[inter-AP roam]")
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
    # English distinguishes singular / plural; the Chinese catalog
    # collapses both onto the same translation, so the call site does
    # not branch on language.
    bssid_word = t("BSSID") if n == 1 else t("BSSIDs")
    rssi_part = (
        f"{best} dBm" if best == worst or best is None or worst is None
        else f"{best}..{worst} dBm"
    )
    ssid_part = (
        t("  ·  {n} SSID", n=len(ssids)) if len(ssids) == 1
        else t("  ·  {n} SSIDs", n=len(ssids)) if ssids
        else ""
    )
    line = Text()
    line.append("  ── ", style="dim")
    # cluster labels start with '?'; inventory names never do.
    name_style = "bold dim" if group.key.startswith("?") else "bold cyan"
    line.append(group.key, style=name_style)
    line.append(t("  ·  {n} {bssid_word}  ·  {rssi_part}",
                  n=n, bssid_word=bssid_word, rssi_part=rssi_part) + ssid_part,
                style="dim")
    if group.is_current:
        line.append(t("  · current"), style="bold cyan")
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
    line.append(t("Visible BSSIDs  "), style="bold dim")
    line.append(
        t(
            "{n} total  2.4 GHz: {n2}  5 GHz: {n5}  6 GHz: {n6}",
            n=len(results), n2=counts["2.4G"], n5=counts["5G"], n6=counts["6G"],
        ),
        style="white",
    )
    if hidden:
        line.append(t("  hidden in this scan: {n}", n=hidden), style="dim")
    if redacted:
        line.append(t("  redacted: {n}", n=redacted), style="dim italic")
    if countries:
        style = "yellow" if len(countries) > 1 else "dim"
        line.append(t("  country codes: {codes}", codes="/".join(countries)),
                    style=style)
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
        warnings.append((t("{n} open/no-password BSSIDs", n=open_count), "yellow"))
    if ht40_2g:
        warnings.append((t("{n} wide 2.4 GHz BSSIDs", n=ht40_2g), "yellow"))
    if current_load is not None:
        style = "yellow" if current_load >= 5 else "dim"
        warnings.append(
            (t("{n} other BSSIDs on your channel", n=current_load), style)
        )
    if len(_country_codes(results)) > 1:
        warnings.append((t("mixed country codes nearby"), "yellow"))

    line = Text()
    line.append(t("Things to notice  "), style="bold dim")
    if not warnings:
        line.append(t("No obvious environment warnings from the scan."),
                    style="green")
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
    line.append(t("Least crowded channels  "), style="bold dim")
    line.append(t("Estimated from the scan."), style="dim")
    if rec_2g is not None:
        line.append(_channel_hint("2.4 GHz", rec_2g, results))
    if rec_5g is not None:
        line.append(_channel_hint("5 GHz", rec_5g, results))
    return line


def _channel_hint(label: str, channel: int, results: list[ScanResult]) -> Text:
    text = Text()
    text.append(t("  {band}: ch{n}", band=label, n=channel), style="cyan")
    if not any(r.channel == channel for r in results):
        text.append(t(" (no AP heard)"), style="dim")
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
    line.append(t("Current link  "), style="bold dim")
    if current is None:
        line.append(t("not associated"), style="dim italic")
        return line

    issues: list[tuple[str, str]] = []
    if current.rssi_dbm is not None:
        if current.rssi_dbm <= -75:
            issues.append((t("weak signal {dbm} dBm", dbm=current.rssi_dbm), "red"))
        elif current.rssi_dbm <= -67:
            issues.append((t("fair signal {dbm} dBm", dbm=current.rssi_dbm), "yellow"))
    if current.rssi_dbm is not None and current.noise_dbm is not None:
        snr = current.rssi_dbm - current.noise_dbm
        if snr < 25:
            issues.append((t("SNR {db} dB", db=snr), "yellow"))

    better = _best_same_ssid_candidate(results, current)
    if better is not None:
        candidate, delta = better
        label = _fmt(candidate.bssid)
        if candidate.channel is not None:
            label += f" ch{candidate.channel}"
        issues.append((
            t("stronger same-name AP nearby: +{delta} dB ({label})",
              delta=delta, label=label),
            "bold cyan",
        ))

    if not issues:
        line.append(t("Looks OK"), style="green")
        return line
    for i, (msg, style) in enumerate(issues):
        if i:
            line.append("  ")
        line.append(msg, style=style)
    if better is not None:
        line.append(t("  press c to re-roam"), style="dim")
    return line


def _score_line(results: list[ScanResult], current: Connection | None) -> Text:
    line = Text()
    line.append(t("Roam score  "), style="bold dim")
    if current is None:
        line.append(t("not associated"), style="dim italic")
        return line
    current_score = _link_score(current, results, baseline=current)
    candidate = _best_roam_candidate(results, current)
    line.append(t("current {n}/100", n=current_score.score),
                style=_score_style(current_score.score))
    if current_score.reasons:
        # Each reason is its own catalog key so the Chinese version is
        # natural ("信号强") rather than a literal translation of every
        # space-separated word.
        translated = [t(r) for r in current_score.reasons[:2]]
        line.append(f" ({', '.join(translated)})", style="dim")
    if candidate is None:
        line.append(t("  ·  no clearly better same-SSID BSSID"), style="dim")
        return line
    row, score = candidate
    delta = score.score - current_score.score
    line.append(
        t("  ·  better candidate {n}/100", n=score.score),
        style=_score_style(score.score),
    )
    line.append(f" (+{delta})", style="cyan")
    if row.channel is not None:
        line.append(f" ch{row.channel}", style="dim")
    if row.bssid:
        line.append(f" {row.bssid}", style="dim")
    if score.reasons:
        translated = [t(r) for r in score.reasons[:2]]
        line.append(f" ({', '.join(translated)})", style="dim")
    line.append(t("  press c to re-roam"), style="dim")
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
    # All left-aligned columns route through pad_cells so CJK headers
    # (e.g. "信号", "频段") consume their two cells per glyph instead of
    # str.ljust's one-byte-per-char accounting. The RSSI column is the
    # only right-aligned one and keeps str.format alignment because its
    # header "RSSI" is ASCII in both languages.
    h = Text(style="bold dim")
    h.append(
        f" {'★':<2}{t('RSSI'):>{_COL_RSSI}}  "
        f"{pad_cells(t('signal'), _COL_SIGNAL)}  "
        f"{pad_cells(t('channel'), _COL_CH)}  "
        f"{pad_cells(t('band'), _COL_BAND)}  "
        f"{pad_cells(t('AP host'), _COL_AP)}  "
        f"{pad_cells(t('SSID'), _COL_SSID)}  "
        f"{pad_cells(t('security'), _COL_SEC)}  "
        f"{pad_cells(t('BSSID'), _COL_BSSID)}  "
        f"{pad_cells(t('width'), _COL_WIDTH)}"
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
        ap_text, ap_style = t("(redacted)"), "dim italic"
        ssid_text, ssid_style = t("(redacted)"), "dim italic"
        bssid_text, bssid_style = t("(redacted)"), "dim italic"
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
        ssid_text = r.ssid or t("(hidden)")
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
    # ASCII-only fields keep str.format alignment for speed; ap_text
    # and ssid_text can hold CJK (user-defined inventory names, real
    # network SSIDs in foreign locales) so they go through fit_cells
    # which counts terminal cells and never chops a wide glyph.
    line.append(f"{r.channel if r.channel is not None else '?':<{_COL_CH}}  ", style="white")
    line.append(f"{band_short:<{_COL_BAND}}  ", style="white")
    line.append(fit_cells(ap_text, _COL_AP) + "  ", style=ap_style)
    line.append(fit_cells(ssid_text, _COL_SSID) + "  ", style=ssid_style)
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


# ---------- BLE table rendering ----------

_COL_BLE_RSSI = 4
_COL_BLE_SIGNAL = 8
_COL_BLE_VENDOR = 18
_COL_BLE_NAME = 22
_COL_BLE_SERVICES = 16
_COL_BLE_AGO = 8
_COL_BLE_ID = 10


def _ble_header_line() -> Text:
    h = Text(style="bold dim")
    h.append(
        f" {'★':<2}{t('RSSI'):>{_COL_BLE_RSSI}}  "
        f"{pad_cells(t('signal'), _COL_BLE_SIGNAL)}  "
        f"{pad_cells(t('vendor'), _COL_BLE_VENDOR)}  "
        f"{pad_cells(t('name'), _COL_BLE_NAME)}  "
        f"{pad_cells(t('services'), _COL_BLE_SERVICES)}  "
        f"{pad_cells(t('last seen'), _COL_BLE_AGO)}  "
        f"{pad_cells(t('id'), _COL_BLE_ID)}"
    )
    return h


def _ble_row_line(d: BLEDevice, now: datetime) -> Text:
    rssi_color = _rssi_color(d.rssi_dbm) if d.rssi_dbm is not None else "dim"
    rssi_text = f"{d.rssi_dbm:>{_COL_BLE_RSSI}}" if d.rssi_dbm is not None else f"{'?':>{_COL_BLE_RSSI}}"
    vendor_text = d.vendor or t("(unknown)")
    name_text = d.name or t("(unknown)")
    name_style = "white" if d.name else "dim italic"
    services_text = _ble_services_summary(d.services)
    age_text = _ble_age_text(d, now)
    id_short = d.identifier[:8]

    line = Text()
    # Selection star reserved for future use; no devices are "current"
    # in the BLE view because BLE doesn't expose an association concept.
    line.append(f" {' ':<2}")
    line.append(f"{rssi_text}  ", style=rssi_color)
    line.append(_signal_bar(d.rssi_dbm, length=_COL_BLE_SIGNAL))
    line.append("  ")
    line.append(fit_cells(vendor_text, _COL_BLE_VENDOR) + "  ",
                style="cyan" if d.vendor else "dim")
    line.append(fit_cells(name_text, _COL_BLE_NAME) + "  ", style=name_style)
    line.append(fit_cells(services_text, _COL_BLE_SERVICES) + "  ", style="dim")
    # Use fit_cells (not raw f-string ljust) because t("now") resolves
    # to "刚刚" in zh — 2 code points but 4 terminal cells. str.ljust
    # would pad to 6 spaces (= 8 code points / 10 cells), shoving the
    # id column 2 cells right of where the header expects.
    line.append(fit_cells(age_text, _COL_BLE_AGO) + "  ", style="dim")
    line.append(f"{id_short:<{_COL_BLE_ID}}", style="dim")
    if d.merged_count > 1:
        line.append("  ")
        line.append(t("(merged {n})", n=d.merged_count), style="cyan")
    return line


def _ble_services_summary(services: tuple[str, ...]) -> str:
    if not services:
        return ""
    cats: list[str] = []
    seen: set[str] = set()
    for s in services:
        cat = service_category(s)
        # Translate categories that have catalog entries; raw UUIDs
        # pass through unchanged.
        translated = t(cat)
        if translated in seen:
            continue
        seen.add(translated)
        cats.append(translated)
    return ", ".join(cats[:3])


def _ble_age_text(d: BLEDevice, now: datetime) -> str:
    delta = (now - d.last_seen).total_seconds()
    if delta < 1:
        return t("now")
    return t("{n}s", n=int(delta))


# ---------- app ----------

class GroupedFooter(Static):
    """Custom footer that splits the main app's eight bindings into three
    semantic groups separated by ``│`` dividers. Replaces Textual's
    default flat ``Footer`` at the App level so the user can find the
    right key faster — "is this an app control, a scan action, or an
    info modal?" — without scanning a long undifferentiated row.

    Group layout, left to right:

    1. **App control**: ``q`` quit · ``p`` pause
    2. **Scan / view**: ``r`` rescan · ``s`` sort · ``n`` view-toggle ·
       ``c`` re-roam
    3. **Info**: ``h`` help · ``b`` basics

    The ``n`` binding's description is **dynamic** — it shows the OTHER
    view as the literal target ("→ BLE" while in Wi-Fi view, "→ Wi-Fi"
    while in BLE view). This is more discoverable than a static word
    like "View" / "视图" which gives the user no idea what pressing it
    will switch to.

    Modal screens (Help, Basics) keep their own inline close hint and
    are not affected by this widget.
    """

    DEFAULT_CSS = """
    GroupedFooter {
        dock: bottom;
        height: 1;
        background: $primary;
        color: $text;
        padding: 0 1;
    }
    """

    def on_mount(self) -> None:
        self.refresh_layout()

    def refresh_layout(self) -> None:
        view_mode = getattr(self.app, "_view_mode", "wifi")
        next_view = "BLE" if view_mode == "wifi" else "Wi-Fi"

        groups: list[list[tuple[str, str]]] = [
            [("q", t("Quit")), ("p", t("Pause"))],
            [
                ("r", t("Rescan")),
                ("s", t("Sort")),
                ("n", t("→ {view}", view=next_view)),
                ("c", t("Re-roam")),
            ],
            [("h", t("Help")), ("b", t("Basics"))],
        ]

        out = Text()
        for group_idx, group in enumerate(groups):
            if group_idx > 0:
                out.append("  │  ", style="dim")
            for binding_idx, (key, desc) in enumerate(group):
                if binding_idx > 0:
                    out.append("  ")
                out.append(f" {key} ", style="reverse bold")
                out.append(f" {desc}")
        self.update(out)


class WifiScopeApp(App):
    CSS = """
    Screen { layout: vertical; }
    """
    # Binding descriptions go through ``t()`` at class-define time so
    # the command palette (Ctrl+P) and any other Textual-driven UI sees
    # localised strings. The visible footer is rendered separately by
    # GroupedFooter, which overrides the layout entirely. cli.main()
    # calls i18n.set_lang() before lazy-importing tui, so by the time
    # this BINDINGS list is built the catalog is final.
    BINDINGS = [
        Binding("q", "quit", t("Quit")),
        Binding("p", "toggle_pause", t("Pause")),
        Binding("r", "rescan", t("Rescan")),
        Binding("s", "cycle_sort", t("Sort")),
        Binding("n", "toggle_view", t("Toggle Wi-Fi / BLE view")),
        Binding("c", "reroam", t("Re-roam")),
        Binding("h", "show_help", t("Help")),
        Binding("b", "show_basics", t("Basics")),
    ]

    def __init__(
        self,
        backend: WiFiBackend,
        inv: NetworkInventory,
        *,
        scan_interval: float = 7.0,
        ble_helper_path: str | None = None,
    ) -> None:
        super().__init__()
        self._backend = backend
        self._inv = inv
        self._poller = WiFiPoller(backend, scan_interval=scan_interval)
        # The BLE poller spawns wifiscope-helper ble-scan as a long-
        # running subprocess. If no helper path is supplied, the poller
        # surfaces a permission_state of "unavailable" and yields
        # empty snapshots — the BLE panel then renders a placeholder
        # rather than crashing the TUI.
        helper_path = ble_helper_path
        if helper_path is None:
            helper_path = getattr(backend, "_helper_path", None) or ""
        self._ble_poller: BLEPoller | None = None
        self._ble_helper_path = helper_path
        # Latest BLE snapshot — kept fresh in the background regardless
        # of which view is active so toggling is instant.
        self._latest_ble: list[BLEDevice] = []
        self._ble_permission_state: str = "unknown"
        # 'wifi' (default) or 'ble' — toggled by `n`. Both panels are
        # mounted; we flip widget.display rather than mount/unmount so
        # the widget tree stays stable for tests and the swap is
        # instantaneous on key press.
        self._view_mode: str = "wifi"
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
        yield BLEPanel(id="ble")
        yield RoamLogPanel(id="roam")
        yield GroupedFooter(id="footer")

    async def on_mount(self) -> None:
        # The BLE panel sits in the same vertical slot as the Wi-Fi
        # scan panel; only one is visible at a time. Hide it on mount
        # so the default 'wifi' view shows the scan panel.
        self.query_one("#ble", BLEPanel).display = False
        self.run_worker(self._consume_events(), exclusive=True, name="poller")
        if self._ble_helper_path:
            self._ble_poller = BLEPoller(self._ble_helper_path)
            self.run_worker(
                self._consume_ble_events(), exclusive=False, name="ble-poller",
            )

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

    async def _consume_ble_events(self) -> None:
        """Drain BLE snapshots from the poller into the BLE panel.

        Runs in parallel with the Wi-Fi consumer so toggling between
        views is instantaneous — both data streams update internal
        state regardless of which view is currently visible.
        """
        if self._ble_poller is None:
            return
        try:
            async for event in self._ble_poller.events():
                if self._paused:
                    continue
                if isinstance(event, BLEScanUpdate):
                    self._latest_ble = event.devices
                    self._ble_permission_state = event.permission_state
                    self._refresh_ble_panel()
        except Exception:
            # Don't let a poller hiccup tear down the whole TUI.
            pass

    def _refresh_ble_panel(self) -> None:
        try:
            panel = self.query_one("#ble", BLEPanel)
        except Exception:
            return
        panel.update_devices(self._latest_ble, self._ble_permission_state)

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

    def action_toggle_view(self) -> None:
        """Swap the third panel slot between Wi-Fi scan and BLE list.

        Both pollers keep running in the background; only the visible
        widget changes. The BLE panel is rendered with the latest
        snapshot on swap so the user does not see a stale "scanning..."
        placeholder for a brief moment.
        """
        self._view_mode = "ble" if self._view_mode == "wifi" else "wifi"
        scan = self.query_one("#scan", ScanPanel)
        ble = self.query_one("#ble", BLEPanel)
        if self._view_mode == "ble":
            scan.display = False
            ble.display = True
            self._refresh_ble_panel()
        else:
            ble.display = False
            scan.display = True
            self._refresh_scan_panel()
        self.sub_title = self._build_subtitle()
        # Refresh the footer so n's "→ BLE" / "→ Wi-Fi" label flips to
        # match the new view. Done after sub_title so any work that
        # the toggle triggers is visible before the user's eye drops
        # to confirm where they are.
        self.query_one("#footer", GroupedFooter).refresh_layout()

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
                t("WiFi off → on — reconnecting via auto-join (2-5 s)")
            )
        else:
            self.notify(t("no WiFi interface"), severity="warning")

    def _build_subtitle(self) -> str:
        # Header subtitle is dynamic state and live diagnostics — what
        # changes as the user interacts, plus the poll cadence so the
        # user can see when the next scan is due. Static facts
        # (inventory size, backend name, helper presence) live in the
        # AttributionBar / panel titles instead.
        scan_s = int(getattr(self._poller, "_scan_interval", 0))
        bits = [
            t("view: {mode}", mode=t(self._view_mode)),
            t("sort: {mode}", mode=t(self._sort_mode)),
        ]
        if scan_s:
            bits.append(t("scan {n}s", n=scan_s))
        if self._paused:
            bits.append(t("PAUSED"))
        return " · ".join(bits)
