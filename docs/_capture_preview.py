"""Generate the README hero SVGs by running the TUI against a fake backend.

Data is synthetic — no real BSSIDs, IPs, MAC addresses, or BLE
identifiers from the maintainer's environment. Re-run any time the UI
changes:

    uv run python docs/_capture_preview.py            # English Wi-Fi → docs/preview.svg
    DITING_LANG=zh uv run python docs/_capture_preview.py
                                                      # Chinese Wi-Fi → docs/preview.zh.svg
    DITING_PREVIEW_VIEW=ble uv run python docs/_capture_preview.py
                                                      # English BLE → docs/preview-ble.svg
    DITING_LANG=zh DITING_PREVIEW_VIEW=ble uv run python docs/_capture_preview.py
                                                      # Chinese BLE → docs/preview-ble.zh.svg

The env vars DITING_LANG and DITING_PREVIEW_VIEW together select
the output filename, since the four SVGs sit side by side in docs/.

CJK NOTE
--------
Textual's ``export_screenshot`` writes ``textLength`` on every
``<text>`` element using ``len(text)`` (code-point count) rather than
``cell_len(text)``. ASCII content has 1 cell per code point so it
renders correctly, but CJK glyphs are 2 cells each and end up
visually compressed (or overlapping with neighbours) when the SVG
viewer applies ``lengthAdjust='spacing'`` to fit the under-sized
``textLength``. We post-process the export and rewrite each
``textLength`` to ``cell_len(text) * cell_width`` so CJK glyphs render
at their natural width. The next element's anchor ``x`` already
accounts for cell width in Textual's layout (verified empirically
across our preview), so simply expanding textLength does not require
shifting any downstream element.
"""
from __future__ import annotations

import asyncio
import html
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from rich.cells import cell_len

from diting import i18n
from diting.backend import WiFiBackend
from diting.ble import BLEDevice
from diting.environment import APBaseline, RFStirEvent
from diting.events import LatencySpikeEvent, LossBurstEvent
from diting.latency import LatencyAggregate
from diting.models import Connection, ScanResult
from diting.network import APEntry, NetworkInventory
from diting.poller import RoamEvent

# Language must be locked in before DitingApp imports — its
# BINDINGS list calls t() at class-definition time, so a late
# set_lang() would not retranslate the footer hints.
i18n.set_lang(i18n.resolve_lang(None, os.environ))

from diting.tui import DitingApp  # noqa: E402  (import after set_lang)


class _FakeBackend(WiFiBackend):
    name = "macOS CoreWLAN"

    def __init__(self) -> None:
        self._helper_path = "/Applications/diting-tianer.app/Contents/MacOS/diting-tianer"

    def get_connection(self) -> Connection:
        return Connection(
            ssid="Office-WiFi",
            bssid="aa:bb:cc:11:22:53",  # 1F-bedroom 5G radio — fair signal
            rssi_dbm=-68,
            noise_dbm=-95,
            tx_rate_mbps=360.0,
            channel=48,
            channel_width_mhz=80,
            channel_band="5 GHz",
            phy_mode="802.11ax",
            security="WPA2 Enterprise",
            mcs_index=7,
            nss=2,
            timestamp=datetime.now(),
            interface_mac="de:ad:be:ef:00:01",
            country_code="CN",
            ip_address="192.168.1.42",
            router_ip="192.168.1.1",
            max_link_speed_mbps=867,
        )

    def scan(self) -> list[ScanResult]:
        ts = datetime.now()
        # ssid, bssid, rssi, channel, width, security, bss_load_pct,
        # supports_802_11r — the last two are v0.7.0 schema-3 IE
        # fields. Only a few rows populate them so the preview
        # demonstrates "diagnostics knows when the AP is loaded".
        rows = [
            # 1F-bedroom — current AP, stuck here on 5 GHz at fair signal.
            # Heavy load (78%) is the spec's example for the "AP at
            # 78% utilisation" diagnostic.
            ("Office-WiFi",   "aa:bb:cc:11:22:53", -68, 48, 80, "WPA2 Enterprise", 78, True),
            ("Office-Guest",  "aa:bb:cc:11:22:54", -68, 48, 80, "Open",            None, None),
            ("Office-IoT",    "aa:bb:cc:11:22:50", -65,  6, 40, "WPA2 Personal",   None, None),
            ("Office-Guest",  "aa:bb:cc:11:22:51", -66,  6, 40, "Open",            None, None),
            # 2F-living
            ("Office-WiFi",   "aa:bb:cc:33:44:13", -60, 36, 80, "WPA2 Enterprise", 22, True),
            ("Office-Guest",  "aa:bb:cc:33:44:14", -61, 36, 80, "Open",            None, None),
            ("Office-IoT",    "aa:bb:cc:33:44:10", -68, 11, 40, "WPA2 Personal",   None, None),
            ("Office-Guest",  "aa:bb:cc:33:44:11", -68, 11, 40, "Open",            None, None),
            # 3F-attic — same SSID, much stronger; should trigger the
            # "stronger same-name AP nearby" diagnostic + roam hint.
            # Doesn't advertise 11r — the spec example for the "3 of 5
            # candidates do not advertise 802.11r" diagnostic.
            ("Office-WiFi",   "aa:bb:cc:55:66:0b", -52, 48, 80, "WPA2 Enterprise", 12, False),
            ("Office-Guest",  "aa:bb:cc:55:66:0c", -53, 48, 80, "Open",            None, None),
            ("Office-IoT",    "aa:bb:cc:55:66:08", -56,  1, 40, "WPA2 Personal",   None, None),
            # Cafe across the corridor — open guest portal on the same
            # 5 GHz channel as the user; feeds the channel-load warning.
            ("guest-cafe",    "96:de:ad:be:ef:01", -75, 48, 20, "Open",            None, None),
            # Unrelated neighbours
            ("neighbour-2g",  "f2:11:22:33:44:55", -78,  6, 20, "WPA2 Personal",   None, None),
            ("",              "f2:11:22:33:44:56", -82,  6, 20, "WPA2 Personal",   None, None),
        ]
        return [
            ScanResult(
                ssid=ssid or None,
                bssid=bssid,
                rssi_dbm=rssi,
                noise_dbm=-95,
                channel=ch,
                channel_width_mhz=width,
                channel_band="5 GHz" if ch >= 32 else "2.4 GHz",
                phy_mode=None,
                security=security,
                timestamp=ts,
                country_code="CN",
                bss_load_pct=load,
                supports_802_11r=ft,
            )
            for ssid, bssid, rssi, ch, width, security, load, ft in rows
        ]

    def permission_state(self) -> str:
        return "granted"


_INVENTORY = NetworkInventory(
    aps=(
        APEntry(name="1F-bedroom",  mgmt_mac="aa:bb:cc:11:22:4f"),
        APEntry(name="2F-living",   mgmt_mac="aa:bb:cc:33:44:0f"),
        APEntry(name="3F-attic",    mgmt_mac="aa:bb:cc:55:66:07"),
    ),
)


def _synthetic_ble_devices(now: datetime) -> list[BLEDevice]:
    """A representative-feeling mix for the BLE preview.

    Mirrors the device population the v0.6.0 spec calls out: at least
    one of each Tier-1 deep-ID category (iBeacon, AirTag, Eddystone,
    Tile, Apple Nearby Info / iPhone), one Mi Band Heart Rate sensor
    for service-category coverage, plus a privacy-rotating Apple
    beacon to demonstrate the (merged N) badge. Connected peripherals
    are returned separately by `_synthetic_ble_connected`.
    """
    def d(
        ident: str, *, name: str | None, vendor: str | None, vendor_id: int | None,
        services: tuple[str, ...], rssi: int, connectable: bool = True,
        ad_count: int = 4, age_s: int = 1, merged: int = 1,
        type: str | None = None, device_class: str | None = None,
    ) -> BLEDevice:
        last = now - timedelta(seconds=age_s)
        return BLEDevice(
            identifier=ident,
            name=name,
            vendor=vendor,
            vendor_id=vendor_id,
            services=services,
            rssi_dbm=rssi,
            is_connectable=connectable,
            first_seen=last - timedelta(seconds=ad_count * 3),
            last_seen=last,
            ad_count=ad_count,
            merged_count=merged,
            type=type,
            device_class=device_class,
        )
    return [
        # Apple iPhone in the wild — Nearby Info advertising; the deep-ID
        # nibble resolves to "iPhone" so it's no longer just "Apple, Inc.
        # (anonymous)". The exemplar of v0.6.0's question-1 answer.
        d("aaaa1234-5678-4abc-9def-000000000001",
          name=None, vendor="Apple, Inc.", vendor_id=76,
          services=(), rssi=-44, ad_count=22, age_s=1,
          device_class="iPhone"),
        # AirTag — Apple type 0x12 + FD5A. The exemplar of v0.6.0's
        # "label, not just vendor" win.
        d("bbbb1234-5678-4abc-9def-000000000002",
          name="AirTag", vendor="Apple, Inc.", vendor_id=76,
          services=("FD5A",), rssi=-46, ad_count=8, age_s=2,
          type="AirTag"),
        # Generic iBeacon (Apple type 0x02). One of the most common BLE
        # devices in any office space.
        d("cccc1234-5678-4abc-9def-000000000003",
          name=None, vendor="Apple, Inc.", vendor_id=76,
          services=(), rssi=-52, ad_count=10, age_s=1,
          type="iBeacon"),
        # Eddystone-URL beacon (Google's open format).
        d("dddd1234-5678-4abc-9def-000000000004",
          name=None, vendor=None, vendor_id=None,
          services=("FEAA",), rssi=-58, ad_count=14, age_s=2,
          type="Eddystone-URL"),
        # Privacy-rotating Apple peripheral that the fuzzy merger
        # collapsed three ways.
        d("eeee1234-5678-4abc-9def-000000000005",
          name=None, vendor="Apple, Inc.", vendor_id=76,
          services=("FE9F",), rssi=-61, ad_count=8, age_s=3, merged=3),
        # Mi Band 7 — Xiaomi Heart Rate sensor; service-category coverage.
        d("ffff1234-5678-4abc-9def-000000000006",
          name="Mi Band 7", vendor="Xiaomi, Inc.", vendor_id=637,
          services=("180D",), rssi=-67, ad_count=6, age_s=2),
        # Tile Mate.
        d("11111234-5678-4abc-9def-000000000007",
          name="Tile Mate", vendor="Tile, Inc.", vendor_id=323,
          services=("FEED",), rssi=-72, ad_count=15, age_s=4,
          type="Tile"),
        # Anonymous beacon — neither vendor nor name; the merger leaves
        # it alone per the conservative-merge policy.
        d("22221234-5678-4abc-9def-000000000008",
          name=None, vendor=None, vendor_id=None,
          services=("FFE0",), rssi=-84, ad_count=2, age_s=6,
          connectable=False),
    ]


def _synthetic_ble_connected(now: datetime) -> list[BLEDevice]:
    """Connected peripherals for the v0.6.0 'Connected' section.

    These are devices the user is actively using right now — AirPods
    they are listening to, a Magic Keyboard they are typing on. They do
    not advertise; the helper enumerates them via
    `retrieveConnectedPeripherals`. RSSI is missing by design (we never
    `readRSSI()` against an active link), so the rendered column shows
    `—`. Sort is alphabetic by name.
    """
    # Identifiers use the IOBluetooth-flavour MAC string the helper
    # actually emits. Both prefixes are real Apple OUIs (38:09:fb /
    # 8c:85:90), so the OUI lookup populates vendor automatically —
    # exactly the production code path. We do NOT pre-fill `vendor`
    # because the synthetic data is supposed to mirror what arrives on
    # the JSON wire, not what the panel ends up showing.
    return [
        BLEDevice(
            identifier="38-09-fb-0b-be-60",
            name="AirPods Pro",
            vendor="Apple, Inc.",
            vendor_id=None,
            services=("110A",),
            rssi_dbm=None,
            is_connectable=True,
            first_seen=now,
            last_seen=now,
            ad_count=0,
            is_connected=True,
        ),
        BLEDevice(
            identifier="8c-85-90-f1-d0-cd",
            name="Magic Keyboard",
            vendor="Apple, Inc.",
            vendor_id=None,
            services=("1812",),
            rssi_dbm=None,
            is_connectable=True,
            first_seen=now,
            last_seen=now,
            ad_count=0,
            is_connected=True,
        ),
    ]


def _preview_view() -> str:
    return (os.environ.get("DITING_PREVIEW_VIEW") or "wifi").lower()


async def main() -> None:
    view = _preview_view()
    # Disable the live latency / environment pollers in the wifi /
    # ble previews so the seeded synthetic state survives screenshot
    # time without a 1 Hz background loop racing it. The events
    # preview re-enables nothing; we inject pre-built ring contents
    # directly into the modal.
    app = DitingApp(
        _FakeBackend(), _INVENTORY,
        ble_helper_path="",
        enable_latency=False,
        enable_environment=False,
    )
    async with app.run_test(size=(160, 56)) as pilot:
        # let one connection update + one scan land
        await pilot.pause(2.0)
        # Seed the unified events panel with one of every event type
        # so the README hero shows the full variety.
        events_panel = pilot.app.query_one("#roam")
        events_panel.clear()
        now = datetime.now()
        events_panel.append_event(
            RoamEvent(
                timestamp=now,
                previous_bssid="aa:bb:cc:33:44:13",
                previous_channel=36,
                new_bssid="aa:bb:cc:11:22:53",
                new_channel=48,
            ),
            _INVENTORY,
        )
        events_panel.append_event(
            RFStirEvent(
                timestamp=now,
                bssid="aa:bb:cc:11:22:53",
                location="1F-bedroom",
                magnitude_db=8.3,
                duration_s=12.0,
                confidence="high",
                mode="co_located",
            ),
            _INVENTORY,
        )
        events_panel.append_event(
            LatencySpikeEvent(
                timestamp=now,
                target="router",
                target_ip="192.168.1.1",
                rtt_ms=412.0,
                loss_pct=25.0,
            ),
            _INVENTORY,
        )
        events_panel.append_event(
            LossBurstEvent(
                timestamp=now,
                target="wan",
                target_ip="1.1.1.1",
                loss_pct=80.0,
                lost_in_window=4,
            ),
            _INVENTORY,
        )
        # Seed the Diagnostics panel's Link / Environment lines with
        # well-formed aggregates and a stable σ.
        from diting.tui import EnvironmentPanel
        env_panel = pilot.app.query_one("#env", EnvironmentPanel)
        link = (
            LatencyAggregate(
                target="router", target_ip="192.168.1.1",
                rtt_ms=14.0, loss_pct=0.0, jitter_ms=2.0, sample_count=30,
            ),
            LatencyAggregate(
                target="wan", target_ip="1.1.1.1",
                rtt_ms=22.0, loss_pct=0.0, jitter_ms=3.0, sample_count=30,
            ),
            None,
        )
        env = ("stable", 1.4, None)
        env_panel.update_environment(
            pilot.app._cached_scan, pilot.app._latest_connection,
            link=link, env=env,
        )
        if view == "ble":
            # Inject synthetic BLE devices and switch the panel to BLE
            # view. We bypass the live BLE poller entirely — the goal
            # of the SVG is a deterministic, network-free render, and
            # spinning up a real subprocess from a pytest pilot is not
            # worth the flakiness.
            from diting.tui import BLEPanel
            now_utc = datetime.now(timezone.utc)
            pilot.app._latest_ble = _synthetic_ble_devices(now_utc)
            pilot.app._latest_ble_connected = _synthetic_ble_connected(now_utc)
            pilot.app._ble_permission_state = "granted"
            await pilot.press("n")
            await pilot.pause(0.3)
        if view == "events":
            # Push synthetic events into the ring and open the modal.
            from diting.environment import APBaseline
            from diting.tui import EventsScreen

            now = datetime.now()
            ring_events = [
                RoamEvent(
                    timestamp=now, previous_bssid="aa:bb:cc:33:44:13",
                    previous_channel=36, new_bssid="aa:bb:cc:11:22:53",
                    new_channel=48,
                ),
                RFStirEvent(
                    timestamp=now, bssid="aa:bb:cc:11:22:53",
                    location="1F-bedroom", magnitude_db=8.3,
                    duration_s=12.0, confidence="high", mode="co_located",
                ),
                LatencySpikeEvent(
                    timestamp=now, target="router",
                    target_ip="192.168.1.1", rtt_ms=412.0, loss_pct=25.0,
                ),
                LossBurstEvent(
                    timestamp=now, target="wan",
                    target_ip="1.1.1.1", loss_pct=80.0, lost_in_window=4,
                ),
            ]
            baselines = [
                APBaseline(
                    bssid="aa:bb:cc:11:22:53", location="1F-bedroom",
                    mode="co_located", samples=240,
                    baseline_sigma=1.4, current_sigma=8.3, last_rssi=-52,
                ),
                APBaseline(
                    bssid="aa:bb:cc:33:44:13", location="2F-living",
                    mode="co_located", samples=180,
                    baseline_sigma=1.1, current_sigma=1.5, last_rssi=-60,
                ),
                APBaseline(
                    bssid="aa:bb:cc:55:66:0b", location="3F-attic",
                    mode="spatial_channel", samples=90,
                    baseline_sigma=2.2, current_sigma=2.0, last_rssi=-78,
                ),
            ]
            sigma_history = [
                (now - timedelta(minutes=60 - i * 2), max(1.0, abs(i - 30) / 4.0))
                for i in range(30)
            ]
            sigma_history.append((now, 8.3))
            screen = EventsScreen(
                ring_snapshot=list(reversed(ring_events)),
                baselines=baselines,
                sigma_history=sigma_history,
            )
            pilot.app.push_screen(screen)
            await pilot.pause(0.4)
        await pilot.pause(0.3)
        out = pilot.app.export_screenshot(title="diting")
    out = _fix_cjk_textlength(out)
    out = _replace_title_font(out)
    base_map = {"ble": "preview-ble", "events": "preview-events", "wifi": "preview"}
    base = base_map.get(view, "preview")
    suffix = ".zh.svg" if i18n.get_lang() == i18n.ZH else ".svg"
    target = Path(__file__).parent / f"{base}{suffix}"
    target.write_text(out)
    print(f"wrote {target} ({len(out):,} bytes)")


# Pattern matches Textual's <text ... textLength="N" ...>BODY</text>
# format. The capture group order is documented in the regex; rewrite
# extracts the body, recomputes the cell-aware width, and edits the
# attribute in place. We do not touch ``x`` or downstream elements
# because Textual lays the next-anchor x out cell-aware already — see
# the module docstring for the verification.
_TEXT_RX = re.compile(
    r'(<text[^>]*\btextLength=")([0-9.]+)("[^>]*>)([^<]*)(</text>)'
)


def _fix_cjk_textlength(svg: str, cell_width_px: float = 12.2) -> str:
    """Rewrite each ``<text>`` element's ``textLength`` to match
    ``cell_len(body)`` × ``cell_width_px``. ASCII rows are unchanged
    (1 cell per code point); CJK rows expand so glyphs render natural-
    width without lengthAdjust compression.
    """
    def _rewrite(match: re.Match) -> str:
        prefix, _old_len, mid, body, suffix = match.groups()
        # html.unescape because Textual emits &#160; (NBSP), which
        # cell_len would otherwise count as zero-width if we left it
        # as the escape sequence.
        decoded = html.unescape(body)
        new_len = cell_len(decoded) * cell_width_px
        return f'{prefix}{new_len:g}{mid}{body}{suffix}'

    return _TEXT_RX.sub(_rewrite, svg)


# Textual's screenshot pipeline writes the small title-bar text
# ("diting") into a `.terminal-XXX-title` CSS class with
# `font-family: arial;` baked in. The design system at
# `design/diting-design/` mandates Fira Code / JetBrains Mono on
# any mono surface, including the snapshot title bar. Rewrite the
# baked CSS so the rendered title matches the rest of the chrome.
def _replace_title_font(svg: str) -> str:
    return svg.replace(
        "font-family: arial;",
        "font-family: 'JetBrains Mono','Fira Code','SF Mono',Menlo,monospace;",
    )


if __name__ == "__main__":
    asyncio.run(main())
