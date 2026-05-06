"""Generate the README hero SVGs by running the TUI against a fake backend.

Data is synthetic — no real BSSIDs, IPs, MAC addresses, or BLE
identifiers from the maintainer's environment. Re-run any time the UI
changes:

    uv run python docs/_capture_preview.py            # English Wi-Fi → docs/preview.svg
    WIFISCOPE_LANG=zh uv run python docs/_capture_preview.py
                                                      # Chinese Wi-Fi → docs/preview.zh.svg
    WIFISCOPE_PREVIEW_VIEW=ble uv run python docs/_capture_preview.py
                                                      # English BLE → docs/preview-ble.svg
    WIFISCOPE_LANG=zh WIFISCOPE_PREVIEW_VIEW=ble uv run python docs/_capture_preview.py
                                                      # Chinese BLE → docs/preview-ble.zh.svg

The env vars WIFISCOPE_LANG and WIFISCOPE_PREVIEW_VIEW together select
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

from wifiscope import i18n
from wifiscope.backend import WiFiBackend
from wifiscope.ble import BLEDevice
from wifiscope.models import Connection, ScanResult
from wifiscope.network import APEntry, NetworkInventory
from wifiscope.poller import RoamEvent

# Language must be locked in before WifiScopeApp imports — its
# BINDINGS list calls t() at class-definition time, so a late
# set_lang() would not retranslate the footer hints.
i18n.set_lang(i18n.resolve_lang(None, os.environ))

from wifiscope.tui import WifiScopeApp  # noqa: E402  (import after set_lang)


class _FakeBackend(WiFiBackend):
    name = "macOS CoreWLAN"

    def __init__(self) -> None:
        self._helper_path = "/Applications/wifiscope-helper.app/Contents/MacOS/wifiscope-helper"

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
        rows: list[tuple[str, str, int, int, int, str]] = [
            # ssid, bssid, rssi, channel, width, security
            # 1F-bedroom — current AP, stuck here on 5 GHz at fair signal
            ("Office-WiFi",   "aa:bb:cc:11:22:53", -68, 48, 80, "WPA2 Enterprise"),
            ("Office-Guest",  "aa:bb:cc:11:22:54", -68, 48, 80, "Open"),
            ("Office-IoT",    "aa:bb:cc:11:22:50", -65,  6, 40, "WPA2 Personal"),
            ("Office-Guest",  "aa:bb:cc:11:22:51", -66,  6, 40, "Open"),
            # 2F-living
            ("Office-WiFi",   "aa:bb:cc:33:44:13", -60, 36, 80, "WPA2 Enterprise"),
            ("Office-Guest",  "aa:bb:cc:33:44:14", -61, 36, 80, "Open"),
            ("Office-IoT",    "aa:bb:cc:33:44:10", -68, 11, 40, "WPA2 Personal"),
            ("Office-Guest",  "aa:bb:cc:33:44:11", -68, 11, 40, "Open"),
            # 3F-attic — same SSID, much stronger; should trigger the
            # "stronger same-name AP nearby" diagnostic + roam hint
            ("Office-WiFi",   "aa:bb:cc:55:66:0b", -52, 48, 80, "WPA2 Enterprise"),
            ("Office-Guest",  "aa:bb:cc:55:66:0c", -53, 48, 80, "Open"),
            ("Office-IoT",    "aa:bb:cc:55:66:08", -56,  1, 40, "WPA2 Personal"),
            # Cafe across the corridor — open guest portal on the same
            # 5 GHz channel as the user; feeds the channel-load warning.
            ("guest-cafe",    "96:de:ad:be:ef:01", -75, 48, 20, "Open"),
            # Unrelated neighbours
            ("neighbour-2g",  "f2:11:22:33:44:55", -78,  6, 20, "WPA2 Personal"),
            ("",              "f2:11:22:33:44:56", -82,  6, 20, "WPA2 Personal"),
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
            )
            for ssid, bssid, rssi, ch, width, security in rows
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

    Mirrors the device population the spec calls out (AirPods, Apple
    Watch, smart-home gadgets, BLE keyboards, generic iBeacons). The
    devices already reflect post-merge state: one (merged 3) row
    demonstrates the rotated-UUID badge.
    """
    def d(
        ident: str, *, name: str | None, vendor: str | None, vendor_id: int | None,
        services: tuple[str, ...], rssi: int, connectable: bool = True,
        ad_count: int = 4, age_s: int = 1, merged: int = 1,
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
        )
    return [
        d("550e8400-e29b-41d4-a716-446655440000",
          name="AirPods Pro", vendor="Apple, Inc.", vendor_id=76,
          services=("180A",), rssi=-42, ad_count=12, age_s=1),
        d("aabbccdd-1111-4111-8111-111122223333",
          name=None, vendor="Apple, Inc.", vendor_id=76,
          services=("FE9F",), rssi=-55, ad_count=8, age_s=2, merged=3),
        d("11223344-5566-4877-8899-aabbccddeeff",
          name="Magic Keyboard", vendor="Apple, Inc.", vendor_id=76,
          services=("1812", "1124"), rssi=-58, ad_count=20, age_s=1),
        d("99887766-aabb-4ccd-8eef-001122334455",
          name="Galaxy Watch6", vendor="Samsung Electronics Co. Ltd.",
          vendor_id=117,
          services=("180D",), rssi=-63, ad_count=6, age_s=3),
        d("deadbeef-cafe-4001-8002-feedface0000",
          name="Tile Mate", vendor="Tile, Inc.", vendor_id=323,
          services=("FEED",), rssi=-71, ad_count=15, age_s=4),
        d("8b9c4f12-aaaa-4bbb-8ccc-dddddddddddd",
          name=None, vendor="Microsoft", vendor_id=6,
          services=(), rssi=-78, ad_count=3, age_s=5, connectable=False),
        d("0a1b2c3d-4e5f-4111-8222-333444555666",
          name=None, vendor=None, vendor_id=None,
          services=("FFE0",), rssi=-86, ad_count=2, age_s=6,
          connectable=False),
    ]


def _preview_view() -> str:
    return (os.environ.get("WIFISCOPE_PREVIEW_VIEW") or "wifi").lower()


async def main() -> None:
    view = _preview_view()
    app = WifiScopeApp(_FakeBackend(), _INVENTORY)
    async with app.run_test(size=(160, 56)) as pilot:
        # let one connection update + one scan land
        await pilot.pause(2.0)
        # seed a roam event so the bottom panel has content
        roam_panel = pilot.app.query_one("#roam")
        roam_panel.append_roam(
            RoamEvent(
                timestamp=datetime.now(),
                previous_bssid="aa:bb:cc:33:44:13",
                previous_channel=36,
                new_bssid="aa:bb:cc:11:22:53",
                new_channel=48,
            ),
            _INVENTORY,
        )
        if view == "ble":
            # Inject synthetic BLE devices and switch the panel to BLE
            # view. We bypass the live BLE poller entirely — the goal
            # of the SVG is a deterministic, network-free render, and
            # spinning up a real subprocess from a pytest pilot is not
            # worth the flakiness.
            from wifiscope.tui import BLEPanel
            now_utc = datetime.now(timezone.utc)
            pilot.app._latest_ble = _synthetic_ble_devices(now_utc)
            pilot.app._ble_permission_state = "granted"
            await pilot.press("n")
            await pilot.pause(0.3)
        await pilot.pause(0.3)
        out = pilot.app.export_screenshot(title="wifiscope")
    out = _fix_cjk_textlength(out)
    base = "preview-ble" if view == "ble" else "preview"
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


if __name__ == "__main__":
    asyncio.run(main())
