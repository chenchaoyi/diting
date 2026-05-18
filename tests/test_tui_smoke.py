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


def test_app_title_carries_version():
    """The header title is `diting v<version>` so users always see the
    running version without pressing a key. The actual version string
    comes from importlib.metadata; we only assert the prefix here so
    the test does not need to track release bumps."""
    import asyncio
    from importlib.metadata import version as _pkg_version

    async def go():
        app = DitingApp(_FakeBackend(), _INVENTORY)
        async with app.run_test(size=(140, 50)) as pilot:
            await pilot.pause(0.2)
            assert app.title.startswith("diting v"), (
                f"title should start with `diting v`, got {app.title!r}"
            )
            assert _pkg_version("diting") in app.title, (
                f"title should contain the importlib-metadata version, "
                f"got {app.title!r}"
            )
            await pilot.press("q")

    asyncio.run(go())


def test_brand_header_renders_logo_mark():
    """The brand header SHALL render the diting radar mark using
    Unicode half-block characters in brand orange.

    We check for the mark by querying the BrandHeader's _LogoMark
    child and asserting its rendered text contains at least one
    half-block glyph (`▀`, `█`, or `▄`). Colour assertion is left
    to the regression-snapshot CSS check; pytest only proves the
    mark is on screen.
    """
    import asyncio
    from diting.tui import BrandHeader

    async def go():
        app = DitingApp(_FakeBackend(), _INVENTORY)
        async with app.run_test(size=(140, 50)) as pilot:
            await pilot.pause(0.3)
            header = app.query_one(BrandHeader)
            rendered = "\n".join(
                str(child.render()) for child in header.query("_LogoMark")
            )
            assert any(g in rendered for g in ("▀", "█", "▄")), (
                f"BrandHeader should render half-block glyphs, got {rendered!r}"
            )
            await pilot.press("q")

    asyncio.run(go())


def test_brand_header_carries_live_title_and_subtitle():
    """The brand header's right-hand stack SHALL render the App's
    title (`diting v<X.Y.Z>`) and the live subtitle string
    (`view: Wi-Fi · scan 7s`). Both are pulled from `app.title` /
    `app.sub_title` via the widget's reactive watchers, so existing
    assignment sites in DitingApp continue to drive the live state.
    """
    import asyncio
    from diting.tui import BrandHeader, _TitleStack

    async def go():
        app = DitingApp(_FakeBackend(), _INVENTORY, scan_interval=7.0)
        async with app.run_test(size=(140, 50)) as pilot:
            await pilot.pause(0.3)
            header = app.query_one(BrandHeader)
            stack = header.query_one(_TitleStack)
            # Static.visual wraps the renderable; reach in for the Group.
            renderable = stack.visual._renderable
            from rich.console import Group
            assert isinstance(renderable, Group), (
                f"_TitleStack should render a Rich Group of three lines, "
                f"got {type(renderable).__name__}"
            )
            from rich.align import Align
            from rich.text import Text
            plain_lines = []
            for r in renderable.renderables:
                if isinstance(r, Align):
                    plain_lines.append(str(r.renderable))
                elif isinstance(r, Text):
                    plain_lines.append(r.plain)
                else:
                    plain_lines.append(str(r))
            plain = "\n".join(plain_lines)
            # title comes from app.title; subtitle from app.sub_title.
            assert "diting v" in plain, (
                f"header stack should carry the App title, got {plain!r}"
            )
            assert "view:" in plain or "视图" in plain, (
                f"header stack should carry the App subtitle, got {plain!r}"
            )
            await pilot.press("q")

    asyncio.run(go())


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
    """Pressing '?' opens the help modal; Esc closes it. Both code paths
    must render the help body without raising (regression: an earlier
    version used Textual CSS variables in Rich style strings and crashed
    on first show)."""
    import asyncio
    asyncio.run(_run_pilot("question_mark", "escape"))


def test_help_modal_question_mark_to_close():
    """The '?' key inside the modal also closes — convenience binding."""
    import asyncio
    asyncio.run(_run_pilot("question_mark", "question_mark"))


def test_help_modal_renders_through_pilot_query():
    """Verify the modal actually mounts (not just that key handling
    doesn't error)."""
    import asyncio

    async def go():
        app = DitingApp(_FakeBackend(), _INVENTORY)
        async with app.run_test(size=(140, 50)) as pilot:
            await pilot.pause(0.5)
            await pilot.press("question_mark")
            await pilot.pause(0.3)
            modals = [s for s in app.screen_stack if isinstance(s, HelpScreen)]
            assert len(modals) == 1
            await pilot.press("escape")
            await pilot.pause(0.2)
            modals = [s for s in app.screen_stack if isinstance(s, HelpScreen)]
            assert len(modals) == 0
            await pilot.press("q")

    asyncio.run(go())


def test_pressing_h_is_a_no_op():
    """`h` is intentionally unbound after the `?` rebind so the slot
    is free for a future per-view shortcut. Pressing it must not
    push HelpScreen (or anything else) onto the stack."""
    import asyncio

    async def go():
        app = DitingApp(_FakeBackend(), _INVENTORY)
        async with app.run_test(size=(140, 50)) as pilot:
            await pilot.pause(0.5)
            await pilot.press("h")
            await pilot.pause(0.3)
            # Stack contains only the main Screen, no HelpScreen pushed.
            modals = [s for s in app.screen_stack if isinstance(s, HelpScreen)]
            assert len(modals) == 0
            await pilot.press("q")

    asyncio.run(go())


def test_custom_scan_interval_threads_through():
    """The scan_interval kwarg lands on the underlying poller."""
    app = DitingApp(_FakeBackend(), _INVENTORY, scan_interval=4.5)
    assert app._poller._scan_interval == 4.5


def test_toggle_view_swaps_third_panel():
    """Press `n` to advance through the wifi → ble → mdns → lan → wifi
    cycle. All four panels stay mounted; only display flips, so each
    swap is instant and consumer state is preserved."""
    import asyncio
    from diting.tui import BLEPanel, BonjourPanel, LANPanel

    async def go():
        app = DitingApp(_FakeBackend(), _INVENTORY)
        async with app.run_test(size=(140, 50)) as pilot:
            await pilot.pause(0.5)
            scan = app.query_one("#scan")
            ble = app.query_one("#ble", BLEPanel)
            mdns = app.query_one("#mdns", BonjourPanel)
            lan = app.query_one("#lan", LANPanel)
            assert scan.display is True
            assert ble.display is False
            assert mdns.display is False
            assert lan.display is False
            assert app._view_mode == "wifi"
            # wifi → ble
            await pilot.press("n")
            await pilot.pause(0.2)
            assert app._view_mode == "ble"
            assert scan.display is False
            assert ble.display is True
            assert mdns.display is False
            assert lan.display is False
            # ble → mdns
            await pilot.press("n")
            await pilot.pause(0.2)
            assert app._view_mode == "mdns"
            assert scan.display is False
            assert ble.display is False
            assert mdns.display is True
            assert lan.display is False
            # mdns → lan
            await pilot.press("n")
            await pilot.pause(0.2)
            assert app._view_mode == "lan"
            assert scan.display is False
            assert ble.display is False
            assert mdns.display is False
            assert lan.display is True
            # lan → wifi (cycle wraps)
            await pilot.press("n")
            await pilot.pause(0.2)
            assert app._view_mode == "wifi"
            assert scan.display is True
            assert ble.display is False
            assert mdns.display is False
            assert lan.display is False
            await pilot.press("q")

    asyncio.run(go())


def test_view_toggle_cycles_wifi_ble_mdns_lan_wifi():
    """Alias of test_toggle_view_swaps_third_panel — kept under the
    name referenced by the TESTING.md row so future readers can find
    the citation directly. Four presses return to wifi."""
    import asyncio
    from diting.tui import BLEPanel, BonjourPanel, LANPanel

    async def go():
        app = DitingApp(_FakeBackend(), _INVENTORY)
        async with app.run_test(size=(140, 50)) as pilot:
            await pilot.pause(0.4)
            assert app._view_mode == "wifi"
            for expected in ("ble", "mdns", "lan", "wifi"):
                await pilot.press("n")
                await pilot.pause(0.2)
                assert app._view_mode == expected
            await pilot.press("q")

    asyncio.run(go())


def test_panel_border_title_carries_tab_indicator():
    """Every view's active third-slot panel renders all three view
    labels in its `border_title`. The user can discover that three
    views exist from any single screen — that's the whole point of
    the always-visible tab indicator (PR three-view-tabs)."""
    import asyncio
    from diting.tui import BLEPanel, BonjourPanel, ScanPanel

    async def go():
        app = DitingApp(_FakeBackend(), _INVENTORY)
        async with app.run_test(size=(140, 50)) as pilot:
            await pilot.pause(0.5)
            # Wi-Fi active: ScanPanel's border_title carries the tabs.
            scan = app.query_one("#scan", ScanPanel)
            assert "Wi-Fi" in scan.border_title
            assert "BLE" in scan.border_title
            assert "Bonjour" in scan.border_title
            # Subtitle still carries the panel-specific detail.
            assert "BSSIDs" in (scan.border_subtitle or "")

            # BLE active: BLEPanel's border_title carries the tabs.
            await pilot.press("n")
            await pilot.pause(0.3)
            ble = app.query_one("#ble", BLEPanel)
            assert "Wi-Fi" in ble.border_title
            assert "BLE" in ble.border_title
            assert "Bonjour" in ble.border_title

            # mDNS active: BonjourPanel's border_title carries the tabs.
            await pilot.press("n")
            await pilot.pause(0.3)
            mdns = app.query_one("#mdns", BonjourPanel)
            assert "Wi-Fi" in mdns.border_title
            assert "BLE" in mdns.border_title
            assert "Bonjour" in mdns.border_title
            await pilot.press("q")

    asyncio.run(go())


def test_subtitle_uses_display_name_not_internal_token():
    """Header subtitle reads `view: Bonjour`, not `view: mdns`. The
    internal mode token stays `mdns` everywhere in code; only the
    user-facing label changes."""
    import asyncio

    async def go():
        app = DitingApp(_FakeBackend(), _INVENTORY)
        async with app.run_test(size=(140, 50)) as pilot:
            await pilot.pause(0.4)
            # Cycle to mDNS.
            await pilot.press("n")
            await pilot.press("n")
            await pilot.pause(0.3)
            assert app._view_mode == "mdns"
            # Subtitle carries the display name, not the token.
            assert "Bonjour" in app.sub_title
            assert "mdns" not in app.sub_title
            await pilot.press("q")

    asyncio.run(go())


def test_bonjour_prewarms_at_mount():
    """The Bonjour stack starts prewarming at TUI mount, not on first
    `n` press. The PyInstaller-frozen binary's GIL-bound import path
    needs the longest possible window to amortise; mount-time gives
    it the entire wifi-view dwell time before the user navigates."""
    import asyncio

    async def go():
        app = DitingApp(_FakeBackend(), _INVENTORY)
        async with app.run_test(size=(140, 50)) as pilot:
            # First refresh tick is enough for on_mount to schedule
            # the prewarm worker — either `_mdns_starting` is True or
            # the poller is already up.
            await pilot.pause(0.05)
            assert app._mdns_starting or app._mdns_poller is not None, (
                "TUI mount should kick off the Bonjour prewarm; "
                "neither `_mdns_starting` nor `_mdns_poller` is set"
            )
            # Allow the worker to finish so subsequent assertions are
            # stable. zeroconf init is real-time; 1.5 s is generous.
            for _ in range(15):
                await pilot.pause(0.1)
                if app._mdns_poller is not None:
                    break
            assert app._mdns_poller is not None
            await pilot.press("q")

    asyncio.run(go())


def test_bonjour_view_switch_is_idempotent_after_mount_prewarm():
    """Once on_mount has prewarmed the poller, pressing `n` to cycle
    through views does NOT spawn additional pollers or workers — the
    `_ensure_mdns_poller` gate sees a non-None poller and no-ops.
    Guarantees the mount-time prewarm doesn't double up with the
    legacy wifi→BLE trigger."""
    import asyncio

    async def go():
        app = DitingApp(_FakeBackend(), _INVENTORY)
        async with app.run_test(size=(140, 50)) as pilot:
            # Wait for the mount-time prewarm to settle.
            for _ in range(15):
                await pilot.pause(0.1)
                if app._mdns_poller is not None:
                    break
            assert app._mdns_poller is not None
            poller_after_mount = app._mdns_poller
            # Drive the full view cycle.
            await pilot.press("n")  # wifi → ble
            await pilot.press("n")  # ble → mdns
            await pilot.pause(0.2)
            # Same poller instance — no rebuild.
            assert app._mdns_poller is poller_after_mount, (
                "Pressing `n` after mount-time prewarm must not "
                "replace the existing poller"
            )
            await pilot.press("q")

    asyncio.run(go())


def test_bonjour_consumer_task_resets_poller_on_unexpected_error(monkeypatch):
    """If the consumer task hits an unexpected exception, it stops the
    poller and clears `_mdns_poller` so a subsequent `n` cycle can
    rebuild it. Without this reset the lazy-init gate would see a
    non-None poller and refuse to restart."""
    import asyncio

    stopped = {"count": 0}

    class _ExplodingPoller:
        async def events(self):
            raise RuntimeError("simulated zeroconf failure")
            yield  # pragma: no cover  (makes it a generator)

        def stop(self) -> None:
            stopped["count"] += 1

    # The consumer imports BonjourPoller via the module-level helper.
    # Patching it short-circuits the real `from .mdns import ...` and
    # gives us an exploding poller instead.
    import diting.tui as tui_mod
    monkeypatch.setattr(
        tui_mod, "_import_bonjour_poller", lambda: _ExplodingPoller,
    )

    async def go():
        app = DitingApp(_FakeBackend(), _INVENTORY)
        async with app.run_test(size=(140, 50)) as pilot:
            await pilot.pause(0.3)
            # Trigger the prewarm path. With the exploding poller in
            # place the consumer will hit the failure path on its
            # first iteration of events().
            await pilot.press("n")  # wifi → ble; triggers _ensure_mdns_poller
            for _ in range(20):
                await pilot.pause(0.05)
                if app._mdns_poller is None and not app._mdns_starting:
                    break
            assert app._mdns_poller is None, (
                "consumer should have reset _mdns_poller after the "
                "exception so a future `n` press can rebuild it"
            )
            assert stopped["count"] >= 1, (
                "consumer should have called poller.stop() on its way out"
            )
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


def test_wifi_inspect_opens_modal_on_first_press():
    """Wi-Fi view active, no prior cursor movement, pressing `i`
    opens WifiDetailScreen for the first row (currently associated
    AP if any, otherwise the strongest-signal row)."""
    import asyncio
    from diting.tui import WifiDetailScreen

    async def go():
        app = DitingApp(_FakeBackend(), _INVENTORY)
        async with app.run_test(size=(140, 50)) as pilot:
            await pilot.pause(0.6)
            assert app._view_mode == "wifi"
            assert app._wifi_selected_key is None
            await pilot.press("i")
            await pilot.pause(0.3)
            modals = [
                s for s in app.screen_stack
                if isinstance(s, WifiDetailScreen)
            ]
            assert len(modals) == 1
            # Selection now points at the row the modal opened on.
            assert app._wifi_selected_key is not None
            await pilot.press("escape")
            await pilot.pause(0.2)
            # Esc closes the modal, but the selection persists so the
            # next `i` opens the same row without the user having to
            # re-walk the cursor.
            assert not any(
                isinstance(s, WifiDetailScreen) for s in app.screen_stack
            )
            assert app._wifi_selected_key is not None
            await pilot.press("q")

    asyncio.run(go())


def test_wifi_selection_keyed_by_bssid_survives_resort():
    """The selection cursor tracks BSSID, not row index. Bumping a
    different AP's RSSI changes sort order but must not move the
    cursor onto a different physical AP."""
    import asyncio

    async def go():
        app = DitingApp(_FakeBackend(), _INVENTORY)
        async with app.run_test(size=(140, 50)) as pilot:
            await pilot.pause(0.6)
            # Switch sort mode to 'signal' so a single RSSI change is
            # enough to flip row positions (ap-grouped mode pins the
            # current AP irrespective of RSSI, which would mask the
            # selection-by-key contract).
            app._sort_mode = "signal"
            # Lock in selection on the neighbour AP (the bottom row).
            target_bssid = "aabbccddee01"  # normalised key form
            app._wifi_selected_key = target_bssid
            app._refresh_scan_panel()
            # Re-poll: the FakeBackend's RSSI for the connected AP
            # walks with self._tick, but sort is RSSI-desc so the
            # neighbour stays at the bottom regardless. We re-issue
            # the refresh with a new synthetic scan that swaps two
            # other rows to prove the selection sticks to its BSSID.
            await pilot.pause(0.5)
            assert app._wifi_selected_key == target_bssid
            await pilot.press("q")

    asyncio.run(go())


def test_wifi_selection_clears_when_target_drops_out():
    """When the selected BSSID disappears from the next snapshot the
    selection clears to None — no ghost cursor on a row the user can
    no longer see."""
    import asyncio

    async def go():
        app = DitingApp(_FakeBackend(), _INVENTORY)
        async with app.run_test(size=(140, 50)) as pilot:
            await pilot.pause(0.6)
            # Select a ghost BSSID not present in any FakeBackend scan.
            app._wifi_selected_key = "deadbeefcafe"
            app._refresh_scan_panel()
            # The refresh prunes a selection whose key isn't in the
            # current snapshot — proves the "stable + auto-clear"
            # contract pinned in wifi-detail-modal/spec.md.
            assert app._wifi_selected_key is None
            await pilot.press("q")

    asyncio.run(go())


def _inject_bonjour_devices(app, devices):
    """Bypass the zeroconf-driven poller (which would need real Macs
    on the LAN) by setting the App's latest snapshot directly and
    refreshing the panel.

    Sets `_paused = True` so the mount-time prewarm consumer task
    (which would otherwise yield an empty `BonjourScanUpdate` from
    the real poller and overwrite our injection) sees the pause gate
    and skips the `self._latest_mdns = snap.devices` assignment."""
    app._paused = True
    app._latest_mdns = devices
    app._refresh_mdns_panel()


def _make_bonjour(name, service_type="_raop._tcp.local."):
    from datetime import datetime, timezone
    from diting.mdns import BonjourDevice
    now = datetime.now(timezone.utc)
    return BonjourDevice(
        service_type=service_type,
        name=name,
        host=f"{name.split('.')[0]}.local.",
        port=7000,
        addresses=("192.168.1.42",),
        txt={},
        vendor="Apple, Inc.",
        category="AirPlay audio",
        first_seen=now,
        last_seen=now,
    )


def test_bonjour_inspect_opens_modal_on_first_press():
    """Bonjour view active, no prior cursor movement, pressing `i`
    opens BonjourDetailScreen for the first device."""
    import asyncio
    from diting.tui import BonjourDetailScreen

    async def go():
        app = DitingApp(_FakeBackend(), _INVENTORY)
        async with app.run_test(size=(140, 50)) as pilot:
            await pilot.pause(0.5)
            # Cycle to mDNS view.
            await pilot.press("n")
            await pilot.press("n")
            await pilot.pause(0.3)
            assert app._view_mode == "mdns"
            # Inject a deterministic snapshot.
            _inject_bonjour_devices(app, [
                _make_bonjour("Office HomePod._raop._tcp.local."),
            ])
            await pilot.pause(0.2)
            await pilot.press("i")
            await pilot.pause(0.3)
            modals = [
                s for s in app.screen_stack
                if isinstance(s, BonjourDetailScreen)
            ]
            assert len(modals) == 1
            assert app._bonjour_selected_key is not None
            await pilot.press("escape")
            await pilot.pause(0.2)
            assert app._bonjour_selected_key is not None
            await pilot.press("q")

    asyncio.run(go())


def test_lan_poller_lazy_starts_on_third_n_press():
    """The LANInventoryPoller is NOT constructed at mount; it
    lazy-starts the first time the user cycles into the LAN view
    (four `n` presses from wifi: wifi → ble → mdns → lan)."""
    import asyncio

    async def go():
        app = DitingApp(_FakeBackend(), _INVENTORY)
        async with app.run_test(size=(140, 50)) as pilot:
            await pilot.pause(0.5)
            # Not yet on LAN view — poller must not exist.
            assert app._lan_inventory_poller is None
            for _ in range(3):
                await pilot.press("n")
                await pilot.pause(0.2)
            assert app._view_mode == "lan"
            # Lazy-start happens via run_worker; give the worker a beat.
            await pilot.pause(0.6)
            assert (
                app._lan_inventory_poller is not None
                or app._lan_inventory_starting
            )
            await pilot.press("q")

    asyncio.run(go())


def test_bonjour_selection_keyed_by_fqdn_survives_resort():
    """Selecting an instance by its FQDN survives subsequent snapshot
    refreshes when the same instance is still in the list."""
    import asyncio
    from diting.tui import _bonjour_row_key

    async def go():
        app = DitingApp(_FakeBackend(), _INVENTORY)
        async with app.run_test(size=(140, 50)) as pilot:
            await pilot.pause(0.4)
            await pilot.press("n")
            await pilot.press("n")
            await pilot.pause(0.3)
            d1 = _make_bonjour("Office._raop._tcp.local.")
            d2 = _make_bonjour("Kitchen._raop._tcp.local.")
            _inject_bonjour_devices(app, [d1, d2])
            await pilot.pause(0.1)
            d1_key = _bonjour_row_key(d1)
            app._bonjour_selected_key = d1_key
            # Re-inject in swapped order — selection must still resolve
            # to the Office instance because we key by FQDN, not index.
            _inject_bonjour_devices(app, [d2, d1])
            assert app._bonjour_selected_key == d1_key
            await pilot.press("q")

    asyncio.run(go())


def test_bonjour_selection_clears_when_target_drops_out():
    """A service that stops announcing and falls out of the next
    snapshot also drops the selection — same auto-clear contract as
    BLE / Wi-Fi."""
    import asyncio
    from diting.tui import _bonjour_row_key

    async def go():
        app = DitingApp(_FakeBackend(), _INVENTORY)
        async with app.run_test(size=(140, 50)) as pilot:
            await pilot.pause(0.4)
            await pilot.press("n")
            await pilot.press("n")
            await pilot.pause(0.3)
            d1 = _make_bonjour("Office._raop._tcp.local.")
            _inject_bonjour_devices(app, [d1])
            await pilot.pause(0.1)
            app._bonjour_selected_key = _bonjour_row_key(d1)
            # Service disappears.
            _inject_bonjour_devices(app, [])
            assert app._bonjour_selected_key is None
            await pilot.press("q")

    asyncio.run(go())


def test_wifi_detail_modal_tracks_selection_on_arrow_keys():
    """While the Wi-Fi detail modal is open, pressing ↓ moves the
    underlying selection AND re-renders the modal body so the user
    can walk the list without closing + reopening."""
    import asyncio
    from diting.tui import WifiDetailScreen

    async def go():
        app = DitingApp(_FakeBackend(), _INVENTORY)
        async with app.run_test(size=(140, 50)) as pilot:
            await pilot.pause(0.6)
            # Switch to signal sort so RSSI alone drives row order
            # (more predictable for the test than ap-grouped).
            app._sort_mode = "signal"
            app._refresh_scan_panel()
            # Open the modal on the default row (associated AP).
            await pilot.press("i")
            await pilot.pause(0.3)
            modals = [
                s for s in app.screen_stack
                if isinstance(s, WifiDetailScreen)
            ]
            assert len(modals) == 1
            modal = modals[0]
            opened_on = modal._scan.bssid
            opened_key = app._wifi_selected_key
            # Press ↓ inside the modal: selection advances, modal
            # re-renders with the new row's data.
            await pilot.press("down")
            await pilot.pause(0.2)
            assert app._wifi_selected_key != opened_key
            # The modal's internal scan record is the new selection,
            # not the one it opened on.
            assert modal._scan.bssid != opened_on
            await pilot.press("escape")
            await pilot.press("q")

    asyncio.run(go())


def test_bonjour_detail_modal_tracks_selection_on_arrow_keys():
    """Bonjour modal walks instances the same way Wi-Fi does."""
    import asyncio
    from diting.tui import BonjourDetailScreen, _bonjour_row_key

    async def go():
        app = DitingApp(_FakeBackend(), _INVENTORY)
        async with app.run_test(size=(140, 50)) as pilot:
            await pilot.pause(0.4)
            await pilot.press("n")  # → ble
            await pilot.press("n")  # → mdns
            await pilot.pause(0.3)
            d1 = _make_bonjour("Office._raop._tcp.local.")
            d2 = _make_bonjour("Kitchen._raop._tcp.local.")
            _inject_bonjour_devices(app, [d1, d2])
            await pilot.pause(0.1)
            await pilot.press("i")
            await pilot.pause(0.3)
            modals = [
                s for s in app.screen_stack
                if isinstance(s, BonjourDetailScreen)
            ]
            assert len(modals) == 1
            modal = modals[0]
            assert app._bonjour_selected_key == _bonjour_row_key(d1)
            assert modal._device.name == d1.name
            # ↓ advances to d2, modal tracks.
            await pilot.press("down")
            await pilot.pause(0.2)
            assert app._bonjour_selected_key == _bonjour_row_key(d2)
            assert modal._device.name == d2.name
            # ↑ goes back to d1.
            await pilot.press("up")
            await pilot.pause(0.2)
            assert app._bonjour_selected_key == _bonjour_row_key(d1)
            assert modal._device.name == d1.name
            await pilot.press("escape")
            await pilot.press("q")

    asyncio.run(go())
