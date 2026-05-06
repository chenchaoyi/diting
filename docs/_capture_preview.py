"""Generate docs/preview.svg by running the TUI against a fake backend.

Data is synthetic — no real BSSIDs, IPs, or MAC addresses from the
maintainer's environment. Re-run any time the UI changes:

    uv run python docs/_capture_preview.py
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path

from wifiscope.backend import WiFiBackend
from wifiscope.models import Connection, ScanResult
from wifiscope.network import APEntry, NetworkInventory
from wifiscope.poller import RoamEvent
from wifiscope.tui import WifiScopeApp


class _FakeBackend(WiFiBackend):
    name = "macOS CoreWLAN"

    def __init__(self) -> None:
        self._helper_path = "/Applications/wifiscope-helper.app/Contents/MacOS/wifiscope-helper"

    def get_connection(self) -> Connection:
        return Connection(
            ssid="Office-WiFi",
            bssid="aa:bb:cc:11:22:53",  # 1F-bedroom 5G radio
            rssi_dbm=-58,
            noise_dbm=-95,
            tx_rate_mbps=720.0,
            channel=48,
            channel_width_mhz=80,
            channel_band="5 GHz",
            phy_mode="802.11ax",
            security="WPA2 Personal",
            mcs_index=9,
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
        rows: list[tuple[str, str, int, int, int]] = [
            # ssid, bssid, rssi, channel, width
            ("Office-WiFi",   "aa:bb:cc:11:22:53", -58, 48, 80),
            ("Office-Guest",  "aa:bb:cc:11:22:54", -58, 48, 80),
            ("Office-WiFi",   "aa:bb:cc:11:22:50", -55,  6, 40),
            ("Office-Guest",  "aa:bb:cc:11:22:51", -56,  6, 40),
            ("Office-WiFi",   "aa:bb:cc:33:44:13", -65, 36, 80),
            ("Office-Guest",  "aa:bb:cc:33:44:14", -65, 36, 80),
            ("Office-WiFi",   "aa:bb:cc:33:44:10", -68, 11, 40),
            ("Office-Guest",  "aa:bb:cc:33:44:11", -68, 11, 40),
            ("Office-WiFi",   "aa:bb:cc:55:66:0b", -76, 36, 80),
            ("Office-WiFi",   "aa:bb:cc:55:66:08", -78,  1, 40),
            ("neighbour",     "f2:11:22:33:44:55", -82,  6, 20),
            ("",              "f2:11:22:33:44:56", -82,  6, 20),  # hidden
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
                security=None,
                timestamp=ts,
            )
            for ssid, bssid, rssi, ch, width in rows
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


async def main() -> None:
    app = WifiScopeApp(_FakeBackend(), _INVENTORY)
    async with app.run_test(size=(120, 38)) as pilot:
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
        await pilot.pause(0.3)
        out = pilot.app.export_screenshot(title="wifiscope")
    target = Path(__file__).parent / "preview.svg"
    target.write_text(out)
    print(f"wrote {target} ({len(out):,} bytes)")


if __name__ == "__main__":
    asyncio.run(main())
