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

from diting.backend import WiFiBackend
from diting.models import Connection, ScanResult
from diting.network import APEntry, NetworkInventory
from diting.tui import HelpScreen, DitingApp


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
    app = DitingApp(_FakeBackend(), _INVENTORY, scan_interval=scan_interval)
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
        app = DitingApp(_FakeBackend(), _INVENTORY)
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
    app = DitingApp(_FakeBackend(), _INVENTORY, scan_interval=4.5)
    assert app._poller._scan_interval == 4.5


def test_toggle_view_swaps_third_panel():
    """Press `n` to advance through the wifi → ble → mdns → wifi cycle.
    All three panels stay mounted; only display flips, so each swap
    is instant and consumer state is preserved."""
    import asyncio
    from diting.tui import BLEPanel, BonjourPanel

    async def go():
        app = DitingApp(_FakeBackend(), _INVENTORY)
        async with app.run_test(size=(140, 50)) as pilot:
            await pilot.pause(0.5)
            scan = app.query_one("#scan")
            ble = app.query_one("#ble", BLEPanel)
            mdns = app.query_one("#mdns", BonjourPanel)
            assert scan.display is True
            assert ble.display is False
            assert mdns.display is False
            assert app._view_mode == "wifi"
            # wifi → ble
            await pilot.press("n")
            await pilot.pause(0.2)
            assert app._view_mode == "ble"
            assert scan.display is False
            assert ble.display is True
            assert mdns.display is False
            # ble → mdns
            await pilot.press("n")
            await pilot.pause(0.2)
            assert app._view_mode == "mdns"
            assert scan.display is False
            assert ble.display is False
            assert mdns.display is True
            # mdns → wifi (cycle wraps)
            await pilot.press("n")
            await pilot.pause(0.2)
            assert app._view_mode == "wifi"
            assert scan.display is True
            assert ble.display is False
            assert mdns.display is False
            await pilot.press("q")

    asyncio.run(go())


def test_view_toggle_cycles_wifi_ble_mdns_wifi():
    """Alias of test_toggle_view_swaps_third_panel — kept under the
    name referenced by the TESTING.md row so future readers can find
    the citation directly. Three presses return to wifi."""
    import asyncio
    from diting.tui import BLEPanel, BonjourPanel

    async def go():
        app = DitingApp(_FakeBackend(), _INVENTORY)
        async with app.run_test(size=(140, 50)) as pilot:
            await pilot.pause(0.4)
            assert app._view_mode == "wifi"
            for expected in ("ble", "mdns", "wifi"):
                await pilot.press("n")
                await pilot.pause(0.2)
                assert app._view_mode == expected
            await pilot.press("q")

    asyncio.run(go())


def test_app_constructs_bonjour_panel_lazily():
    """The `BonjourPoller` is instantiated only when the user first
    transitions into the mDNS view. Before that, `_mdns_poller` is
    None and `zeroconf` may not even be imported."""
    import asyncio
    from diting.tui import BonjourPanel

    async def go():
        app = DitingApp(_FakeBackend(), _INVENTORY)
        async with app.run_test(size=(140, 50)) as pilot:
            await pilot.pause(0.4)
            assert app._mdns_poller is None
            # Cycle wifi → ble → mdns. After the third press the
            # poller should be instantiated.
            await pilot.press("n")
            await pilot.press("n")
            await pilot.pause(0.3)
            assert app._mdns_poller is not None
            assert app._view_mode == "mdns"
            await pilot.press("q")

    asyncio.run(go())


def test_events_modal_open_and_close():
    """Press `m` to open EventsScreen; press `m` again to close.
    Mirrors the help-modal smoke test pattern for the v0.7.0 binding."""
    import asyncio
    from diting.tui import EventsScreen

    async def go():
        app = DitingApp(_FakeBackend(), _INVENTORY,
                           enable_latency=False, enable_environment=False)
        async with app.run_test(size=(140, 50)) as pilot:
            await pilot.pause(0.4)
            await pilot.press("m")
            await pilot.pause(0.3)
            modals = [s for s in app.screen_stack if isinstance(s, EventsScreen)]
            assert len(modals) == 1
            await pilot.press("escape")
            await pilot.pause(0.2)
            modals = [s for s in app.screen_stack if isinstance(s, EventsScreen)]
            assert len(modals) == 0
            await pilot.press("q")

    asyncio.run(go())


def test_diagnostics_renders_link_line_when_latency_data_available():
    """Inject latency aggregates and an environment monitor, then
    confirm the Diagnostics body contains the new ``Link`` and
    ``Environment`` rows. Done through update_environment so we
    exercise the same code path the live consumer uses."""
    import asyncio
    from datetime import datetime

    from diting.environment import EnvironmentMonitor
    from diting.latency import LatencyAggregate
    from diting.tui import EnvironmentPanel

    async def go():
        app = DitingApp(_FakeBackend(), _INVENTORY,
                           enable_latency=False, enable_environment=False)
        async with app.run_test(size=(140, 50)) as pilot:
            await pilot.pause(0.4)
            panel = app.query_one("#env", EnvironmentPanel)
            results = app._cached_scan or _FakeBackend().scan()
            link = (
                LatencyAggregate(
                    target="router", target_ip="10.0.0.1",
                    rtt_ms=14.0, loss_pct=0.0, jitter_ms=2.0,
                    sample_count=30,
                ),
                LatencyAggregate(
                    target="wan", target_ip="8.8.8.8",
                    rtt_ms=22.0, loss_pct=0.0, jitter_ms=3.0,
                    sample_count=30,
                ),
                None,
            )
            env = ("stable", 1.4, None)
            panel.update_environment(results, app._latest_connection,
                                     link=link, env=env)
            from io import StringIO

            from rich.console import Console
            content = getattr(panel, "_Static__content")
            console = Console(file=StringIO(), width=140, force_terminal=False)
            console.print(content)
            text = console.file.getvalue()
            assert "Link" in text
            assert "Router 14 ms" in text
            assert "Environment" in text
            assert "stable" in text
            await pilot.press("q")

    asyncio.run(go())


def test_unified_events_panel_renders_roam_and_stir_interleaved():
    """The events panel accepts both roam events (from the WiFi
    poller) and rf_stir events (from the EnvironmentMonitor) into
    one ring buffer. Pump one of each in and verify both surface."""
    import asyncio
    from datetime import datetime

    from textual.widgets import RichLog

    from diting.environment import RFStirEvent
    from diting.poller import RoamEvent
    from diting.tui import EventsPanel

    async def go():
        app = DitingApp(_FakeBackend(), _INVENTORY,
                           enable_latency=False, enable_environment=False)
        async with app.run_test(size=(140, 50)) as pilot:
            await pilot.pause(0.4)
            panel = app.query_one("#roam", EventsPanel)
            panel.append_event(
                RoamEvent(
                    timestamp=datetime.now(),
                    previous_bssid="aa:bb:cc:11:22:50",
                    previous_channel=36,
                    new_bssid="aa:bb:cc:33:44:10",
                    new_channel=48,
                ),
                _INVENTORY,
            )
            panel.append_event(
                RFStirEvent(
                    timestamp=datetime.now(),
                    bssid="aa:bb:cc:11:22:53",
                    location="1F-bedroom",
                    magnitude_db=8.3, duration_s=12.0,
                    confidence="high", mode="co_located",
                ),
                _INVENTORY,
            )
            from io import StringIO

            from rich.console import Console
            console = Console(file=StringIO(), width=140, force_terminal=False)
            for line in panel.lines:
                console.print(line)
            text = console.file.getvalue()
            assert "[ROAM]" in text
            assert "[STIR]" in text
            assert "1F-bedroom" in text
            # The "(no events yet)" placeholder must be cleared once
            # the first real event arrives — otherwise it sits above
            # the live log forever (regression seen on 0.7.0 RC).
            assert "no events yet" not in text
            assert "暂无事件" not in text
            await pilot.press("q")

    asyncio.run(go())


def test_app_with_notify_calls_watchdog_on_event(monkeypatch):
    """`DitingApp(notify=True)` constructs watchdog state and routes
    events through it. We patch the real `osascript` notifier with a
    recording stub so the test never spawns a subprocess, then drive
    one anomaly payload through `_maybe_notify` and assert the stub
    was called exactly once with the expected message body."""
    import asyncio

    import diting._watchdog as wd

    calls: list[tuple[str, str]] = []

    async def fake_notifier(*, title: str, message: str) -> None:
        calls.append((title, message))

    monkeypatch.setattr(wd, "_macos_notify", fake_notifier)

    async def go():
        app = DitingApp(
            _FakeBackend(), _INVENTORY,
            enable_latency=False, enable_environment=False,
            notify=True,
        )
        async with app.run_test(size=(140, 50)) as pilot:
            await pilot.pause(0.4)
            assert app._notify_enabled is True
            assert app._watchdog_cfg is not None
            assert app._silence_clock is not None
            await app._maybe_notify(
                {"type": "latency_spike", "target": "gw", "rtt_ms": 240.5},
                target="gw",
            )
            await pilot.press("q")

    asyncio.run(go())

    assert len(calls) == 1
    title, message = calls[0]
    assert title == "diting"
    assert "Latency spike on gw" in message
    assert "240.5" in message


def test_app_without_notify_does_not_call_watchdog(monkeypatch):
    """`DitingApp()` with the default `notify=False` keeps the
    notification side-effect inert — `_maybe_notify` is a no-op."""
    import asyncio

    import diting._watchdog as wd

    calls: list[tuple[str, str]] = []

    async def fake_notifier(*, title: str, message: str) -> None:
        calls.append((title, message))

    monkeypatch.setattr(wd, "_macos_notify", fake_notifier)

    async def go():
        app = DitingApp(
            _FakeBackend(), _INVENTORY,
            enable_latency=False, enable_environment=False,
        )
        async with app.run_test(size=(140, 50)) as pilot:
            await pilot.pause(0.4)
            assert app._notify_enabled is False
            assert app._watchdog_cfg is None
            assert app._silence_clock is None
            await app._maybe_notify(
                {"type": "latency_spike", "target": "gw", "rtt_ms": 240.5},
                target="gw",
            )
            await pilot.press("q")

    asyncio.run(go())

    assert calls == []


def test_ble_panel_renders_both_connected_and_advertising_sections():
    """Seed both the advertising buffer and the connected buffer, then
    press `n` to enter the BLE view. The BLEPanel body must contain
    both section headers ('Connected' / 'Advertising') and a row from
    each so the spec's two-section layout is preserved end-to-end."""
    import asyncio
    from datetime import datetime, timedelta, timezone

    from textual.widgets import Static

    from diting.ble import BLEDevice
    from diting.tui import BLEPanel

    async def go():
        app = DitingApp(_FakeBackend(), _INVENTORY)
        async with app.run_test(size=(160, 56)) as pilot:
            await pilot.pause(0.5)
            now = datetime.now(timezone.utc)
            advert = BLEDevice(
                identifier="ad000000-0000-0000-0000-000000000001",
                name="AirTag",
                vendor="Apple, Inc.",
                vendor_id=76,
                services=("FD5A",),
                rssi_dbm=-42,
                is_connectable=False,
                first_seen=now - timedelta(seconds=8),
                last_seen=now,
                ad_count=4,
                type="AirTag",
            )
            connected = BLEDevice(
                identifier="cc000000-0000-0000-0000-000000000001",
                name="Magic Keyboard",
                vendor=None,
                vendor_id=None,
                services=("1812",),
                rssi_dbm=None,
                is_connectable=True,
                first_seen=now,
                last_seen=now,
                ad_count=0,
                is_connected=True,
            )
            app._latest_ble = [advert]
            app._latest_ble_connected = [connected]
            app._ble_permission_state = "granted"
            await pilot.press("n")
            await pilot.pause(0.3)
            ble = app.query_one("#ble", BLEPanel)
            body = ble.query_one("#ble-body", Static)
            # Static stores the most recent argument to .update() in a
            # private name-mangled attribute; the rich.console.Group we
            # built is reachable that way. Render via a Console without
            # ANSI escapes so the assertion is on plain text.
            renderable = getattr(body, "_Static__content")
            from io import StringIO
            from rich.console import Console
            console = Console(file=StringIO(), width=160, force_terminal=False)
            console.print(renderable)
            text = console.file.getvalue()
            assert "Connected (1)" in text
            assert "Advertising (1)" in text
            assert "Magic Keyboard" in text
            assert "AirTag" in text
            await pilot.press("q")

    asyncio.run(go())
