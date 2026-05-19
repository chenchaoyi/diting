"""TUI self-test harness — regression + product-opportunity exploration.

Drives the TUI through a designed sequence of states using
Textual's ``pilot`` API, captures one SVG screenshot per state,
and runs a small rule-based inspector pass over each captured
state to flag both regressions (assertions about visible content)
and product opportunities (e.g. "30% of BLE rows show unknown
vendor — expand the OUI map?").

Two flavours of output for every run:

  * One ``<scenario_id>.svg`` per scenario in the output dir (also
    rendered to ``.png`` if the platform has ``qlmanage`` or
    ``rsvg-convert`` available — purely for human inspection).
  * One ``snapshot-report.json`` with all assertions and findings,
    plus a console summary.

This module is checked in: it doubles as the regression suite for
the visual layer (which the unit tests cannot meaningfully cover)
and as a way for a contributor to systematically poke at edge
cases, find UX issues, and propose product improvements without
needing to physically sit in front of a Mac with twelve real APs.

Adding a scenario is a single dict literal at the bottom of
``SCENARIOS``; the runner takes care of pilot wiring, screenshot
capture, language switching, and inspector dispatch.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

from diting import i18n
from diting.backend import WiFiBackend
from diting.ble import BLEDevice
from diting.events import (
    LatencySpikeEvent,
    LossBurstEvent,
    RFStirEvent,
)
from diting.latency import LatencyAggregate
from diting.models import Connection, ScanResult
from diting.network import APEntry, NetworkInventory
from diting.poller import RoamEvent


# ---------- shared synthetic backends + inventory ----------

_INVENTORY = NetworkInventory(
    aps=(
        APEntry(name="1F-bedroom", mgmt_mac="aa:bb:cc:11:22:4f"),
        APEntry(name="2F-living",  mgmt_mac="aa:bb:cc:33:44:0f"),
        APEntry(name="3F-attic",   mgmt_mac="aa:bb:cc:55:66:07"),
    ),
)


class _GoodBackend(WiFiBackend):
    """Healthy connected state with a busy-but-OK home network."""
    name = "macOS CoreWLAN"

    def __init__(self) -> None:
        self._helper_path = "/Applications/diting-tianer.app/Contents/MacOS/diting-tianer"

    def get_connection(self) -> Connection:
        return Connection(
            ssid="Office-WiFi",
            bssid="aa:bb:cc:11:22:53",
            rssi_dbm=-58, noise_dbm=-95, tx_rate_mbps=360.0,
            channel=48, channel_width_mhz=80, channel_band="5 GHz",
            phy_mode="802.11ax", security="WPA2 Enterprise",
            mcs_index=7, nss=2, timestamp=datetime.now(),
            interface_mac="de:ad:be:ef:00:01", country_code="CN",
            ip_address="192.168.1.42", router_ip="192.168.1.1",
            max_link_speed_mbps=867,
        )

    def scan(self) -> list[ScanResult]:
        ts = datetime.now()
        rows = [
            ("Office-WiFi",  "aa:bb:cc:11:22:53", -58, 48, 80, "WPA2 Enterprise", 78, True),
            ("Office-Guest", "aa:bb:cc:11:22:54", -60, 48, 80, "Open",            None, None),
            ("Office-WiFi",  "aa:bb:cc:33:44:13", -65, 36, 80, "WPA2 Enterprise", 22, True),
            ("Office-WiFi",  "aa:bb:cc:55:66:0b", -70, 48, 80, "WPA2 Enterprise", 12, False),
            ("guest-cafe",   "96:de:ad:be:ef:01", -75, 48, 20, "Open",            None, None),
            ("neighbour-2g", "f2:11:22:33:44:55", -78,  6, 20, "WPA2 Personal",   None, None),
        ]
        return [
            ScanResult(
                ssid=ssid or None, bssid=bssid, rssi_dbm=rssi,
                noise_dbm=-95, channel=ch, channel_width_mhz=width,
                channel_band="5 GHz" if ch >= 32 else "2.4 GHz",
                phy_mode=None, security=security, timestamp=ts,
                country_code="CN", bss_load_pct=load,
                supports_802_11r=ft,
            )
            for ssid, bssid, rssi, ch, width, security, load, ft in rows
        ]

    def permission_state(self) -> str:
        return "granted"


class _DisassociatedBackend(_GoodBackend):
    """User disconnected from any Wi-Fi network."""
    def get_connection(self) -> Connection:
        return None  # type: ignore[return-value]

    def scan(self) -> list[ScanResult]:
        return []


class _RedactedBackend(_GoodBackend):
    """Helper not granted / Location Services denied: scan rows
    have None SSID / BSSID like macOS 14.4+ produces."""
    def scan(self) -> list[ScanResult]:
        ts = datetime.now()
        return [
            ScanResult(
                ssid=None, bssid=None, rssi_dbm=-58 - i,
                noise_dbm=-95, channel=48, channel_width_mhz=80,
                channel_band="5 GHz", phy_mode=None,
                security="WPA2 Enterprise", timestamp=ts,
                country_code="CN", bss_load_pct=None,
                supports_802_11r=None,
            )
            for i in range(6)
        ]

    def permission_state(self) -> str:
        return "denied"


def _ble_devices_normal(now: datetime) -> list[BLEDevice]:
    """Healthy BLE population — most rows have a vendor, some have a
    device class, a couple have ``(unknown)`` to keep the inspector
    honest. The iBeacon and Eddystone-URL rows carry real raw bytes
    (manufacturer_hex / service_data) so the decoder framework can
    decode them in detail-modal regression captures."""
    def d(ident, *, name, vendor, vendor_id, services, rssi,
          ad_count=4, age_s=1, merged=1, type=None, device_class=None,
          manufacturer_hex=None, service_data=()):
        last = now - timedelta(seconds=age_s)
        return BLEDevice(
            identifier=ident, name=name, vendor=vendor, vendor_id=vendor_id,
            services=services, rssi_dbm=rssi, is_connectable=True,
            first_seen=last - timedelta(seconds=ad_count * 3),
            last_seen=last, ad_count=ad_count, merged_count=merged,
            type=type, device_class=device_class,
            manufacturer_hex=manufacturer_hex,
            service_data=service_data,
        )
    # Real iBeacon bytes: cid 0x004C + type 0x02 + length 0x15 + 16-byte
    # UUID "550e8400-e29b-41d4-a716-446655440000" + major=1 + minor=42
    # + tx_power -59 dBm.
    ibeacon_bytes = (
        "4c00" "0215"
        "550e8400e29b41d4a716446655440000"
        "0001" "002a" "c5"
    )
    # Real Eddystone-URL bytes for "https://example.com/": frame 0x10
    # + tx_power -21 dBm + scheme 0x03 (https://) + "example" + 0x00
    # (".com/" expansion).
    eddystone_url_bytes = "10eb03" + "example".encode().hex() + "00"
    return [
        d("aaaa1234-...01", name=None, vendor="Apple, Inc.", vendor_id=76,
          services=(), rssi=-44, ad_count=22, device_class="iPhone"),
        d("bbbb1234-...02", name="AirTag", vendor="Apple, Inc.", vendor_id=76,
          services=("FD5A",), rssi=-46, type="AirTag"),
        d("cccc1234-...03", name=None, vendor="Apple, Inc.", vendor_id=76,
          services=(), rssi=-52, type="iBeacon",
          manufacturer_hex=ibeacon_bytes),
        d("dddd1234-...04", name=None, vendor=None, vendor_id=None,
          services=("FEAA",), rssi=-58, type="Eddystone-URL",
          service_data=(("FEAA", eddystone_url_bytes),)),
        d("eeee1234-...05", name=None, vendor="Apple, Inc.", vendor_id=76,
          services=("FE9F",), rssi=-61, merged=3),
        d("ffff1234-...06", name="Mi Band 7", vendor="Xiaomi, Inc.", vendor_id=637,
          services=("180D",), rssi=-67),
        d("11111234-...07", name="Tile Mate", vendor="Tile, Inc.", vendor_id=323,
          services=("FEED",), rssi=-72, type="Tile"),
        d("22221234-...08", name=None, vendor=None, vendor_id=None,
          services=("FFE0",), rssi=-84),
    ]


def _ble_devices_unknown_heavy(now: datetime) -> list[BLEDevice]:
    """Worst-case BLE population: 10 devices, 7 with ``vendor=None``
    and ``name=None``. Stress test for the inspector's "could
    improve vendor coverage" finding."""
    def d(ident, *, name=None, vendor=None, services=(), rssi=-70):
        return BLEDevice(
            identifier=ident, name=name, vendor=vendor, vendor_id=None,
            services=services, rssi_dbm=rssi, is_connectable=False,
            first_seen=now - timedelta(seconds=30),
            last_seen=now - timedelta(seconds=2),
            ad_count=3, merged_count=1, type=None, device_class=None,
        )
    return [
        d(f"unknown-{i:02d}", rssi=-50 - i * 5)
        for i in range(7)
    ] + [
        d("known-iphone", vendor="Apple, Inc.", rssi=-45),
        d("known-tile", name="Tile Mate", vendor="Tile, Inc.",
          services=("FEED",), rssi=-65),
        d("known-mi", name="Mi Band 7", vendor="Xiaomi, Inc.",
          services=("180D",), rssi=-72),
    ]


def _ble_connected(now: datetime) -> list[BLEDevice]:
    return [
        BLEDevice(
            identifier="38-09-fb-0b-be-60", name="AirPods Pro",
            vendor="Apple, Inc.", vendor_id=None, services=("110A",),
            rssi_dbm=None, is_connectable=True, first_seen=now,
            last_seen=now, ad_count=0, is_connected=True,
        ),
        BLEDevice(
            identifier="8c-85-90-f1-d0-cd", name="Magic Keyboard",
            vendor="Apple, Inc.", vendor_id=None, services=("1812",),
            rssi_dbm=None, is_connectable=True, first_seen=now,
            last_seen=now, ad_count=0, is_connected=True,
        ),
    ]


# ---------- scenarios ----------

@dataclass(frozen=True)
class Scenario:
    """One TUI state to capture + check.

    ``setup`` builds the DitingApp. ``after_mount`` runs inside
    the pilot context after the app's first connection / scan have
    landed; this is where we inject synthetic BLE / events / link
    aggregates and drive any keystrokes that change the view.
    ``assertions`` is a list of ``(label, predicate)`` tuples
    against the captured SVG text; ``inspectors`` is a list of
    callables that receive the running app + captured text and
    yield :class:`Finding` items.
    """
    id: str
    description: str
    lang: str                          # 'en' | 'zh'
    setup: Callable[[], "Any"]         # returns DitingApp
    after_mount: Callable[..., Awaitable[None]] | None = None
    assertions: tuple[tuple[str, Callable[[str], bool]], ...] = ()
    inspectors: tuple[Callable[..., list["Finding"]], ...] = ()


@dataclass(frozen=True)
class Finding:
    """One observation from an inspector pass.

    ``severity`` is ``info`` | ``note`` | ``warn``. ``message`` is
    short; ``suggestion`` is the actionable line shown in the
    report.
    """
    severity: str
    message: str
    suggestion: str = ""


# ---------- inspectors ----------

def _inspect_ble_unknown_vendors(app: "Any", *_args) -> list[Finding]:
    """Count BLE rows lacking a resolved vendor. High ratio is the
    user's specific complaint about real-Mac scans."""
    devices = list(getattr(app, "_latest_ble", []) or [])
    if not devices:
        return []
    unknown = sum(1 for d in devices if not d.vendor)
    ratio = unknown / len(devices)
    if ratio >= 0.30:
        return [Finding(
            severity="warn",
            message=(
                f"{unknown}/{len(devices)} BLE rows have unknown vendor "
                f"({ratio:.0%}). Real-Mac scans tend to look like this "
                f"because the bundled OUI map is curated, not exhaustive."
            ),
            suggestion=(
                "Expand src/diting/data/wifi_ouis.json with more "
                "common consumer + Bluetooth-accessory OUIs, or fetch "
                "the full IEEE OUI registry into a parallel data file."
            ),
        )]
    if ratio >= 0.15:
        return [Finding(
            severity="note",
            message=(
                f"{unknown}/{len(devices)} BLE rows have unknown "
                f"vendor ({ratio:.0%}). Acceptable but improvable."
            ),
        )]
    return []


def _inspect_ble_no_name_no_type(app: "Any", *_args) -> list[Finding]:
    """Two-tier check on rows that lack a deep-ID label.

    * **Completely anonymous** — no vendor, no name, no type, no
      device_class. The user has only RSSI + a rotating MAC. No
      adversarial guess is possible from advertisement data
      alone; the only way to attach meaning is observation
      patterns (proximity-walk, time-of-day correlation) which
      diting doesn't do today.

    * **Vendor-only** — vendor resolved (e.g. "Apple, Inc.",
      "Microsoft", "Polar Electro Oy") but name / type /
      device_class all empty. The row is still informative — the
      user can at least tell "something Apple" — but the deep-ID
      gap suggests a missing protocol decoder. We surface it as
      a soft note, not a warning.

    Tightening from the original "any row with no name+type+
    devclass" version: that lumped the two tiers together, so
    "Apple, Inc. (unknown)" rows triggered the same warning as
    rows the user has zero signal on. After the audit's first
    pass — when the bulk of unlabelled Apple rows turned out to
    be Continuity 0x16, decoded in dbc2406 — the remaining gap
    is mostly vendor-only rows where the deep-ID would need
    per-vendor schema work. Splitting tiers makes the
    actionability honest.
    """
    from diting.ble import is_silent_device
    devices = list(getattr(app, "_latest_ble", []) or [])
    if not devices:
        return []
    # Three buckets, mutually exclusive:
    # - silent: zero broadcast info — physical limit, no fix possible
    # - unknown_with_data: had data but vendor lookup failed — actionable
    # - vendor_only: vendor resolved but no deep-ID label — decoder gap
    silent = [d for d in devices if is_silent_device(d)]
    unknown_with_data = [
        d for d in devices
        if not d.vendor and not is_silent_device(d)
    ]
    vendor_only = [
        d for d in devices
        if d.vendor and not d.name and not d.type and not d.device_class
    ]
    out: list[Finding] = []
    if len(silent) >= 3:
        out.append(Finding(
            severity="info",
            message=(
                f"{len(silent)} BLE rows are truly silent — broadcasts "
                f"carry no manufacturer_id, no service UUIDs, no name, "
                f"no type, no device_class. Only RSSI is available."
            ),
            suggestion=(
                "Nothing to derive from advertisement data. Possible "
                "future signal: pattern observation (proximity walk, "
                "time correlation), which diting does not do today."
            ),
        ))
    if len(unknown_with_data) >= 3:
        out.append(Finding(
            severity="warn",
            message=(
                f"{len(unknown_with_data)} BLE rows have broadcast data "
                f"(manufacturer_id / services / name / type / "
                f"device_class) but the vendor lookup chain abstained. "
                f"This bucket IS actionable."
            ),
            suggestion=(
                "Inspect what data each unresolved row carries. Common "
                "fixes: missing OUI in src/diting/data/wifi_ouis.json, "
                "missing 16-bit member UUID in bluetooth_member_uuids.json, "
                "missing name pattern in src/diting/ble.py "
                "_NAME_PATTERN_VENDORS, or missing 128-bit member UUID "
                "in _LONG_MEMBER_UUIDS."
            ),
        ))
    if len(vendor_only) >= 5:
        out.append(Finding(
            severity="note",
            message=(
                f"{len(vendor_only)} BLE rows have a known vendor but "
                f"no name / type / device_class — partial identity. "
                f"Decoder gap rather than missing data."
            ),
            suggestion=(
                "Add per-vendor manufacturer-data decoders for the "
                "long-tail company-ids that appear in this set "
                "(Polar Electro Oy / Bluegiga / Telink Semiconductor "
                "/ similar small-vendor schemas)."
            ),
        ))
    # Dense same-vendor anonymous cluster — many rows from one vendor,
    # all of them name-less. The user's question "are these the same
    # device?" generalises: when a vendor has 8+ name-less rows post-
    # merge, it's either (a) genuinely many physical devices of the
    # same kind nearby (Mi Bands in a CN tech office, AirPods Pro
    # cases in a coffee shop), or (b) one device whose RPA-rotation
    # outpaces the merge's RSSI cluster window. Either way it's
    # surface-worthy because the diagnostic line `Vendor N` reads
    # alarming without explaining post-merge accounting.
    from collections import Counter
    vendor_anonymous: Counter[str] = Counter()
    for d in devices:
        if d.vendor and not d.name and not d.type and not d.device_class:
            vendor_anonymous[d.vendor] += 1
    for vendor, count in vendor_anonymous.most_common(3):
        if count >= 8:
            out.append(Finding(
                severity="info",
                message=(
                    f"{count} post-merge rows under vendor {vendor!r} — "
                    f"all name-less. Either {count}+ physical devices "
                    f"of this kind in range (likely at high office "
                    f"density), or RPA-rotation slipping the merge's "
                    f"±10 dBm cluster window."
                ),
                suggestion=(
                    "Verify by re-capturing in a low-density "
                    "environment (home / weekend). If the count drops "
                    "to 1-3 it was real device density; if it stays "
                    "high there's a decoder opportunity to extract a "
                    "vendor-specific device ID from the manufacturer-"
                    "data body so merge_for_display can fold across "
                    "RSSI spreads."
                ),
            ))
    return out


def _inspect_redacted_scan(_app: "Any", text: str) -> list[Finding]:
    """If the captured SVG carries the redacted placeholder, the
    helper isn't doing its job — flag it loudly."""
    markers = ["(redacted)", "(已遮蔽)", "(redact"]
    if any(m in text for m in markers):
        return [Finding(
            severity="warn",
            message=(
                "Scan list shows redacted SSID / BSSID — the Swift "
                "helper bundle has not been granted Location Services."
            ),
            suggestion=(
                "Run `open helper/diting-tianer.app` once, click "
                "Allow on the macOS prompt, then relaunch diting."
            ),
        )]
    return []


def _inspect_environment_silent(app: "Any", *_args) -> list[Finding]:
    """The Diagnostics panel renders an Environment row even with
    no σ data; if we expected stir events but got none, surface."""
    monitor = getattr(app, "_environment_monitor", None)
    if monitor is None:
        return []  # disabled by scenario, not a finding
    history = sum(
        len(state.get("history", [])) for state in monitor._state.values()
    )
    if history == 0:
        return [Finding(
            severity="info",
            message=(
                "Environment monitor has no RSSI samples yet; stir "
                "events cannot fire until the rolling window fills."
            ),
        )]
    return []


# ---------- the registry ----------

def _regression_scenarios() -> list[Scenario]:
    """Synthetic-backend scenarios for TUI end-to-end regression.

    Each scenario pins a known input (fake backend / inventory /
    BLE roster / event ring) to a known output (assertion list +
    inspector findings). Deterministic — safe for CI / pre-commit
    via ``make test-system``. Defined as a function rather than a
    module-level list so the heavy ``DitingApp`` import inside
    each ``setup`` lambda is deferred until snapshot is actually
    invoked.
    """
    from diting.tui import DitingApp

    def _build_good(*, lang: str = "en") -> "Any":
        i18n.set_lang(lang)
        return DitingApp(
            _GoodBackend(), _INVENTORY,
            ble_helper_path="",
            enable_latency=False, enable_environment=False,
        )

    def _build_disassociated() -> "Any":
        i18n.set_lang("en")
        return DitingApp(
            _DisassociatedBackend(), _INVENTORY,
            ble_helper_path="",
            enable_latency=False, enable_environment=False,
        )

    def _build_redacted() -> "Any":
        i18n.set_lang("en")
        return DitingApp(
            _RedactedBackend(), _INVENTORY,
            ble_helper_path="",
            enable_latency=False, enable_environment=False,
        )

    async def _seed_link_and_events(pilot, ble_devices=None):
        """Common after-mount: inject link aggregates + a sample
        event so the events strip + diagnostics row aren't empty.

        The App's ``_refresh_environment_panel`` can fire at any
        moment after we paint and would otherwise call
        ``_link_diagnostic_tuple`` / ``_environment_diagnostic_tuple``
        — both of which return None when ``enable_latency=False``,
        wiping the Link / Environment rows we just seeded. Monkey-
        patch those two methods on the App instance so any later
        refresh re-renders with the seeded tuples.
        """
        from diting.tui import EnvironmentPanel, EventsPanel
        await pilot.pause(2.0)
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
        # Pin the seed values onto the App so any re-render path
        # picks them up — eliminates a flaky race where a stray
        # refresh wipes the diagnostics rows we just painted.
        pilot.app._link_diagnostic_tuple = lambda: link
        pilot.app._environment_diagnostic_tuple = lambda: env
        env_panel.update_environment(
            pilot.app._cached_scan, pilot.app._latest_connection,
            link=link, env=env,
        )
        events_panel = pilot.app.query_one("#roam", EventsPanel)
        events_panel.append_event(
            RFStirEvent(
                timestamp=datetime.now(),
                bssid="aa:bb:cc:11:22:53",
                location="1F-bedroom",
                magnitude_db=8.3, duration_s=12.0,
                confidence="high", mode="co_located",
            ),
            _INVENTORY,
        )
        if ble_devices is not None:
            pilot.app._latest_ble = ble_devices
            pilot.app._latest_ble_connected = _ble_connected(datetime.now())
            pilot.app._ble_permission_state = "granted"
            from diting.tui import BLEPanel
            ble_panel = pilot.app.query_one(BLEPanel)
            ble_panel.update_devices(
                ble_devices, _ble_connected(datetime.now()), "granted",
            )
        await pilot.pause(0.3)

    async def _switch_to_ble(pilot, *, ble_devices):
        await _seed_link_and_events(pilot, ble_devices=ble_devices)
        await pilot.press("n")
        await pilot.pause(0.3)

    async def _switch_to_ble_and_inspect(pilot, *, ble_devices, steps: int):
        """Switch to BLE view, push the cursor down ``steps`` times,
        then open the detail modal. Used by the regression scenario
        that exercises the decoder framework — the cursor needs to
        land on a row whose payload one of the registered decoders
        will recognise (typically the iBeacon row in
        ``_ble_devices_normal``)."""
        await _switch_to_ble(pilot, ble_devices=ble_devices)
        for _ in range(steps):
            await pilot.press("down")
            await pilot.pause(0.02)
        await pilot.press("i")
        await pilot.pause(0.3)

    async def _open_events_modal(pilot):
        await _seed_link_and_events(pilot)
        # Inject a richer event mix into the ring before opening.
        from diting.tui import EventsPanel
        events_panel = pilot.app.query_one("#roam", EventsPanel)
        now = datetime.now()
        for ev in (
            RoamEvent(
                timestamp=now,
                previous_bssid="aa:bb:cc:33:44:13", previous_channel=36,
                new_bssid="aa:bb:cc:11:22:53", new_channel=48,
            ),
            LatencySpikeEvent(
                timestamp=now, target="router",
                target_ip="192.168.1.1", rtt_ms=412.0, loss_pct=25.0,
            ),
            LossBurstEvent(
                timestamp=now, target="wan", target_ip="1.1.1.1",
                loss_pct=80.0, lost_in_window=4,
            ),
        ):
            events_panel.append_event(ev, _INVENTORY)
        await pilot.press("m")
        await pilot.pause(0.3)

    async def _open_help(pilot):
        await _seed_link_and_events(pilot)
        # Help screen rebound from `h` to `?` in PR #90; Textual's
        # named key for `?` is `question_mark`.
        await pilot.press("question_mark")
        await pilot.pause(0.3)

    async def _open_basics(pilot):
        await _seed_link_and_events(pilot)
        await pilot.press("b")
        await pilot.pause(0.3)

    async def _pause_polling(pilot):
        await _seed_link_and_events(pilot)
        await pilot.press("p")
        await pilot.pause(0.3)

    async def _open_wifi_detail(pilot):
        """Open WifiDetailScreen on the currently-associated AP.

        Default-row inspect (no prior up/down) lands on the first row,
        which under the AP-grouped sort is the user's own AP — exactly
        the row whose detail modal is the most common reader path.
        """
        await _seed_link_and_events(pilot)
        await pilot.press("i")
        await pilot.pause(0.3)

    async def _switch_to_bonjour_by_host(pilot):
        """Cycle to Bonjour view, inject a `multi-service-per-host`
        snapshot, then press `s` to flip from the default `service`
        sort to `by-host`. Locks the folded-services rendering under
        regression."""
        from datetime import datetime, timezone
        from diting.mdns import BonjourDevice
        await _seed_link_and_events(pilot)
        await pilot.press("n")  # wifi → ble
        await pilot.pause(0.1)
        await pilot.press("n")  # ble → mdns
        await pilot.pause(0.2)
        now = datetime.now(timezone.utc)
        # One HomePod host announcing four services so the by-host
        # row's services column carries the folded list.
        devices = [
            BonjourDevice(
                service_type="_airplay._tcp.local.",
                name="Blue Pod._airplay._tcp.local.",
                host="Blue-Pod.local.", port=7000,
                addresses=("192.168.1.42",), txt={},
                vendor="Apple, Inc.", category="AirPlay",
                first_seen=now, last_seen=now,
            ),
            BonjourDevice(
                service_type="_raop._tcp.local.",
                name="MAC@Blue Pod._raop._tcp.local.",
                host="Blue-Pod.local.", port=7000,
                addresses=("192.168.1.42",), txt={},
                vendor="Apple, Inc.", category="AirPlay audio",
                first_seen=now, last_seen=now,
            ),
            BonjourDevice(
                service_type="_companion-link._tcp.local.",
                name="Blue Pod._companion-link._tcp.local.",
                host="Blue-Pod.local.", port=49152,
                addresses=("192.168.1.42",), txt={},
                vendor="Apple, Inc.", category="Apple Companion",
                first_seen=now, last_seen=now,
            ),
            BonjourDevice(
                service_type="_hap._tcp.local.",
                name="Blue Pod._hap._tcp.local.",
                host="Blue-Pod.local.", port=49152,
                addresses=("192.168.1.42",), txt={},
                vendor="Apple, Inc.", category="HomeKit",
                first_seen=now, last_seen=now,
            ),
            BonjourDevice(
                service_type="_http._tcp.local.",
                name="FriendlyWrt._http._tcp.local.",
                host="FriendlyWrt.local.", port=80,
                addresses=("192.168.1.1",), txt={},
                vendor=None, category="HTTP",
                first_seen=now, last_seen=now,
            ),
        ]
        pilot.app._latest_mdns = devices
        pilot.app._refresh_mdns_panel()
        await pilot.pause(0.2)
        # Flip to by-host mode.
        await pilot.press("s")
        await pilot.pause(0.2)

    async def _switch_to_lan_inventory(pilot):
        """Cycle to LAN view (4 `n` presses from wifi: wifi → ble →
        mdns → lan), then inject a synthetic ``LANInventoryUpdate``
        with five hosts covering self, gateway, Bonjour-named,
        random-MAC, and unknown-vendor cases."""
        from datetime import datetime, timezone
        from diting.lan import LANHost, LANInventoryUpdate
        await _seed_link_and_events(pilot)
        await pilot.press("n")  # wifi → ble
        await pilot.pause(0.1)
        await pilot.press("n")  # ble → mdns
        await pilot.pause(0.1)
        await pilot.press("n")  # mdns → lan
        await pilot.pause(0.2)
        now = datetime.now(timezone.utc)
        hosts = (
            LANHost(
                mac="84:2f:57:9b:15:59",
                ip="192.168.1.20",
                vendor="Apple, Inc.",
                hostname=None,
                bonjour_name=None,
                bonjour_services=(),
                first_seen=now,
                last_seen=now,
                is_gateway=False,
                is_self=True,
                is_randomised_mac=False,
            ),
            LANHost(
                mac="aa:bb:cc:11:22:33",
                ip="192.168.1.1",
                vendor="TP-Link Tech.",
                hostname="router.local",
                bonjour_name=None,
                bonjour_services=(),
                first_seen=now,
                last_seen=now,
                is_gateway=True,
                is_self=False,
                is_randomised_mac=False,
                last_rtt_ms=1.8,
                last_reachable_at=now,
            ),
            LANHost(
                mac="de:ad:be:ef:00:01",
                ip="192.168.1.42",
                vendor="Apple, Inc.",
                hostname=None,
                bonjour_name="ccy-MBP24-M4-Office",
                bonjour_services=("AirPlay", "AirPlay audio", "Apple Companion"),
                first_seen=now,
                last_seen=now,
                is_gateway=False,
                is_self=False,
                is_randomised_mac=False,
            ),
            LANHost(
                mac="f4:5c:89:11:22:33",
                ip="192.168.1.55",
                vendor=None,
                hostname=None,
                bonjour_name=None,
                bonjour_services=(),
                first_seen=now,
                last_seen=now,
                is_gateway=False,
                is_self=False,
                is_randomised_mac=False,
            ),
            LANHost(
                mac="02:11:22:33:44:55",
                ip="192.168.1.81",
                vendor=None,
                hostname=None,
                bonjour_name=None,
                bonjour_services=(),
                first_seen=now,
                last_seen=now,
                is_gateway=False,
                is_self=False,
                is_randomised_mac=True,
            ),
        )
        update = LANInventoryUpdate(
            hosts=hosts,
            subnet="192.168.1.0/24",
            subnet_capped=False,
            cap_prefix=24,
            last_sweep_at=now,
            next_sweep_at=now,
        )
        pilot.app._latest_lan = update
        pilot.app._refresh_lan_panel()
        await pilot.pause(0.2)

    async def _open_lan_detail(pilot):
        """Cycle to LAN view, inject the synthetic 5-host snapshot,
        then walk the cursor to the gateway row and press `i`.

        Walking takes two presses: `down` from no-selection lands on
        row 0 (self); a second `down` advances to row 1 (gateway).
        That's the row with the seeded `last_rtt_ms=1.8`."""
        await _switch_to_lan_inventory(pilot)
        await pilot.press("down")
        await pilot.pause(0.05)
        await pilot.press("down")
        await pilot.pause(0.05)
        await pilot.press("i")
        await pilot.pause(0.3)

    async def _open_bonjour_detail(pilot):
        """Cycle to Bonjour view, inject a few representative
        services, then open the detail modal on the first row."""
        from datetime import datetime, timezone
        from diting.mdns import BonjourDevice
        from diting.tui import BonjourPanel
        await _seed_link_and_events(pilot)
        await pilot.press("n")  # wifi → ble
        await pilot.pause(0.1)
        await pilot.press("n")  # ble → mdns
        await pilot.pause(0.2)
        now = datetime.now(timezone.utc)
        # An AirPlay receiver with a long TXT value to exercise the
        # folding path the modal advertises in its design.
        devices = [
            BonjourDevice(
                service_type="_raop._tcp.local.",
                name="LivingRoom-HomePod._raop._tcp.local.",
                host="LivingRoom-HomePod.local.",
                port=7000,
                addresses=("192.168.1.42", "fe80::1"),
                txt={
                    "md": "AppleTV5,3",
                    "am": "AppleTV5,3",
                    "pk": "a" * 200,  # > 60 chars → folded
                },
                vendor="Apple, Inc.",
                category="AirPlay audio",
                first_seen=now,
                last_seen=now,
            ),
            BonjourDevice(
                service_type="_googlecast._tcp.local.",
                name="Office Display._googlecast._tcp.local.",
                host="office-display.local.",
                port=8009,
                addresses=("192.168.1.55",),
                txt={"id": "abc123", "md": "Chromecast"},
                vendor="Google",
                category="Chromecast",
                first_seen=now,
                last_seen=now,
            ),
        ]
        pilot.app._latest_mdns = devices
        pilot.app._refresh_mdns_panel()
        await pilot.pause(0.2)
        await pilot.press("i")
        await pilot.pause(0.3)

    return [
        Scenario(
            id="wifi_main_en",
            description="Connected, scan list populated, English UI.",
            lang="en",
            setup=lambda: _build_good(lang="en"),
            after_mount=_seed_link_and_events,
            assertions=(
                ("AP name visible", lambda t: "1F-bedroom" in t),
                ("Diagnostics row", lambda t: "Link" in t and "Environment" in t),
                ("Events panel header", lambda t: "Events" in t),
            ),
            inspectors=(
                _inspect_environment_silent,
            ),
        ),
        Scenario(
            id="wifi_main_zh",
            description="Connected, scan list populated, Chinese UI.",
            lang="zh",
            setup=lambda: _build_good(lang="zh"),
            after_mount=_seed_link_and_events,
            assertions=(
                ("Connection panel CN", lambda t: "连接" in t),
                ("Link row CN", lambda t: "链路" in t),
                ("Events panel CN", lambda t: "事件" in t),
            ),
            inspectors=(),
        ),
        Scenario(
            id="wifi_disassociated",
            description="No active Wi-Fi connection.",
            lang="en",
            setup=_build_disassociated,
            after_mount=None,
            assertions=(
                ("not associated label", lambda t: "(not associated)" in t),
            ),
            inspectors=(),
        ),
        Scenario(
            id="wifi_redacted",
            description="Helper not granted; SSID/BSSID redacted.",
            lang="en",
            setup=_build_redacted,
            after_mount=_seed_link_and_events,
            assertions=(),
            inspectors=(_inspect_redacted_scan,),
        ),
        Scenario(
            id="ble_normal",
            description="BLE view with a healthy device population.",
            lang="en",
            setup=lambda: _build_good(lang="en"),
            after_mount=lambda pilot: _switch_to_ble(
                pilot, ble_devices=_ble_devices_normal(datetime.now()),
            ),
            assertions=(
                ("BLE panel header", lambda t: "Nearby BLE" in t or "BLE" in t),
                ("AirTag visible", lambda t: "AirTag" in t),
            ),
            inspectors=(
                _inspect_ble_unknown_vendors,
                _inspect_ble_no_name_no_type,
            ),
        ),
        Scenario(
            id="ble_detail_decoded",
            description="BLE detail modal with iBeacon decoder firing.",
            lang="en",
            # The iBeacon row is the 3rd advertising entry in
            # _ble_devices_normal. With 2 connected peripherals
            # seeded by _ble_connected the cursor reaches the iBeacon
            # at the 5th `down` press: 2 through Connected, then 3
            # advertising rows (iPhone Nearby Info, AirTag, iBeacon).
            setup=lambda: _build_good(lang="en"),
            after_mount=lambda pilot: _switch_to_ble_and_inspect(
                pilot,
                ble_devices=_ble_devices_normal(datetime.now()),
                steps=5,
            ),
            assertions=(
                ("Decoded section header", lambda t: "Decoded payload" in t),
                ("iBeacon UUID rendered",
                 lambda t: "550e8400-e29b-41d4" in t),
                ("iBeacon major+minor",
                 lambda t: "major" in t and "minor" in t),
            ),
            inspectors=(),
        ),
        Scenario(
            id="wifi_detail_modal",
            description="Wi-Fi detail modal on the associated AP.",
            lang="en",
            setup=lambda: _build_good(lang="en"),
            after_mount=_open_wifi_detail,
            assertions=(
                ("Identity section header", lambda t: "Identity" in t),
                ("Radio section header", lambda t: "Radio" in t),
                ("Signal section header", lambda t: "Signal" in t),
                ("Activity section header", lambda t: "Activity" in t),
                ("Associated annotation",
                 lambda t: "associated" in t.lower()),
                ("AP name from inventory",
                 lambda t: "1F-bedroom" in t),
                ("Close hint visible", lambda t: "Esc" in t),
            ),
            inspectors=(),
        ),
        Scenario(
            id="bonjour_by_host_mode",
            description="Bonjour panel in `by-host` sort: one row per "
                        "host, services folded.",
            lang="en",
            setup=lambda: _build_good(lang="en"),
            after_mount=_switch_to_bonjour_by_host,
            assertions=(
                ("Subtitle reflects by-host sort",
                 lambda t: "sort: by-host" in t),
                ("Blue Pod row appears",
                 lambda t: "Blue-Pod" in t),
                ("Folded services join with comma",
                 lambda t: "AirPlay" in t and "," in t),
                ("Unknown-vendor row uses (unknown)",
                 lambda t: "(unknown)" in t),
            ),
            inspectors=(),
        ),
        Scenario(
            id="bonjour_detail_modal",
            description="Bonjour detail modal on an AirPlay receiver.",
            lang="en",
            setup=lambda: _build_good(lang="en"),
            after_mount=_open_bonjour_detail,
            assertions=(
                ("Identity section header", lambda t: "Identity" in t),
                ("Network section header", lambda t: "Network" in t),
                ("TXT records section header",
                 lambda t: "TXT records" in t),
                ("Activity section header", lambda t: "Activity" in t),
                ("Long TXT folded to payload placeholder",
                 lambda t: "200-byte payload" in t),
                ("Close hint visible", lambda t: "Esc" in t),
            ),
            inspectors=(),
        ),
        Scenario(
            id="lan_view",
            description="LAN inventory view, synthetic 5-host snapshot.",
            lang="en",
            setup=lambda: _build_good(lang="en"),
            after_mount=_switch_to_lan_inventory,
            assertions=(
                ("LAN tab is active",
                 lambda t: "LAN" in t),
                ("Self row pinned with star + label",
                 lambda t: "this Mac" in t and "★" in t),
                ("Gateway row labelled",
                 lambda t: "gateway" in t),
                ("Bonjour-named row carries friendly name",
                 lambda t: "ccy-MBP24-M4-Office" in t),
                ("Random MAC marked",
                 lambda t: "(random MAC)" in t),
                ("Diagnostics line carries host count",
                 lambda t: "LAN inventory" in t and "5 hosts" in t),
                ("Subnet line present",
                 lambda t: "192.168.1.0/24" in t),
            ),
            inspectors=(),
        ),
        Scenario(
            id="lan_detail_modal",
            description=(
                "LANDetailScreen modal on the gateway row — pins the "
                "Latency / Reachable / Bonjour-empty-state contract."
            ),
            lang="en",
            setup=lambda: _build_good(lang="en"),
            after_mount=_open_lan_detail,
            assertions=(
                ("Identity section header",
                 lambda t: "Identity" in t),
                ("Network section header",
                 lambda t: "Network" in t),
                ("Bonjour services section header",
                 lambda t: "Bonjour services" in t),
                ("Activity section header",
                 lambda t: "Activity" in t),
                ("Latency row rendered with the seeded RTT",
                 lambda t: "Latency" in t and "1.8 ms" in t),
                ("Reachable row rendered (this sweep or relative)",
                 lambda t: "Reachable" in t),
                ("Gateway has no Bonjour services — placeholder visible",
                 lambda t: "(no Bonjour services)" in t),
                ("Close hint visible",
                 lambda t: "Esc" in t),
            ),
            inspectors=(),
        ),
        Scenario(
            id="ble_unknown_heavy",
            description="BLE view stress test — most rows lack vendor.",
            lang="en",
            setup=lambda: _build_good(lang="en"),
            after_mount=lambda pilot: _switch_to_ble(
                pilot, ble_devices=_ble_devices_unknown_heavy(datetime.now()),
            ),
            assertions=(),
            inspectors=(
                _inspect_ble_unknown_vendors,
                _inspect_ble_no_name_no_type,
            ),
        ),
        Scenario(
            id="events_modal",
            description="Events modal with one of every event type.",
            lang="en",
            setup=lambda: _build_good(lang="en"),
            after_mount=_open_events_modal,
            assertions=(
                ("filter hint visible",
                 lambda t: "filter" in t.lower() or "Esc" in t),
            ),
            inspectors=(),
        ),
        Scenario(
            id="help_modal",
            description="Help modal at the top of its scroll.",
            lang="en",
            setup=lambda: _build_good(lang="en"),
            after_mount=_open_help,
            assertions=(
                # Top-of-scroll content. "Subcommands" is several
                # screens down — only PgDn scenarios should assert on it.
                ("Panels section heading", lambda t: "Panels" in t),
                ("Bindings section heading", lambda t: "Bindings" in t),
            ),
            inspectors=(),
        ),
        Scenario(
            id="basics_modal",
            description="Basics / glossary modal.",
            lang="en",
            setup=lambda: _build_good(lang="en"),
            after_mount=_open_basics,
            assertions=(
                ("Wi-Fi section", lambda t: "SSID" in t),
            ),
            inspectors=(),
        ),
        Scenario(
            id="paused_polling",
            description="User pressed `p` — polling paused.",
            lang="en",
            setup=lambda: _build_good(lang="en"),
            after_mount=_pause_polling,
            assertions=(),
            inspectors=(),
        ),
    ]


# ---------- runner ----------


def _prefer_installed_helper_for_audit() -> None:
    """For /tui-audit explore mode, pin DITING_HELPER to the installed
    bundle when one is present.

    Why: ``_helper.find_helper()`` prefers ``<repo>/helper/diting-
    tianer.app`` (so a contributor's local rebuild wins over a stale
    /Applications drop). That preference is correct for normal
    development, but for an audit run it bites: the repo-local bundle
    has a different cdhash from the released one the user has
    actually granted Location + Bluetooth to, so ``locationd`` fires
    a fresh permission prompt on every scan tick.

    Honour an explicit ``DITING_HELPER`` override the user already
    set; only pin when the env var is empty AND the installer's drop
    exists at the canonical ``~/Library/Application Support/diting/``
    path.
    """
    if os.environ.get("DITING_HELPER"):
        return
    installed = Path(
        "~/Library/Application Support/diting/diting-tianer.app"
    ).expanduser()
    if installed.is_dir():
        os.environ["DITING_HELPER"] = str(installed)


def _explore_scenarios() -> list[Scenario]:
    """Real-backend scenarios for `/tui-audit` exploration runs.

    Built on top of ``MacOSWiFiBackend`` + the live BLE helper:
    each scenario captures a view of the user's *actual* network
    and BLE environment as it exists right now. No synthetic
    injection — what shows up is what the user would see if they
    launched ``diting`` themselves.

    Suitable scenarios are limited to keystroke-driven view /
    modal switches: we cannot fabricate "disassociated" or
    "redacted" or "BLE unknown heavy" against a live machine, so
    those live only in the regression list above. The inspector
    rules still run against the live data, which is where the
    user-actionable findings come from.

    Output dirs default to a timestamped path under ``/tmp/`` —
    the captured SVG / PNG carry the user's real SSIDs / BSSIDs
    / device names and have no place in source control.
    """
    from diting import _helper
    from diting.macos_backend import MacOSWiFiBackend
    from diting.network import load_inventory
    from diting.tui import DitingApp

    _prefer_installed_helper_for_audit()
    helper_path = _helper.find_helper() or ""

    def _build_live() -> "Any":
        # Honour DITING_LANG / locale so an audit run can target
        # the Chinese UI by setting DITING_LANG=zh; the regression
        # scenarios above pin lang explicitly via set_lang, so without
        # this call the explore mode would silently inherit whatever
        # the last regression run left _lang at.
        i18n.set_lang(i18n.detect_default_lang())
        backend = MacOSWiFiBackend()
        inv = load_inventory()
        return DitingApp(
            backend, inv,
            ble_helper_path=helper_path,
            enable_latency=True,
            enable_environment=True,
        )

    async def _settle_main(pilot):
        # Real Wi-Fi scan takes ~5–7 s on CoreWLAN; latency probe
        # needs a couple of pings to populate medians; BLE first
        # snapshot lands ~10 s in. 15 s gives every diagnostic row
        # something real to show.
        await pilot.pause(15.0)

    async def _switch_to_ble(pilot):
        await pilot.pause(15.0)
        await pilot.press("n")
        # BLE snapshots refresh every 2 s by default; one extra
        # interval makes the panel non-empty on a normal day.
        await pilot.pause(8.0)

    async def _open_events_modal(pilot):
        await pilot.pause(15.0)
        await pilot.press("m")
        await pilot.pause(0.5)

    async def _open_help(pilot):
        await pilot.pause(5.0)
        # Help screen rebound from `h` to `?` in PR #90; Textual's
        # named key for `?` is `question_mark`.
        await pilot.press("question_mark")
        await pilot.pause(0.3)

    async def _open_basics(pilot):
        await pilot.pause(5.0)
        await pilot.press("b")
        await pilot.pause(0.3)

    async def _switch_to_mdns(pilot):
        # Cycle wifi → ble → mdns. The poller is lazy-instantiated on
        # the third press; pause to let zeroconf collect announces
        # from the local link before capture. mDNS announce intervals
        # are typically 1-15 s; 20 s on a typical floor catches
        # several rounds of AirPlay / Bonjour / printer announces.
        await pilot.pause(3.0)
        await pilot.press("n")  # wifi → ble
        await pilot.pause(0.3)
        await pilot.press("n")  # ble → mdns
        await pilot.pause(20.0)  # let Bonjour announces accumulate

    async def _switch_to_lan_inventory(pilot):
        # Cycle wifi → ble → mdns → lan. Wait the first ICMP sweep
        # window (default cadence ~60 s, but the first tick fires
        # immediately on lazy-construction). A healthy /24 sweep at
        # 30-way concurrency completes in ~3-10 s; wait 20 s so a
        # quiet network has time to surface stragglers.
        await pilot.pause(3.0)
        await pilot.press("n")  # wifi → ble
        await pilot.pause(0.3)
        await pilot.press("n")  # ble → mdns
        await pilot.pause(0.3)
        await pilot.press("n")  # mdns → lan
        await pilot.pause(20.0)

    async def _pause_polling(pilot):
        await pilot.pause(15.0)
        await pilot.press("p")
        await pilot.pause(0.5)

    async def _open_lan_detail(pilot):
        """Live LAN detail modal. Cycle to LAN, give the sweep time
        to populate, advance to the gateway row, then press `i`."""
        await _switch_to_lan_inventory(pilot)
        # `down` twice from no-selection lands on row 1 (gateway —
        # self is row 0 because is_self pins it). `i` opens detail.
        await pilot.press("down")
        await pilot.pause(0.05)
        await pilot.press("down")
        await pilot.pause(0.05)
        await pilot.press("i")
        await pilot.pause(0.5)

    async def _open_ble_detail(pilot):
        # Switch to BLE first, let the list populate, then push the
        # cursor past the Connected section (typically 2-3 paired
        # peripherals on a normal Mac) and a few rows into Advertising
        # so the detail modal lands on a row that actually has
        # manufacturer_hex and (with luck) service_data — the
        # interesting raw-byte sections. Specifically aim past the
        # Apple-heavy top of the list (typical office: ~10 Apple
        # rows) so we land on a Microsoft / Mi Band / etc. row where
        # the lesser-tested decoders also fire.
        await pilot.pause(15.0)
        await pilot.press("n")
        await pilot.pause(8.0)
        for _ in range(20):
            await pilot.press("down")
            await pilot.pause(0.05)
        await pilot.press("i")
        await pilot.pause(0.4)

    return [
        Scenario(
            id="live_main",
            description="Live Wi-Fi main view (real backend).",
            lang="auto",
            setup=_build_live,
            after_mount=_settle_main,
            assertions=(),  # No fixed assertions — this is exploration, not regression.
            inspectors=(_inspect_redacted_scan,),
        ),
        Scenario(
            id="live_ble",
            description="Live BLE view (real helper, real devices).",
            lang="auto",
            setup=_build_live,
            after_mount=_switch_to_ble,
            assertions=(),
            inspectors=(
                _inspect_ble_unknown_vendors,
                _inspect_ble_no_name_no_type,
            ),
        ),
        Scenario(
            id="live_events_modal",
            description="Live events modal (whatever fired this session).",
            lang="auto",
            setup=_build_live,
            after_mount=_open_events_modal,
            assertions=(),
            inspectors=(),
        ),
        Scenario(
            id="live_help",
            description="Help modal opened against the live session.",
            lang="auto",
            setup=_build_live,
            after_mount=_open_help,
            assertions=(),
            inspectors=(),
        ),
        Scenario(
            id="live_basics",
            description="Basics / glossary modal opened against the live session.",
            lang="auto",
            setup=_build_live,
            after_mount=_open_basics,
            assertions=(),
            inspectors=(),
        ),
        Scenario(
            id="live_ble_detail",
            description="BLE detail modal (live device under cursor).",
            lang="auto",
            setup=_build_live,
            after_mount=_open_ble_detail,
            assertions=(),
            inspectors=(),
        ),
        Scenario(
            id="live_paused",
            description="Live state with polling paused (`p`).",
            lang="auto",
            setup=_build_live,
            after_mount=_pause_polling,
            assertions=(),
            inspectors=(),
        ),
        Scenario(
            id="live_mdns",
            description="Live mDNS / Bonjour view (passive announce-listen).",
            lang="auto",
            setup=_build_live,
            after_mount=_switch_to_mdns,
            assertions=(),
            inspectors=(),
        ),
        Scenario(
            id="live_lan",
            description="Live LAN inventory view (ARP + ICMP sweep).",
            lang="auto",
            setup=_build_live,
            after_mount=_switch_to_lan_inventory,
            assertions=(),
            inspectors=(),
        ),
        Scenario(
            id="live_lan_detail",
            description="Live LAN detail modal on the gateway row.",
            lang="auto",
            setup=_build_live,
            after_mount=_open_lan_detail,
            assertions=(),
            inspectors=(),
        ),
    ]


async def _capture_one(scenario: Scenario, out_dir: Path) -> dict:
    """Run one scenario end-to-end, return its report row."""
    app = scenario.setup()
    svg_path = out_dir / f"{scenario.id}.svg"
    text_for_assertions = ""
    findings: list[Finding] = []

    async with app.run_test(size=(160, 60)) as pilot:
        if scenario.after_mount is not None:
            await scenario.after_mount(pilot)
        else:
            await pilot.pause(2.0)
        out = pilot.app.export_screenshot(title=f"diting · {scenario.id}")
        out = _fix_cjk_textlength(out)
        svg_path.write_text(out)
        text_for_assertions = _extract_text(out)
        # Run inspectors with the live pilot.app and the captured
        # text so each can choose which surface to look at.
        for ins in scenario.inspectors:
            findings.extend(ins(pilot.app, text_for_assertions))

    # Run assertions.
    assertion_rows: list[dict] = []
    for label, predicate in scenario.assertions:
        passed = bool(predicate(text_for_assertions))
        assertion_rows.append({"label": label, "passed": passed})

    # Best-effort PNG render for human inspection.
    png_path = _maybe_render_png(svg_path)

    return {
        "id": scenario.id,
        "description": scenario.description,
        "lang": scenario.lang,
        "svg": str(svg_path),
        "png": str(png_path) if png_path else None,
        "assertions": assertion_rows,
        "findings": [
            {
                "severity": f.severity,
                "message": f.message,
                "suggestion": f.suggestion,
            }
            for f in findings
        ],
    }


def _maybe_render_png(svg_path: Path) -> Path | None:
    """Render SVG → PNG using whichever local tool is available.
    macOS `qlmanage` is preferred; falls back to `rsvg-convert`,
    then gives up silently."""
    target_dir = svg_path.parent
    if shutil.which("qlmanage"):
        try:
            subprocess.run(
                ["qlmanage", "-t", "-s", "1600", "-o", str(target_dir),
                 str(svg_path)],
                check=False, capture_output=True, timeout=30,
            )
            generated = target_dir / f"{svg_path.name}.png"
            if generated.is_file():
                final = svg_path.with_suffix(".png")
                generated.replace(final)
                return final
        except (subprocess.SubprocessError, OSError):
            pass
    if shutil.which("rsvg-convert"):
        try:
            png_path = svg_path.with_suffix(".png")
            subprocess.run(
                ["rsvg-convert", "-w", "1600", str(svg_path),
                 "-o", str(png_path)],
                check=False, capture_output=True, timeout=30,
            )
            if png_path.is_file():
                return png_path
        except (subprocess.SubprocessError, OSError):
            pass
    return None


# Mirror of docs/_capture_preview.py:_fix_cjk_textlength — Textual
# writes textLength using len(body) (code-point count), which
# compresses CJK glyphs to half their natural width. We rewrite
# textLength to cell_len(body) * cell_width so wide glyphs render
# correctly. Cell width 12.2 px is Textual's SVG default; verified
# in the preview captures committed under docs/.
_SVG_TEXT_RX = re.compile(
    r'(<text[^>]*\btextLength=")([0-9.]+)("[^>]*>)([^<]*)(</text>)'
)


def _fix_cjk_textlength(svg: str, cell_width_px: float = 12.2) -> str:
    import html
    from rich.cells import cell_len

    def _rewrite(match: re.Match) -> str:
        prefix, _old_len, mid, body, suffix = match.groups()
        decoded = html.unescape(body)
        new_len = cell_len(decoded) * cell_width_px
        return f"{prefix}{new_len:g}{mid}{body}{suffix}"

    return _SVG_TEXT_RX.sub(_rewrite, svg)


def _extract_text(svg: str) -> str:
    """Concatenate every ``<text>...</text>`` body. Used for both
    assertion predicates and the redacted-scan inspector."""
    parts = re.findall(r'>([^<>]+)<', svg)
    return " ".join(p.replace("&#160;", " ") for p in parts)


_MODES = ("regression", "explore")


async def run_async(
    out_dir: Path,
    *,
    mode: str = "regression",
    scenario_ids: list[str] | None = None,
) -> dict:
    """Run scenarios (or a subset by id), return the report dict.

    ``mode`` selects the scenario list:

    * ``regression`` — synthetic backends, deterministic input/
      output, suitable for CI / ``make test-system``.
    * ``explore`` — real ``MacOSWiFiBackend`` + live BLE helper,
      captures the user's actual environment for ``/tui-audit``
      and other audit work.

    Caller decides what to do with the returned dict (print,
    write to JSON, pipe through a CI gate, …).
    """
    if mode not in _MODES:
        raise ValueError(f"mode must be one of {_MODES!r}, got {mode!r}")
    out_dir.mkdir(parents=True, exist_ok=True)
    scenarios = (
        _regression_scenarios() if mode == "regression"
        else _explore_scenarios()
    )
    if scenario_ids:
        scenarios = [s for s in scenarios if s.id in set(scenario_ids)]
    rows: list[dict] = []
    for s in scenarios:
        rows.append(await _capture_one(s, out_dir))
    summary = {
        "mode": mode,
        "total": len(rows),
        "asserts_passed": sum(
            1 for r in rows for a in r["assertions"] if a["passed"]
        ),
        "asserts_failed": sum(
            1 for r in rows for a in r["assertions"] if not a["passed"]
        ),
        "findings": sum(len(r["findings"]) for r in rows),
    }
    return {
        "ts": datetime.now(timezone.utc).astimezone().isoformat(),
        "mode": mode,
        "out_dir": str(out_dir),
        "summary": summary,
        "scenarios": rows,
    }


def run(
    out_dir: Path,
    *,
    mode: str = "regression",
    scenario_ids: list[str] | None = None,
) -> dict:
    """Sync wrapper around :func:`run_async`."""
    return asyncio.run(
        run_async(out_dir, mode=mode, scenario_ids=scenario_ids),
    )


def default_out_dir(mode: str) -> Path:
    """Mode-aware default output directory.

    Regression runs go under ``./snapshot-output/`` (cwd-relative,
    deterministic, gitignored — fine to overwrite). Explore runs
    go under ``/tmp/wfs-tui-audit-YYYYMMDD-HHMMSS/`` so multiple
    sessions don't clobber each other and so the captured live
    data — which contains the user's real SSIDs / BSSIDs / device
    names — stays on a path no shell completion or Git operation
    is going to surface accidentally.
    """
    if mode == "explore":
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        return Path(f"/tmp/wfs-tui-audit-{stamp}")
    return Path("snapshot-output")


def render_console(report: dict) -> str:
    """Format the report for stdout — short, action-oriented."""
    lines: list[str] = []
    mode = report.get("mode", "regression")
    lines.append(f"diting snapshot [{mode}] — {report['ts']}")
    lines.append(f"output: {report['out_dir']}")
    s = report["summary"]
    lines.append(
        f"scenarios: {s['total']}  ·  "
        f"asserts: {s['asserts_passed']} passed / "
        f"{s['asserts_failed']} failed  ·  "
        f"findings: {s['findings']}"
    )
    lines.append("=" * 60)
    for row in report["scenarios"]:
        marker = "✓" if all(a["passed"] for a in row["assertions"]) else "✗"
        lines.append(f"{marker} {row['id']:<22} {row['description']}")
        for a in row["assertions"]:
            tag = "  pass" if a["passed"] else "  FAIL"
            lines.append(f"    {tag}: {a['label']}")
        for f in row["findings"]:
            sev = {"warn": "[!]", "note": "[*]", "info": "[i]"}.get(
                f["severity"], "[i]",
            )
            lines.append(f"    {sev} {f['message']}")
            if f["suggestion"]:
                lines.append(f"        → {f['suggestion']}")
    return "\n".join(lines)


# ---------- CLI entry point ----------

def _arg_value(args: list[str], flag: str) -> str | None:
    """Pop ``--flag VALUE`` (or ``--flag=VALUE``) and return VALUE,
    or ``None`` if the flag is absent. Same shape as diting's
    other internal arg helpers — kept duplicated here so this
    script has zero dependency on diting's CLI internals.
    """
    for i, a in enumerate(args):
        if a == flag:
            if i + 1 >= len(args):
                return None
            return args[i + 1]
        if a.startswith(flag + "="):
            return a.split("=", 1)[1]
    return None


def _main(argv: list[str]) -> int:
    """``python scripts/tui_snapshot.py [...]`` entry point.

    Engineering tool — explicitly NOT a diting subcommand. The
    user-facing ``diting`` CLI stays focused on real-time
    dashboard / monitor / analyze functionality; capturing TUI
    screenshots for regression and audit lives here in scripts/
    alongside ``update_vendors.py`` and the preview-capture script.

    Flags:
        --mode regression|explore
                              regression (default): synthetic backends, fixed
                              assertions, deterministic — for CI / make
                              test-system. explore: real ``MacOSWiFiBackend``
                              + live BLE helper, captures whatever the user's
                              actual environment looks like — for /tui-audit.
        --out-dir DIR         output directory.
                              default regression → ./snapshot-output
                              default explore   → /tmp/wfs-tui-audit-<stamp>
        --scenarios id1,id2   subset of scenario ids (default: all in mode)
        --json                emit JSON to stdout instead of console summary
        --check               exit 1 on any assertion failure (CI mode;
                              meaningful only in regression mode — explore
                              ships no fixed assertions)
    """
    mode = (_arg_value(argv, "--mode") or "regression").strip()
    if mode not in _MODES:
        print(
            f"--mode must be one of {_MODES}, got {mode!r}",
            file=__import__("sys").stderr,
        )
        return 2
    out_dir_str = _arg_value(argv, "--out-dir")
    out_dir = (
        Path(out_dir_str).expanduser().resolve()
        if out_dir_str else default_out_dir(mode).resolve()
    )
    scenarios_arg = _arg_value(argv, "--scenarios")
    scenario_ids = (
        [s.strip() for s in scenarios_arg.split(",") if s.strip()]
        if scenarios_arg else None
    )
    json_only = "--json" in argv
    check_mode = "--check" in argv

    report = run(out_dir, mode=mode, scenario_ids=scenario_ids)

    report_path = out_dir / "snapshot-report.json"
    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    )

    if json_only:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(render_console(report))
        print()
        print(f"note: full report at {report_path}")

    if check_mode and report["summary"]["asserts_failed"] > 0:
        return 1
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(_main(sys.argv[1:]))
