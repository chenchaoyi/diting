"""Headless TUI smoke tests using Textual's run_test pilot.

These prove the App can boot, drive every binding without raising,
and tear down cleanly. They use a fake backend so CI runners (which
do not have a Wi-Fi association on macOS-latest) can still exercise
the rendering path. Live CoreWLAN integration is intentionally out of
scope here — the unit tests cover the pure-logic transforms above.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest

from wifiscope.backend import WiFiBackend
from wifiscope.models import Connection, ScanResult
from wifiscope.network import APEntry, NetworkInventory
from wifiscope.tui import HelpScreen, WifiScopeApp


class _FakeBackend(WiFiBackend):
    """A backend that returns deterministic data and never touches
    CoreWLAN. Lets the TUI mount and update without a real radio.
    """

    name = "fake"

    def __init__(self) -> None:
        self._helper_path = None
        self._tick = 0

    def get_connection(self) -> Connection | None:
        self._tick += 1
        return Connection(
            ssid="testnet", bssid="40:fe:95:89:c7:e3",
            rssi_dbm=-50 - (self._tick % 5),
            noise_dbm=-94, tx_rate_mbps=300.0,
            channel=48, channel_width_mhz=80, channel_band="5 GHz",
            phy_mode="802.11ax", security="WPA2 Personal",
            mcs_index=5, nss=2, timestamp=datetime.now(),
            interface_mac="84:2f:57:9b:15:59", country_code="CN",
            ip_address="10.0.0.2", router_ip="10.0.0.1",
            max_link_speed_mbps=867,
        )

    def scan(self) -> list[ScanResult]:
        ts = datetime.now()
        return [
            ScanResult(
                ssid="testnet", bssid="40:fe:95:89:c7:e3",
                rssi_dbm=-55, noise_dbm=-94, channel=48,
                channel_width_mhz=80, channel_band="5 GHz",
                phy_mode=None, security=None, timestamp=ts,
            ),
            ScanResult(
                ssid="testnet", bssid="40:fe:95:8a:3c:55",
                rssi_dbm=-65, noise_dbm=-94, channel=1,
                channel_width_mhz=20, channel_band="2.4 GHz",
                phy_mode=None, security=None, timestamp=ts,
            ),
            ScanResult(
                ssid="neighbour", bssid="aa:bb:cc:dd:ee:01",
                rssi_dbm=-80, noise_dbm=-94, channel=11,
                channel_width_mhz=20, channel_band="2.4 GHz",
                phy_mode=None, security=None, timestamp=ts,
            ),
        ]

    def permission_state(self) -> Any:
        return "granted"


_INVENTORY = NetworkInventory(
    aps=(
        APEntry(name="testroom", mgmt_mac="40:fe:95:89:c7:df"),
    ),
)


async def _run_pilot(*key_presses: str, scan_interval: float = 7.0) -> None:
    app = WifiScopeApp(_FakeBackend(), _INVENTORY, scan_interval=scan_interval)
    async with app.run_test(size=(140, 50)) as pilot:
        await pilot.pause(0.6)  # let one connection update + one scan land
        for k in key_presses:
            await pilot.press(k)
            await pilot.pause(0.2)
        # Always quit at the end so the app exits cleanly
        if not key_presses or key_presses[-1] != "q":
            await pilot.press("q")


def test_app_boots_and_quits():
    """Compose, mount, render — minimum-viable proof the App is wired."""
    import asyncio
    asyncio.run(_run_pilot())


def test_pause_and_resume():
    import asyncio
    asyncio.run(_run_pilot("p", "p"))


def test_force_rescan_does_not_crash():
    import asyncio
    asyncio.run(_run_pilot("r"))


def test_cycle_sort_modes():
    """Two presses cycle ap -> signal -> ap."""
    import asyncio
    asyncio.run(_run_pilot("s", "s"))


def test_help_modal_open_and_close():
    """Pressing 'h' opens the help modal; Esc closes it. Both code paths
    must render the help body without raising (regression: an earlier
    version used Textual CSS variables in Rich style strings and crashed
    on first show)."""
    import asyncio
    asyncio.run(_run_pilot("h", "escape"))


def test_help_modal_h_to_close():
    """The 'h' key inside the modal also closes — convenience binding."""
    import asyncio
    asyncio.run(_run_pilot("h", "h"))


def test_help_modal_renders_through_pilot_query():
    """Verify the modal actually mounts (not just that key handling
    doesn't error)."""
    import asyncio

    async def go():
        app = WifiScopeApp(_FakeBackend(), _INVENTORY)
        async with app.run_test(size=(140, 50)) as pilot:
            await pilot.pause(0.5)
            await pilot.press("h")
            await pilot.pause(0.3)
            modals = [s for s in app.screen_stack if isinstance(s, HelpScreen)]
            assert len(modals) == 1
            await pilot.press("escape")
            await pilot.pause(0.2)
            modals = [s for s in app.screen_stack if isinstance(s, HelpScreen)]
            assert len(modals) == 0
            await pilot.press("q")

    asyncio.run(go())


def test_custom_scan_interval_threads_through():
    """The scan_interval kwarg lands on the underlying poller."""
    app = WifiScopeApp(_FakeBackend(), _INVENTORY, scan_interval=4.5)
    assert app._poller._scan_interval == 4.5


def test_toggle_view_swaps_third_panel():
    """Press `n` to toggle from the Wi-Fi scan view to the BLE view,
    then `n` again to return. Both panels stay mounted; only display
    flips, so the swap is instant and consumer state is preserved."""
    import asyncio
    from wifiscope.tui import BLEPanel

    async def go():
        app = WifiScopeApp(_FakeBackend(), _INVENTORY)
        async with app.run_test(size=(140, 50)) as pilot:
            await pilot.pause(0.5)
            scan = app.query_one("#scan")
            ble = app.query_one("#ble", BLEPanel)
            assert scan.display is True
            assert ble.display is False
            assert app._view_mode == "wifi"
            await pilot.press("n")
            await pilot.pause(0.2)
            assert app._view_mode == "ble"
            assert scan.display is False
            assert ble.display is True
            await pilot.press("n")
            await pilot.pause(0.2)
            assert app._view_mode == "wifi"
            assert scan.display is True
            assert ble.display is False
            await pilot.press("q")

    asyncio.run(go())
