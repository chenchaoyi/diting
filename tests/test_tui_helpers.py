"""Pure-logic tests for the TUI helpers — _merge_current and
_group_by_ap. These don't import Textual itself; they exercise the
data transforms that the panels apply before rendering. The TUI
smoke test (test_tui_smoke) covers actually mounting the App.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from rich.text import Text

from diting.ble import BLEDevice
from diting.environment import APBaseline, RFStirEvent
from diting.events import (
    LatencySpikeEvent,
    LinkStateEvent,
    LossBurstEvent,
)
from diting.latency import LatencyAggregate
from diting.models import Connection, ScanResult
from diting.network import APEntry, NetworkInventory
from diting.poller import RoamEvent
from diting.tui import (
    BonjourDetailScreen,
    WifiDetailScreen,
    _aggregate_baselines,
    _baseline_table,
    _best_same_ssid_candidate,
    _ble_categories_line,
    _ble_closest_line,
    _ble_connected_line,
    _ble_diagnostic_lines,
    _ble_label_summary,
    _ble_vendors_line,
    _ble_visible_line,
    _bonjour_row_key,
    _format_duration_short,
    _free_space_distance_m,
    _hex_dump,
    _rssi_sparkline,
    _channel_hint,
    _environment_diagnostic_line,
    _event_format_line,
    _group_by_ap,
    _health_line,
    _link_diagnostic_line,
    _link_score,
    _merge_current,
    _scan_row_key,
    _score_line,
    _recommended_channel,
    _scan_line,
    _security_badge,
    _sigma_sparkline,
    _strip_service_suffix,
    _view_display_name,
    _view_tabs_border_title,
)


def _conn(bssid="40:fe:95:89:c7:e3", ssid="tedo_5G", rssi=-60, channel=48):
    return Connection(
        ssid=ssid, bssid=bssid, rssi_dbm=rssi, noise_dbm=-94,
        tx_rate_mbps=300.0, channel=channel, channel_width_mhz=80,
        channel_band="5 GHz", phy_mode="802.11ax", security="WPA2 Personal",
        mcs_index=5, nss=2, timestamp=datetime.now(),
    )


def _scan(
    bssid,
    ssid="x",
    rssi=-70,
    channel=36,
    *,
    width=20,
    security=None,
    country_code=None,
):
    return ScanResult(
        ssid=ssid, bssid=bssid, rssi_dbm=rssi, noise_dbm=-94,
        channel=channel, channel_width_mhz=width, channel_band="5 GHz",
        phy_mode=None, security=security, timestamp=datetime.now(),
        country_code=country_code,
    )


# --- _merge_current --------------------------------------------------

def test_merge_current_prepends_when_scan_omits_associated_ap():
    """The most common real-world case: CoreWLAN's scan does not list
    the AP we're connected to. The synth row makes it visible."""
    conn = _conn()
    scan = [_scan("40:fe:95:8a:3c:58")]
    out = _merge_current(scan, conn)
    assert len(out) == 2
    assert out[0].bssid == conn.bssid
    assert out[0].rssi_dbm == conn.rssi_dbm


def test_merge_current_replaces_when_scan_already_has_ap():
    """If scan already had the AP, replace it with synth so the panel
    never shows two different RSSIs / channels for the same BSSID."""
    conn = _conn(rssi=-50, channel=48)
    stale = _scan(conn.bssid, rssi=-80, channel=161)  # different values
    scan = [stale, _scan("aa:bb:cc:dd:ee:ff", rssi=-70)]
    out = _merge_current(scan, conn)
    assert len(out) == 2
    cur = next(r for r in out if r.bssid == conn.bssid)
    assert cur.rssi_dbm == -50
    assert cur.channel == 48


def test_merge_current_no_op_when_disconnected():
    scan = [_scan("aa:bb:cc:dd:ee:ff")]
    assert _merge_current(scan, None) == scan


def test_merge_current_no_op_when_connection_has_no_bssid():
    conn = _conn(bssid=None, ssid=None)
    scan = [_scan("aa:bb:cc:dd:ee:ff")]
    assert _merge_current(scan, conn) == scan


def test_merge_current_case_insensitive_match():
    """If scan reports BSSID upper-case but Connection has it
    lower-case, dedup should still hit."""
    conn = _conn(bssid="40:fe:95:89:c7:e3")
    scan = [_scan("40:FE:95:89:C7:E3")]
    out = _merge_current(scan, conn)
    assert len(out) == 1


# --- _group_by_ap ----------------------------------------------------

INVENTORY = NetworkInventory(
    aps=(
        APEntry(name="AX51-E_3-2F", mgmt_mac="40:fe:95:89:c7:df"),
        APEntry(name="AX51-E_4-B2", mgmt_mac="40:fe:95:8a:3c:54"),
    ),
)


def test_group_by_ap_clusters_inventory_matches():
    """Two BSSIDs that resolve to the same AP go into one group."""
    rows = [
        _scan("40:fe:95:89:c7:e0", ssid="tedo", rssi=-50),
        _scan("40:fe:95:89:c7:e3", ssid="tedo_5G", rssi=-55),
        _scan("44:fe:95:89:c7:e3", ssid="H3C_internal", rssi=-60),  # cross-OUI
    ]
    groups = _group_by_ap(rows, current_bssid=None, inv=INVENTORY)
    assert len(groups) == 1
    assert groups[0].key == "AX51-E_3-2F"
    assert len(groups[0].rows) == 3


def test_group_by_ap_separates_distinct_aps():
    rows = [
        _scan("40:fe:95:89:c7:e0", rssi=-50),
        _scan("40:fe:95:8a:3c:55", rssi=-40),
    ]
    groups = _group_by_ap(rows, current_bssid=None, inv=INVENTORY)
    assert {g.key for g in groups} == {"AX51-E_3-2F", "AX51-E_4-B2"}


def test_group_by_ap_floats_current_to_first():
    """Even when the current AP has weak signal, its group sits at the
    top so the user always finds their own row first."""
    rows = [
        _scan("40:fe:95:89:c7:e3", rssi=-80),       # current (weak)
        _scan("40:fe:95:8a:3c:55", rssi=-30),        # other (strong)
    ]
    groups = _group_by_ap(
        rows, current_bssid="40:fe:95:89:c7:e3", inv=INVENTORY
    )
    assert groups[0].key == "AX51-E_3-2F"
    assert groups[0].is_current is True
    assert groups[1].key == "AX51-E_4-B2"


def test_group_by_ap_otherwise_sorts_by_best_rssi():
    rows = [
        _scan("40:fe:95:89:c7:e3", rssi=-80),
        _scan("40:fe:95:8a:3c:55", rssi=-30),
    ]
    groups = _group_by_ap(rows, current_bssid=None, inv=INVENTORY)
    assert groups[0].key == "AX51-E_4-B2"  # -30 wins over -80
    assert groups[1].key == "AX51-E_3-2F"


def test_group_by_ap_within_group_sorts_by_rssi_desc():
    rows = [
        _scan("40:fe:95:89:c7:e0", rssi=-70),
        _scan("40:fe:95:89:c7:e3", rssi=-40),
        _scan("40:fe:95:89:c7:e5", rssi=-55),
    ]
    g = _group_by_ap(rows, current_bssid=None, inv=INVENTORY)[0]
    rssis = [r.rssi_dbm for r in g.rows]
    assert rssis == sorted(rssis, reverse=True)


def test_group_by_ap_unaliased_uses_cluster_label():
    """BSSIDs not in inventory get a cluster_label key that begins
    with '?' — the renderer relies on that prefix to style auto-
    discovered groups dimly."""
    inv = NetworkInventory()  # no APs
    rows = [
        _scan("c2:91:7c:40:5d:0f", rssi=-40),
        _scan("c2:91:7c:40:5d:13", rssi=-50),  # same chip serial
    ]
    groups = _group_by_ap(rows, current_bssid=None, inv=inv)
    assert len(groups) == 1
    assert groups[0].key.startswith("?")


def test_group_by_ap_empty_input():
    assert _group_by_ap([], current_bssid=None, inv=INVENTORY) == []


# --- environment / health summaries ---------------------------------

def test_best_same_ssid_candidate_requires_meaningful_delta():
    conn = _conn(bssid="aa:aa:aa:aa:aa:01", ssid="office", rssi=-75)
    rows = [
        _scan("aa:aa:aa:aa:aa:01", ssid="office", rssi=-75),
        _scan("aa:aa:aa:aa:aa:02", ssid="office", rssi=-63),
        _scan("aa:aa:aa:aa:aa:03", ssid="guest", rssi=-40),
    ]
    assert _best_same_ssid_candidate(rows, conn) is None
    rows[1] = _scan("aa:aa:aa:aa:aa:02", ssid="office", rssi=-55)
    best = _best_same_ssid_candidate(rows, conn)
    assert best is not None
    assert best[0].bssid == "aa:aa:aa:aa:aa:02"
    assert best[1] == 20


def test_recommended_channel_prefers_less_busy_common_channel():
    rows = [
        _scan("aa:aa:aa:aa:aa:01", channel=1, rssi=-50),
        _scan("aa:aa:aa:aa:aa:02", channel=6, rssi=-80),
        _scan("aa:aa:aa:aa:aa:03", channel=36, rssi=-50),
        _scan("aa:aa:aa:aa:aa:04", channel=36, rssi=-60),
    ]
    assert _recommended_channel(rows, "2.4G") == 11
    assert _recommended_channel(rows, "5G") == 40


def test_channel_hint_explains_channel_absent_from_scan_list():
    rows = [_scan("aa:aa:aa:aa:aa:01", channel=36, rssi=-45)]
    assert "(no AP heard)" in _channel_hint("5 GHz", 44, rows).plain
    assert "(no AP heard)" not in _channel_hint("5 GHz", 36, rows).plain


def test_health_line_explains_weak_signal_and_better_ap():
    conn = _conn(bssid="aa:aa:aa:aa:aa:01", ssid="office", rssi=-75)
    rows = [
        _scan("aa:aa:aa:aa:aa:01", ssid="office", rssi=-75),
        _scan("aa:aa:aa:aa:aa:02", ssid="office", rssi=-50, channel=44),
    ]
    text = _health_line(rows, conn).plain
    assert "weak signal -75 dBm" in text
    assert "SNR 19 dB" in text
    assert "stronger same-name AP nearby: +25 dB" in text
    assert "press c to re-roam" in text


def test_security_badge_marks_open_networks():
    assert _security_badge("Open") == ("OPEN", "bold yellow")
    assert _security_badge("WPA2 Enterprise") == ("ENT", "dim")
    assert _security_badge("WPA3 Personal") == ("WPA3", "dim")


def test_scan_line_includes_open_security_marker():
    row = _scan(
        "aa:bb:cc:dd:ee:ff",
        ssid="guest",
        rssi=-50,
        security="Open",
    )
    text = _scan_line(row, current_bssid=None, inv=NetworkInventory()).plain
    assert "OPEN" in text


def test_link_score_rewards_stronger_cleaner_candidate():
    current = _conn(
        bssid="aa:aa:aa:aa:aa:01",
        ssid="office",
        rssi=-75,
        channel=52,
    )
    candidate = _scan(
        "aa:aa:aa:aa:aa:02",
        ssid="office",
        rssi=-50,
        channel=44,
        security="WPA2 Personal",
    )
    rows = [candidate]
    assert _link_score(candidate, rows, baseline=current).score > (
        _link_score(current, rows, baseline=current).score
    )


def test_score_line_reports_better_same_ssid_candidate():
    current = _conn(
        bssid="aa:aa:aa:aa:aa:01",
        ssid="office",
        rssi=-76,
        channel=52,
    )
    rows = [
        _scan("aa:aa:aa:aa:aa:01", ssid="office", rssi=-76, channel=52),
        _scan("aa:aa:aa:aa:aa:02", ssid="office", rssi=-48, channel=44,
              security="WPA2 Personal"),
    ]
    text = _score_line(rows, current).plain
    assert "current" in text
    assert "better candidate" in text
    assert "press c to re-roam" in text


# --- BLE diagnostics ---------------------------------------------------

def _ble_dev(identifier="00000000-0000-0000-0000-000000000001",
             name="dev", vendor="Apple, Inc.", vendor_id=76,
             services=(), rssi=-50, is_connectable=True,
             merged_count=1, type=None, device_class=None,
             is_connected=False):
    """Lightweight BLEDevice factory; the timestamps are placeholders
    since the diagnostic helpers do not read first_seen / last_seen."""
    t = datetime(2026, 5, 7, 9, 30, 0)
    return BLEDevice(
        identifier=identifier,
        name=name,
        vendor=vendor,
        vendor_id=vendor_id,
        services=services,
        rssi_dbm=rssi,
        is_connectable=is_connectable,
        first_seen=t,
        last_seen=t,
        ad_count=1,
        merged_count=merged_count,
        type=type,
        device_class=device_class,
        is_connected=is_connected,
    )


def test_ble_visible_line_counts_total_connectable_anonymous():
    devices = [
        _ble_dev(identifier="01", name="AirPods", vendor="Apple, Inc.",
                 is_connectable=True),
        _ble_dev(identifier="02", name=None, vendor=None,
                 vendor_id=None, is_connectable=False),
        _ble_dev(identifier="03", name=None, vendor=None,
                 vendor_id=None, is_connectable=True),
    ]
    text = _ble_visible_line(devices).plain
    # Three devices total, two connectable, two anonymous (no vendor
    # AND no name). Anonymous count appears even when it equals the
    # connectable count because the categories are independent.
    assert "3 total" in text
    assert "2 connectable" in text
    assert "2 anonymous" in text


def test_ble_vendors_line_top_four_plus_unknown():
    devices = (
        [_ble_dev(identifier=f"a{i}", vendor="Apple, Inc.",
                  vendor_id=76) for i in range(4)]
        + [_ble_dev(identifier=f"x{i}", vendor="Xiaomi Inc.",
                    vendor_id=637) for i in range(2)]
        + [_ble_dev(identifier=f"u{i}", vendor=None, vendor_id=None,
                    name=None) for i in range(3)]
    )
    text = _ble_vendors_line(devices).plain
    assert "Apple, Inc. 4" in text
    assert "Xiaomi Inc. 2" in text
    # Unknown (no vendor) gets a separate "(unknown) N" tag rather
    # than being silently dropped, so the user sees the full picture.
    # Previously this was rendered as "? N" — that reads as a typo,
    # the column convention is "(unknown)".
    assert "(unknown) 3" in text
    assert "? 3" not in text


def test_ble_vendors_line_annotates_folded_rotation_count():
    """When merge_for_display has folded RPA rotations, the diagnostic
    line surfaces the total folded count so the user reads the row
    counts as post-merge, not raw."""
    devices = [
        # Two Anhui Huami rows; the first row folded 4 extra rotations
        # (merged_count=5 means 5 raw identifiers collapsed into 1
        # display row), the second folded 2.
        _ble_dev(identifier="ah1", vendor="Anhui Huami", vendor_id=911,
                 merged_count=5),
        _ble_dev(identifier="ah2", vendor="Anhui Huami", vendor_id=911,
                 merged_count=3),
        # One Apple row with no folding.
        _ble_dev(identifier="a1", vendor="Apple, Inc.", vendor_id=76,
                 merged_count=1),
    ]
    text = _ble_vendors_line(devices).plain
    # Vendor counts use the post-merge row count (not raw).
    assert "Anhui Huami 2" in text
    assert "Apple, Inc. 1" in text
    # Folded annotation totals (merged_count - 1) across all rows:
    # (5-1) + (3-1) + (1-1) = 6.
    assert "(+6 folded)" in text


def test_ble_vendors_line_skips_annotation_when_nothing_folded():
    """No folding → no annotation; the line stays clean for the common
    case where every visible row corresponds to a single raw
    advertisement."""
    devices = [
        _ble_dev(identifier="a1", vendor="Apple, Inc.", vendor_id=76),
        _ble_dev(identifier="a2", vendor="Apple, Inc.", vendor_id=76),
    ]
    text = _ble_vendors_line(devices).plain
    assert "Apple, Inc. 2" in text
    assert "folded" not in text


def test_ble_categories_line_groups_by_service_category():
    # Apple Watch advertises both HID (1812) and Heart Rate (180D),
    # which should each contribute one to its bucket — never two.
    apple_watch = _ble_dev(identifier="aw1", services=("180D", "1812"))
    airpods = _ble_dev(identifier="ap1", services=("110A",))  # Audio
    nameless = _ble_dev(identifier="nx", services=())  # no category
    text = _ble_categories_line(
        [apple_watch, airpods, nameless]
    ).plain
    assert "1 Heart Rate" in text
    assert "1 HID" in text
    assert "1 Audio" in text
    # Devices without any categorised service show up as "N other".
    assert "1 other" in text


def test_ble_closest_line_picks_strongest_rssi():
    devices = [
        _ble_dev(identifier="far", name="A", vendor="Apple, Inc.",
                 rssi=-80),
        _ble_dev(identifier="near", name="Magic Keyboard",
                 vendor="Apple, Inc.", rssi=-32),
        _ble_dev(identifier="mid", name="B", vendor="Apple, Inc.",
                 rssi=-60),
    ]
    text = _ble_closest_line(devices).plain
    assert "-32 dBm" in text
    assert "Magic Keyboard (Apple, Inc.)" in text


def test_ble_closest_line_falls_back_to_anonymous_label():
    """When the strongest device has neither name nor vendor we still
    show its RSSI rather than dropping the row, with a generic
    placeholder so the user knows we have not lost the device."""
    devices = [_ble_dev(identifier="xxx", name=None, vendor=None,
                        vendor_id=None, rssi=-44)]
    text = _ble_closest_line(devices).plain
    assert "-44 dBm" in text
    assert "(anonymous)" in text


def test_ble_diagnostic_lines_returns_four_rows():
    """Sanity: with no connected peripherals the dispatcher returns
    the four rows the panel has had since v0.5.0. Pinning the count
    keeps an accidental fifth row from breaking the panel min-height
    expected layout."""
    devices = [_ble_dev()]
    rows = _ble_diagnostic_lines(devices)
    assert len(rows) == 4


def test_ble_diagnostic_lines_adds_connected_row_when_present():
    """When the helper has reported at least one connected peripheral,
    the diagnostics gain a fifth 'Connected  N peripherals · ...' row.
    The Mac with AirPods + Magic Keyboard paired should see this."""
    devices = [_ble_dev()]
    connected = [
        _ble_dev(identifier="cc1", name="Magic Keyboard",
                 services=("1812",), rssi=None, is_connected=True),
        _ble_dev(identifier="cc2", name="AirPods Pro",
                 services=("110A",), rssi=None, is_connected=True),
    ]
    rows = _ble_diagnostic_lines(devices, connected)
    assert len(rows) == 5
    assert "2 peripherals" in rows[4].plain
    # Service-category breakdown follows the headcount.
    assert "Audio 1" in rows[4].plain
    assert "HID 1" in rows[4].plain


def test_ble_categories_line_includes_deep_id_types():
    """Schema-3 type / device_class show up in the categories line so
    a panel showing 4 iBeacons + 1 AirTag tells the user that even
    when the underlying service-UUID list is empty (iBeacon advertises
    no service UUIDs)."""
    devices = [
        _ble_dev(identifier="ib1", services=(), type="iBeacon"),
        _ble_dev(identifier="ib2", services=(), type="iBeacon"),
        _ble_dev(identifier="at1", services=("FD5A",), type="AirTag"),
        _ble_dev(identifier="ip1", services=(), device_class="iPhone"),
    ]
    text = _ble_categories_line(devices).plain
    assert "2 iBeacon" in text
    assert "1 AirTag" in text
    assert "1 iPhone" in text


def test_ble_label_summary_services_only():
    """`_ble_label_summary` is now purely service-category-derived.
    Schema-3 `type` and Apple Nearby Info `device_class` no longer
    appear in this column — they moved to the Name column's cascade
    so the same fact doesn't render in two columns.
    """
    # type=AirTag + FD5A service: Services column shows only the
    # service-category (Find My), NOT 'AirTag · Find My'.
    airtag = _ble_dev(services=("FD5A",), type="AirTag")
    assert _ble_label_summary(airtag) == "Find My"
    # No services and only a device_class → empty Services column.
    iphone_via_nearby = _ble_dev(services=(), device_class="iPhone")
    assert _ble_label_summary(iphone_via_nearby) == ""
    # No type / device_class, only a service → service-category only.
    plain = _ble_dev(services=("180D",))  # Heart Rate
    assert _ble_label_summary(plain) == "Heart Rate"


# --- Name column cascade ---------------------------------------------

def _row_text(d) -> str:
    """Render `_ble_row_line` and return its `.plain` for substring
    assertions. Uses a fixed `now` so the age column is deterministic."""
    from diting.tui import _ble_row_line
    now = datetime(2026, 5, 11, 18, 0, 0)
    return _ble_row_line(d, now).plain


def test_ble_row_line_name_uses_helper_name_when_present():
    """When the helper supplies a broadcast name, the Name column
    shows it verbatim — no synthesis, no fallback."""
    d = _ble_dev(name="ccy iPhone")
    text = _row_text(d)
    assert "ccy iPhone" in text
    assert "(unknown)" not in text


def test_ble_row_line_name_falls_back_to_type():
    """No helper-provided name but schema-3 `type` set: Name column
    shows the (translated) type rather than '(unknown)'. This is the
    fix for the audit finding that ~17% of visible rows showed
    '(unknown)' alongside a perfectly good type in the Services column."""
    d = _ble_dev(name=None, type="Find My target")
    text = _row_text(d)
    assert "Find My target" in text
    # No '(unknown)' placeholder when we have something to show.
    assert "(unknown)" not in text


def test_ble_row_line_name_falls_back_to_device_class():
    """No name and no type, but Apple Nearby Info supplied a
    device_class: cascade picks device_class as the next-best name."""
    d = _ble_dev(name=None, type=None, device_class="iPhone")
    text = _row_text(d)
    assert "iPhone" in text
    assert "(unknown)" not in text


def test_ble_row_line_name_unknown_when_no_signal():
    """No name, no type, no device_class → fall through to the
    `(unknown)` placeholder. The cascade adds no new data, only
    surfaces what was already there."""
    d = _ble_dev(name=None, type=None, device_class=None)
    text = _row_text(d)
    assert "(unknown)" in text


# --- Rotating-identifier name guard (v1.7.2) ------------------------

def test_ble_looks_like_rotating_id_predicate_true_on_apple_continuity_shape():
    from diting.tui import _looks_like_rotating_id
    # 22-char base64-ish string Apple Continuity emits in the name
    # slot when the advertisement is a Find My / Handoff beacon.
    assert _looks_like_rotating_id("NZ1NhvIw3H5T5cSy3kULrJ") is True


def test_ble_looks_like_rotating_id_predicate_true_on_huami_serial():
    from diting.tui import _looks_like_rotating_id
    # Z-prefixed Huami / Amazfit watch serials.
    assert _looks_like_rotating_id("Z-GM0YXG6A") is False  # too short
    assert _looks_like_rotating_id("Z-GM0YXG6A1234567") is True
    # Long all-hex identifier (no Apple prefix).
    assert _looks_like_rotating_id("abcdef0123456789abcd") is True


def test_ble_looks_like_rotating_id_predicate_false_on_iphone_prefix():
    from diting.tui import _looks_like_rotating_id
    # Apple-product prefix lock — even if the suffix looks random,
    # the name is meant to be human-readable.
    assert _looks_like_rotating_id("iPhone") is False
    assert _looks_like_rotating_id("Mac1234567890ABCDEF") is False
    assert _looks_like_rotating_id("AirPodsXYZABC0123456") is False
    assert _looks_like_rotating_id("HomePod-Living-Room-1234") is False  # has '-' but space-free still locked by prefix


def test_ble_looks_like_rotating_id_predicate_false_on_whitespace_name():
    from diting.tui import _looks_like_rotating_id
    # Any whitespace disqualifies — "real" device names use spaces.
    assert _looks_like_rotating_id("ccy's Magic Keyboard") is False
    assert _looks_like_rotating_id("HW Watch GT") is False
    assert _looks_like_rotating_id("Living Room TV") is False


def test_ble_looks_like_rotating_id_predicate_false_on_short_name():
    from diting.tui import _looks_like_rotating_id
    # 15 chars or fewer never trigger the guard.
    assert _looks_like_rotating_id("abc") is False
    assert _looks_like_rotating_id("ABCDEFGHIJKLMNO") is False
    # Exactly 16 chars — the threshold.
    assert _looks_like_rotating_id("ABCDEFGHIJKLMNOP") is True


def test_ble_looks_like_rotating_id_predicate_false_on_none():
    from diting.tui import _looks_like_rotating_id
    assert _looks_like_rotating_id(None) is False
    assert _looks_like_rotating_id("") is False


def test_ble_row_name_substitutes_rotating_id_placeholder():
    """The row renderer hands the helper-emitted rotating-identifier
    string to the guard and renders `(rotating ID)` instead."""
    d = _ble_dev(name="NZ1NhvIw3H5T5cSy3kULrJ")
    text = _row_text(d)
    assert "(rotating ID)" in text
    # The raw value SHALL NOT appear in the list row.
    assert "NZ1NhvIw3H5T5cSy3kULrJ" not in text


def test_ble_row_name_preserves_real_apple_device_name():
    """Apple prefix is in the allowlist; real iPhone / Mac names
    render verbatim with no `(rotating ID)` substitution."""
    d = _ble_dev(name="iPhone")
    text = _row_text(d)
    assert "iPhone" in text
    assert "(rotating ID)" not in text


def test_ble_detail_renders_raw_name_row_when_rotating_id():
    """When the predicate fires, BLEDetailScreen's Identity section
    gains a `Raw name:` row so the user can still see what the
    helper actually advertised."""
    from diting.tui import BLEDetailScreen
    d = _ble_dev(name="NZ1NhvIw3H5T5cSy3kULrJ")
    out = Text()
    screen = BLEDetailScreen(device=d)
    screen._section_identity(out)
    rendered = out.plain
    assert "Raw name" in rendered
    assert "NZ1NhvIw3H5T5cSy3kULrJ" in rendered
    # `name:` row shows the placeholder, not the raw value.
    assert "(rotating ID)" in rendered


def test_ble_detail_omits_raw_name_row_when_name_none():
    """Anonymous device (name=None) has nothing to surface — no
    `Raw name:` row, no `(rotating ID)` placeholder."""
    from diting.tui import BLEDetailScreen
    d = _ble_dev(name=None)
    out = Text()
    screen = BLEDetailScreen(device=d)
    screen._section_identity(out)
    rendered = out.plain
    assert "Raw name" not in rendered


def test_ble_row_line_services_no_longer_duplicates_type():
    """End-to-end check: a row with type='AirTag' and the FD5A service
    no longer renders 'AirTag · Find My' in the Services column
    (which was duplicating the type one column to the right of where
    it now lives). 'AirTag' appears exactly once — in the Name column."""
    d = _ble_dev(name=None, services=("FD5A",), type="AirTag")
    text = _row_text(d)
    # AirTag appears (it's the Name column value now).
    assert "AirTag" in text
    # And only once — not duplicated in Services.
    assert text.count("AirTag") == 1
    # Services column still shows the service-category.
    assert "Find My" in text


# --- v0.7.0 Link / Environment / Events ----------------------------

def _agg(target, *, rtt=None, loss=None, jitter=None, samples=10, ip="192.168.1.1"):
    return LatencyAggregate(
        target=target, target_ip=ip, rtt_ms=rtt, loss_pct=loss,
        jitter_ms=jitter, sample_count=samples,
    )


def test_link_diagnostic_line_good_link():
    """A healthy gateway and WAN render numbers, no warning glyph."""
    gw = _agg("router", rtt=12.0, loss=0.0, jitter=2.0)
    wan = _agg("wan", rtt=18.0, loss=0.0, jitter=3.0, ip="1.1.1.1")
    text = _link_diagnostic_line(gw, wan, None).plain
    assert "Router 12 ms" in text
    assert "0% loss" in text
    assert "WAN 18 ms" in text
    assert "jitter" in text
    assert "⚠" not in text


def test_link_diagnostic_line_loss_marks_warning():
    gw = _agg("router", rtt=412.0, loss=25.0, jitter=12.0)
    text = _link_diagnostic_line(gw, None, None).plain
    assert "⚠" in text
    assert "412 ms" in text
    assert "25% loss" in text


def test_link_diagnostic_line_router_no_icmp_reply_when_all_pings_fail():
    """When all ICMP probes fail (rtt=None) and loss is ≥ 50%, the
    Router half renders `(no ICMP reply)` rather than the previous
    `WAN unreachable` typo. WAN-side wording is unchanged because the
    WAN probe is TCP/53, not ICMP — a TCP timeout there really IS
    "unreachable" from the host's perspective."""
    gw = _agg("router", rtt=None, loss=100.0, jitter=None)
    text = _link_diagnostic_line(gw, None, None).plain
    # Router half says ICMP-specific.
    assert "Router" in text
    assert "no ICMP reply" in text
    # The old typo no longer leaks into the Router half.
    assert "Router WAN unreachable" not in text
    assert "Router unreachable" not in text


def test_link_diagnostic_line_wan_unreachable_when_tcp_fails():
    """WAN probe is TCP/53. When it fails with rtt=None + ≥50% loss,
    the WAN half still says `WAN unreachable` — the wording matches
    the user's actual experience because a TCP failure here means
    "can't open connections past the router"."""
    gw = _agg("router", rtt=12.0, loss=0.0, jitter=2.0)
    wan = _agg("wan", rtt=None, loss=100.0, jitter=None, ip="1.1.1.1")
    text = _link_diagnostic_line(gw, wan, None).plain
    assert "WAN unreachable" in text
    # Router half stays healthy — no ICMP wording leaks here.
    assert "Router 12 ms" in text


def test_link_diagnostic_line_wan_unreachable_when_no_dns():
    """No SCDynamicStore answer → WAN n/a label."""
    gw = _agg("router", rtt=12.0, loss=0.0, jitter=2.0)
    text = _link_diagnostic_line(gw, None, "no_dns").plain
    assert "WAN n/a" in text
    assert "DNS == gateway" not in text


def test_link_diagnostic_line_wan_dns_eq_gateway_explains():
    """The home-router case: DNS is the gateway. Render the
    explanatory ``WAN n/a (DNS == gateway)`` so the user knows why
    the second column is missing."""
    gw = _agg("router", rtt=12.0, loss=0.0, jitter=2.0)
    text = _link_diagnostic_line(gw, None, "dns_eq_gateway").plain
    assert "WAN n/a" in text
    assert "DNS == gateway" in text


def test_environment_diagnostic_line_stable():
    text = _environment_diagnostic_line("stable", 1.2, None).plain
    assert "stable" in text
    assert "σ" in text
    assert "1.2" in text


def test_environment_diagnostic_line_active_marks_warning():
    """The 'active' label gets a ⚠ prefix and surfaces last-event-ago."""
    last = datetime.now()
    text = _environment_diagnostic_line("active", 7.8, last).plain
    assert "⚠" in text
    assert "active" in text
    assert "7.8" in text
    assert "last event" in text


def test_environment_diagnostic_line_quiet_when_calibrated():
    text = _environment_diagnostic_line("quiet", 0.7, None).plain
    assert "quiet" in text
    assert "0.7" in text


def _stir_event():
    return RFStirEvent(
        timestamp=datetime(2026, 5, 7, 9, 0, 0),
        bssid="aa:bb:cc:11:22:53",
        location="1F-bedroom",
        magnitude_db=8.3,
        duration_s=12.0,
        confidence="high",
        mode="co_located",
    )


def _spike_event():
    return LatencySpikeEvent(
        timestamp=datetime(2026, 5, 7, 9, 0, 5),
        target="router", target_ip="192.168.1.1",
        rtt_ms=412.0, loss_pct=25.0,
    )


def _loss_event():
    return LossBurstEvent(
        timestamp=datetime(2026, 5, 7, 9, 0, 9),
        target="wan", target_ip="1.1.1.1",
        loss_pct=80.0, lost_in_window=4,
    )


def _link_event():
    return LinkStateEvent(
        timestamp=datetime(2026, 5, 7, 9, 0, 11),
        state="associated", bssid="aa:bb:cc:11:22:53", ssid="office",
    )


def _roam_event():
    return RoamEvent(
        timestamp=datetime(2026, 5, 7, 9, 0, 13),
        previous_bssid="aa:bb:cc:11:22:50",
        previous_channel=36,
        new_bssid="aa:bb:cc:33:44:10",
        new_channel=48,
    )


def test_event_format_line_rf_stir():
    text = _event_format_line(_stir_event(), NetworkInventory()).plain
    assert "[STIR]" in text
    assert "1F-bedroom" in text
    assert "8.3" in text
    assert "high" in text


def test_event_format_line_rf_stir_confidence_translates_to_chinese():
    """The confidence enum (high / medium / low) renders translated
    under DITING_LANG=zh. Previously rendered raw English even in ZH
    mode — surfaced by the 2026-05-11 tui-audit."""
    from diting import i18n
    saved = i18n.get_lang()
    try:
        i18n.set_lang("zh")
        text = _event_format_line(_stir_event(), NetworkInventory()).plain
        assert "高" in text  # confidence='high' → '高'
        assert "high" not in text
    finally:
        i18n.set_lang(saved)


def _roam_event_with_ssids(prev_ssid: str | None, new_ssid: str | None) -> RoamEvent:
    return RoamEvent(
        timestamp=datetime(2026, 5, 18, 9, 49),
        previous_bssid="aa:bb:cc:11:22:50",
        previous_channel=36,
        new_bssid="aa:bb:cc:33:44:10",
        new_channel=48,
        previous_ssid=prev_ssid,
        new_ssid=new_ssid,
    )


def test_format_roam_event_includes_ssid_when_same_on_both_sides():
    """Band switch / inter-AP roam keeping the same network: the
    rendered line carries `SSID: <name>` exactly once."""
    text = _event_format_line(
        _roam_event_with_ssids("tedo", "tedo"),
        NetworkInventory(),
    ).plain
    assert "SSID: tedo" in text
    # No transition arrow alongside the SSID; the BSSID arrow is
    # separate.
    assert "SSID: tedo -> " not in text


def test_format_roam_event_renders_ssid_transition_when_different():
    text = _event_format_line(
        _roam_event_with_ssids("home", "office"),
        NetworkInventory(),
    ).plain
    assert "SSID: home -> office" in text


def test_format_roam_event_omits_ssid_segment_when_both_none():
    text = _event_format_line(
        _roam_event_with_ssids(None, None),
        NetworkInventory(),
    ).plain
    assert "SSID" not in text


def test_format_roam_event_omits_ssid_segment_for_hidden_ssid():
    """Both sides hidden (empty string from CoreWLAN) — no SSID
    segment. We don't render `SSID: ` with nothing after."""
    text = _event_format_line(
        _roam_event_with_ssids("", ""),
        NetworkInventory(),
    ).plain
    assert "SSID" not in text


def test_format_rf_stir_event_includes_ssid_when_present():
    """When event.ssid is non-empty, the line appends `· SSID <name>`
    after the location body."""
    event = RFStirEvent(
        timestamp=datetime(2026, 5, 18, 9, 49),
        bssid="1c:28:af:5e:9d:b4",
        location="?af:5e:9d",
        magnitude_db=4.8,
        duration_s=12.0,
        confidence="medium",
        mode="spatial_channel",
        ssid="tedo_5G",
    )
    text = _event_format_line(event, NetworkInventory()).plain
    assert "SSID tedo_5G" in text


def test_format_rf_stir_event_omits_ssid_segment_when_none():
    """No SSID known — the rendered line is unchanged from the
    legacy pre-enrichment shape."""
    event = RFStirEvent(
        timestamp=datetime(2026, 5, 18, 9, 49),
        bssid="1c:28:af:5e:9d:b4",
        location="?af:5e:9d",
        magnitude_db=4.8,
        duration_s=12.0,
        confidence="medium",
        mode="spatial_channel",
    )
    text = _event_format_line(event, NetworkInventory()).plain
    assert "SSID" not in text


def test_event_format_line_latency_spike():
    text = _event_format_line(_spike_event(), NetworkInventory()).plain
    assert "[LATENCY]" in text
    assert "router" in text
    assert "412" in text


def test_event_format_line_latency_spike_loss_suffix_translates_to_chinese():
    """The "% loss" suffix on latency-spike events used to render raw
    English under DITING_LANG=zh because it was a bare f-string. Wrap
    in t() so it follows the same translation as the diagnostic Link
    row's "{loss}% loss" → "丢包 {loss}%". Surfaced by tui-audit."""
    from diting import i18n
    # _spike_event() has loss_pct=25.0 so the suffix renders.
    saved = i18n.get_lang()
    try:
        i18n.set_lang("zh")
        text = _event_format_line(_spike_event(), NetworkInventory()).plain
        assert "丢包" in text
        assert "% loss" not in text
    finally:
        i18n.set_lang(saved)


def test_event_format_line_loss_burst():
    text = _event_format_line(_loss_event(), NetworkInventory()).plain
    assert "[LOSS]" in text
    assert "wan" in text
    assert "80%" in text


def test_event_format_line_link_state():
    text = _event_format_line(_link_event(), NetworkInventory()).plain
    assert "[LINK]" in text
    assert "office" in text


def test_event_format_line_roam_uses_inventory():
    inv = NetworkInventory(aps=(
        APEntry(name="1F-living", mgmt_mac="aa:bb:cc:11:22:4f"),
        APEntry(name="2F-study",  mgmt_mac="aa:bb:cc:33:44:0f"),
    ))
    text = _event_format_line(_roam_event(), inv).plain
    assert "[ROAM]" in text


def test_sigma_sparkline_renders_bars():
    """A non-empty σ history renders as a row of block characters with
    the max σ surfaced. Bucketing is anchored to ``now`` so the test
    must pass an explicit reference time matching the fake history,
    otherwise the bucket window slides past the synthetic samples."""
    base = datetime(2026, 5, 7, 9, 0, 0)
    # 10 samples spaced 2 min apart; "now" is right after the last one
    # so all samples fall inside the 1 h window.
    points = [
        (base + timedelta(minutes=2 * j), float(j))
        for j in range(10)
    ]
    now = base + timedelta(minutes=20)
    text = _sigma_sparkline(points, now=now).plain
    # Must contain at least one block character and the max σ label.
    assert any(c in text for c in "▁▂▃▄▅▆▇█")
    assert "max σ 9.0" in text


def test_sigma_sparkline_drops_samples_older_than_one_hour():
    """The sparkline window is the trailing 1 h ending at ``now``.
    Samples older than that fall off the left edge instead of being
    stretched across the bar — guards the bug where 90 s of data
    was rendered as if it spanned the full hour."""
    base = datetime(2026, 5, 7, 9, 0, 0)
    points = [
        (base, 8.0),                 # 90 min ago — out of window
        (base + timedelta(minutes=70), 1.5),   # 20 min ago — in
        (base + timedelta(minutes=85), 2.0),   # 5 min ago — in
    ]
    now = base + timedelta(minutes=90)
    text = _sigma_sparkline(points, now=now).plain
    # The 8.0 sample is excluded so max σ should be 2.0, not 8.0.
    assert "max σ 2.0" in text


def test_sigma_sparkline_reports_data_span():
    """The legend includes a 'data ~Nm' span so a fresh session that
    only has 3 minutes of σ history is honestly labelled instead of
    pretending to cover a full hour."""
    base = datetime(2026, 5, 7, 9, 0, 0)
    points = [(base + timedelta(minutes=j), 1.0) for j in range(4)]
    now = base + timedelta(minutes=3)
    text = _sigma_sparkline(points, now=now).plain
    # English: "data ~3m" — Chinese translation reuses the same token.
    assert "~3m" in text


def _baseline(bssid, location, mode="co_located", samples=40,
              baseline_sigma=None, current_sigma=None, last_rssi=-55):
    return APBaseline(
        bssid=bssid, location=location, mode=mode, samples=samples,
        baseline_sigma=baseline_sigma, current_sigma=current_sigma,
        last_rssi=last_rssi,
    )


def test_aggregate_baselines_collapses_bssids_to_one_row_per_ap():
    """The same physical AP broadcasts many BSSIDs (one per SSID×band).
    The aggregator must fold those back to a single row keyed on the
    AP-level location label, otherwise the modal shows the AP up to
    ten times."""
    rows = [
        _baseline("a8:5b:f7:e1:a3:e0", "?f7:e1:a3", samples=40, last_rssi=-46),
        _baseline("a8:5b:f7:e1:a3:f0", "?f7:e1:a3", samples=322,
                  baseline_sigma=2.8, current_sigma=2.4, last_rssi=-52),
        _baseline("a8:5b:f7:e1:a3:f4", "?f7:e1:a3", samples=40, last_rssi=-58),
        _baseline("a8:5b:f7:e1:d5:a0", "?f7:e1:d5", samples=40, last_rssi=-43),
        _baseline("a8:5b:f7:e1:d5:b4", "?f7:e1:d5", samples=40, last_rssi=-52),
    ]
    groups = _aggregate_baselines(rows)
    assert len(groups) == 2
    by_loc = {g["location"]: g for g in groups}
    a3 = by_loc["?f7:e1:a3"]
    assert a3["bssid_count"] == 3
    assert a3["samples"] == 40 + 322 + 40
    # Loudest BSSID's σ wins; closest RSSI wins (max because dBm is
    # negative).
    assert a3["baseline_sigma"] == 2.8
    assert a3["current_sigma"] == 2.4
    assert a3["last_rssi"] == -46
    d5 = by_loc["?f7:e1:d5"]
    assert d5["bssid_count"] == 2
    assert d5["baseline_sigma"] is None
    assert d5["current_sigma"] is None


def test_aggregate_baselines_picks_strongest_mode_per_ap():
    """If at least one of an AP's BSSIDs classifies as co_located, the
    AP row should report co_located — the closer signal wins because
    that is the band the user is actually associating to."""
    rows = [
        _baseline("aa:bb:cc:dd:ee:01", "loc", mode="spatial_channel"),
        _baseline("aa:bb:cc:dd:ee:02", "loc", mode="co_located"),
    ]
    groups = _aggregate_baselines(rows)
    assert groups[0]["mode"] == "co_located"


def test_baseline_table_folds_pending_aps_into_a_single_line():
    """APs with no baseline σ and no current σ haven't accumulated
    enough samples to say anything. They should not each get their
    own row of question marks; the table must fold them into one
    "(N APs still collecting samples)" footer line."""
    rows = [
        _baseline("a8:5b:f7:e1:a3:f0", "?f7:e1:a3", samples=322,
                  baseline_sigma=2.8, current_sigma=2.4, last_rssi=-52),
        _baseline("a8:5b:f7:e1:d5:a0", "?f7:e1:d5", samples=40,
                  last_rssi=-43),
        _baseline("a8:5b:f7:e0:cd:80", "?f7:e0:cd", samples=40,
                  last_rssi=-56),
    ]
    text = _baseline_table(rows).plain
    # Exactly one ready row.
    assert text.count("?f7:e1:a3") == 1
    # Both pending APs collapsed into the footer.
    assert "?f7:e1:d5" not in text
    assert "?f7:e0:cd" not in text
    assert "2 APs still collecting samples" in text or \
        "2 个 AP 仍在采集样本" in text


def test_baseline_table_marks_stirring_when_current_exceeds_baseline_x3():
    """The status badge follows the same fire rule as the events log:
    current σ ≥ 5 dB AND > baseline × 3 → 'stirring'. Anything else →
    'stable'."""
    rows_quiet = [
        _baseline("aa:bb:cc:dd:ee:01", "loc-quiet", samples=200,
                  baseline_sigma=1.0, current_sigma=1.2, last_rssi=-55),
    ]
    rows_loud = [
        _baseline("aa:bb:cc:dd:ee:02", "loc-loud", samples=200,
                  baseline_sigma=1.0, current_sigma=8.0, last_rssi=-55),
    ]
    quiet_text = _baseline_table(rows_quiet).plain
    loud_text = _baseline_table(rows_loud).plain
    # Use either English source or Chinese translation depending on
    # locale; both should be present in their respective rows.
    assert ("stable" in quiet_text) or ("稳定" in quiet_text)
    assert ("stirring" in loud_text) or ("抖动" in loud_text)


def test_ble_connected_line_counts_peripherals_and_categories():
    """The diagnostics' Connected row reports total peripherals plus
    a per-category breakdown. AirPods + 2 audio buds + Magic Keyboard
    counts 'Audio 3 · HID 1'."""
    connected = [
        _ble_dev(identifier=f"aud{i}", services=("110A",), rssi=None,
                 is_connected=True) for i in range(3)
    ] + [
        _ble_dev(identifier="kbd", services=("1812",), rssi=None,
                 is_connected=True),
    ]
    text = _ble_connected_line(connected).plain
    assert "4 peripherals" in text
    assert "Audio 3" in text
    assert "HID 1" in text


# ------------------------------------------------------------------
# BLE detail modal helpers
# ------------------------------------------------------------------


def test_format_duration_short_buckets():
    assert _format_duration_short(0) == "0s"
    assert _format_duration_short(35) == "35s"
    assert _format_duration_short(252) == "4m 12s"
    assert _format_duration_short(3 * 3600 + 7 * 60) == "3h 07m"


def test_format_duration_short_negative_clamps_to_zero():
    """Clock skew can occasionally produce a negative ``last_seen ago``;
    show 0 instead of a confusing minus sign."""
    assert _format_duration_short(-5) == "0s"


def test_free_space_distance_m_at_one_meter_returns_one():
    """RSSI = tx_power means distance ≈ 1 m by definition."""
    d = _free_space_distance_m(-50, -50)
    assert d is not None
    assert 0.99 < d < 1.01


def test_free_space_distance_m_doubles_at_minus_six_db():
    """Free-space loss: every −6 dB ≈ doubling of distance."""
    d = _free_space_distance_m(-50, -56)
    assert d is not None
    assert 1.95 < d < 2.05


def test_free_space_distance_m_zero_rssi_returns_none():
    """RSSI = 0 is a CoreBluetooth sentinel, not a real reading."""
    assert _free_space_distance_m(-50, 0) is None


def test_hex_dump_groups_bytes_in_pairs_and_wraps():
    blob = "4c001006271efe0b8af9"
    out = _hex_dump(blob)
    # 10 bytes / 5 uint16 chunks on one line.
    assert out == "4c00 1006 271e fe0b 8af9"


def test_hex_dump_wraps_at_per_line_threshold():
    # 18 bytes triggers a line break at the 16-byte mark by default.
    blob = "00" * 18
    lines = _hex_dump(blob).splitlines()
    assert len(lines) == 2
    assert lines[0].count(" ") == 7  # 8 uint16 chunks per line
    assert lines[1].startswith("0000")


def test_hex_dump_empty_string_returns_empty():
    assert _hex_dump("") == ""


# ------------------------------------------------------------------
# RSSI sparkline
# ------------------------------------------------------------------


def _t(seconds_offset: int) -> datetime:
    base = datetime(2026, 5, 9, 14, 0, 0, tzinfo=timezone.utc)
    return base + timedelta(seconds=seconds_offset)


def test_rssi_sparkline_empty_history_returns_empty():
    assert _rssi_sparkline([]) == ""


def test_rssi_sparkline_single_sample_returns_empty():
    """One sample isn't a history; rendering ⎯ as a sparkline would
    just be noise."""
    assert _rssi_sparkline([(_t(0), -60)]) == ""


def test_rssi_sparkline_constant_rssi_renders_flat_line():
    """A device sitting still at -60 dBm should not panic-divide;
    return a flat mid-block sequence so the user sees "stable"
    rather than a jagged artifact of integer rounding."""
    samples = [(_t(i), -60) for i in range(5)]
    out = _rssi_sparkline(samples)
    assert len(out) == 5
    assert len(set(out)) == 1  # all same character


def test_rssi_sparkline_maps_extremes_to_top_and_bottom_blocks():
    """Highest RSSI → top block (█), lowest → bottom block (▁)."""
    samples = [(_t(0), -90), (_t(1), -40)]
    out = _rssi_sparkline(samples)
    assert out[0] == "▁"
    assert out[1] == "█"


def test_rssi_sparkline_renders_one_char_per_sample():
    samples = [(_t(i), -60 + i * 3) for i in range(7)]
    out = _rssi_sparkline(samples)
    assert len(out) == 7


# --- view-mode display + tab indicator helpers ----------------------

def test_view_display_name_maps_internal_tokens_to_user_names():
    """Internal mode tokens (wifi/ble/mdns) map to user-facing display
    names (Wi-Fi/BLE/Bonjour) for the header subtitle and tab labels.
    """
    assert _view_display_name("wifi") == "Wi-Fi"
    assert _view_display_name("ble") == "BLE"
    assert _view_display_name("mdns") == "Bonjour"
    # Unknown mode falls through unchanged (defensive for future views).
    assert _view_display_name("future-view") == "future-view"


def test_view_tabs_border_title_lists_all_four_views():
    """The composed Rich markup mentions every view name regardless of
    which one is active — that's the whole point of the always-visible
    tab indicator."""
    for active in ("wifi", "ble", "mdns", "lan"):
        markup = _view_tabs_border_title(active)
        assert "Wi-Fi" in markup
        assert "BLE" in markup
        assert "Bonjour" in markup
        assert "LAN" in markup


def test_view_tabs_border_title_styles_active_distinctly():
    """The active view is bold-cyan; the other views are dim.
    Verified by the Rich-markup tag the helper produces."""
    markup = _view_tabs_border_title("ble")
    # Active label is wrapped in [bold cyan] ... [/].
    assert "[bold cyan]BLE[/]" in markup
    # Inactive labels are wrapped in [dim] ... [/].
    assert "[dim]Wi-Fi[/]" in markup
    assert "[dim]Bonjour[/]" in markup
    assert "[dim]LAN[/]" in markup


def test_view_tabs_border_title_preserves_cycle_order():
    """Tab order matches the `n` cycle order (wifi → ble → mdns → lan)
    so the user can visually predict which view a press lands on."""
    markup = _view_tabs_border_title("wifi")
    assert markup.index("Wi-Fi") < markup.index("BLE")
    assert markup.index("BLE") < markup.index("Bonjour")
    assert markup.index("Bonjour") < markup.index("LAN")


# --- Bonjour service-suffix strip -----------------------------------

def test_strip_service_suffix_strips_known_suffix():
    """The redundant ``.<service-type>.local.`` suffix is removed from
    the display name. Tests every shape zeroconf produces."""
    # Most common: name ends with ``.<full-type>``.
    assert _strip_service_suffix(
        "ccy MBP2024 M4 Office._airplay._tcp.local.",
        "_airplay._tcp.local.",
    ) == "ccy MBP2024 M4 Office"
    # Service type with no trailing dot.
    assert _strip_service_suffix(
        "Printer-X._ipp._tcp.local",
        "_ipp._tcp.local",
    ) == "Printer-X"


def test_strip_service_suffix_leaves_other_names_unchanged():
    """A name that doesn't end with the service suffix passes through
    untouched (defensive for non-standard announce shapes)."""
    assert _strip_service_suffix(
        "Living-Room",
        "_airplay._tcp.local.",
    ) == "Living-Room"
    assert _strip_service_suffix("", "_airplay._tcp.local.") == ""
    assert _strip_service_suffix("Living-Room", "") == "Living-Room"


def test_strip_service_suffix_drops_raop_mac_prefix():
    """RAOP (AirPlay audio) instance names use a
    ``<MAC-as-12-hex>@<friendly>`` format. The MAC prefix is machine-
    only clutter — the friendly half matches the AirPlay sibling row
    for the same speaker, so stripping aligns the two rows."""
    # Full RAOP shape: suffix stripped, then MAC@ stripped.
    assert _strip_service_suffix(
        "0A588A3EBF21@ccy MBP2024 M4 Office._raop._tcp.local.",
        "_raop._tcp.local.",
    ) == "ccy MBP2024 M4 Office"
    # Bare MAC@friendly (no suffix to strip first) also handled.
    assert _strip_service_suffix(
        "00A1B2C3D4E5@Living-Room-Speaker",
        "_raop._tcp.local.",
    ) == "Living-Room-Speaker"


def test_strip_service_suffix_keeps_at_signs_outside_raop():
    """Non-RAOP service types must not lose ``user@host`` style names —
    the MAC strip is gated on both service_type prefix AND a 12-hex
    MAC shape so user-named services pass through."""
    # AirPlay row with an @ in its name (not RAOP, not a MAC pattern)
    # — passes through.
    assert _strip_service_suffix(
        "shared@office._airplay._tcp.local.",
        "_airplay._tcp.local.",
    ) == "shared@office"
    # RAOP service type but the part before @ isn't a 12-hex MAC —
    # leave it alone rather than guessing wrong.
    assert _strip_service_suffix(
        "not-a-mac@Living-Room",
        "_raop._tcp.local.",
    ) == "not-a-mac@Living-Room"


# --- service-types i18n leak (post-merge polish) --------------------

def test_bonjour_diagnostic_service_types_translated_in_zh():
    """The "{n} service types" suffix on the visible-bonjour
    diagnostic line translated correctly under DITING_LANG=zh.
    Previously leaked raw English due to a catalog-key whitespace
    mismatch (call-site used "  ·  {n} service types"; catalog
    key was "{n} service types")."""
    from datetime import datetime, timezone
    from diting import i18n
    from diting.tui import _bonjour_diagnostic_lines

    class _D:
        def __init__(self, vendor, category):
            self.vendor = vendor
            self.category = category

    devices = [
        _D("Apple, Inc.", "AirPlay"),
        _D("Apple, Inc.", "AirPlay audio"),
        _D("Apple, Inc.", "Apple Companion"),
    ]
    saved = i18n.get_lang()
    try:
        i18n.set_lang("zh")
        rows = _bonjour_diagnostic_lines(devices)
        joined = "".join(r.plain for r in rows)
        assert "种服务" in joined
        # The English source phrase must not appear.
        assert "service types" not in joined
    finally:
        i18n.set_lang(saved)


# --- _scan_row_key / _bonjour_row_key -------------------------------

def test_scan_row_key_uses_bssid_when_available():
    """Lowercase, separator-stripped BSSID is the canonical key —
    sort + churn never moves the cursor off the selected AP."""
    r = _scan("40:Fe:95:89:c7:e3")
    assert _scan_row_key(r) == "40fe9589c7e3"


def test_scan_row_key_falls_back_to_ssid_and_channel():
    """When TCC redacts BSSID, the synthetic key uses (ssid, channel)
    so users without Location Services can still navigate."""
    r = _scan(None, ssid="eduroam", channel=36)
    assert _scan_row_key(r) == "eduroam#36"


def test_scan_row_key_handles_hidden_ssid():
    """Empty SSID broadcast (the 802.11 'hidden' bit) with redacted
    BSSID falls back to ``#channel`` — collisions stay rare since
    hidden networks usually only have one BSSID per channel."""
    r = ScanResult(
        ssid=None, bssid=None, rssi_dbm=-70, noise_dbm=-94,
        channel=48, channel_width_mhz=20, channel_band="5 GHz",
        phy_mode=None, security=None, timestamp=datetime.now(),
    )
    assert _scan_row_key(r) == "#48"


def test_bonjour_row_key_combines_name_and_service_type():
    class _D:
        name = "Office HomePod"
        service_type = "_raop._tcp.local."
    assert _bonjour_row_key(_D()) == "Office HomePod._raop._tcp.local."


# --- WifiDetailScreen rendering -------------------------------------

def _wifi_detail_text(scan, *, connection=None, inv=None):
    """Construct a WifiDetailScreen and return the rendered body as a
    plain string. The modal's section helpers append to a Rich Text;
    we read ``.plain`` so tests can substring-match without dealing
    with style spans."""
    screen = WifiDetailScreen(
        scan=scan,
        connection=connection,
        inv=inv if inv is not None else NetworkInventory(aps=()),
    )
    return screen._render_body().plain


def test_wifi_detail_renders_identity_radio_signal_activity_sections():
    """Every always-on section (Identity / Radio / Signal / Activity)
    appears in the rendered body. Beacon IE is opt-in (see its own
    test) so it doesn't have to show up here."""
    r = ScanResult(
        ssid="testnet", bssid="40:fe:95:89:c7:e3",
        rssi_dbm=-58, noise_dbm=-94, channel=48,
        channel_width_mhz=80, channel_band="5 GHz",
        phy_mode="802.11ax", security="WPA2 Personal",
        timestamp=datetime.now(timezone.utc),
    )
    body = _wifi_detail_text(r)
    assert "Identity" in body
    assert "Radio" in body
    assert "Signal" in body
    assert "Activity" in body
    # Core fields render.
    assert "testnet" in body
    assert "40:fe:95:89:c7:e3" in body
    assert "-58 dBm" in body
    assert "WPA2 Personal" in body


def test_wifi_detail_renders_beacon_ie_when_present():
    """Schema-3+ helpers populate `bss_load_pct` / `bss_station_count`
    / 802.11r/k/v Booleans. The modal surfaces the section under a
    "Beacon IE" heading with each populated field labelled."""
    r = ScanResult(
        ssid="x", bssid="aa:bb:cc:dd:ee:01",
        rssi_dbm=-65, noise_dbm=-94, channel=36,
        channel_width_mhz=80, channel_band="5 GHz",
        phy_mode=None, security=None,
        timestamp=datetime.now(timezone.utc),
        bss_load_pct=42, bss_station_count=11,
        supports_802_11r=True, supports_802_11k=True,
        supports_802_11v=False,
    )
    body = _wifi_detail_text(r)
    assert "Beacon IE" in body
    assert "42%" in body
    assert "BSS station count" in body
    assert "802.11r" in body
    assert "802.11v" in body


def test_wifi_detail_omits_beacon_ie_when_all_fields_absent():
    """Older helpers (schema < 3) ship neither beacon-IE load nor
    roam-capability flags. The modal MUST omit the entire Beacon IE
    section rather than render a heading with no rows under it."""
    r = ScanResult(
        ssid="x", bssid="aa:bb:cc:dd:ee:01",
        rssi_dbm=-65, noise_dbm=-94, channel=36,
        channel_width_mhz=80, channel_band="5 GHz",
        phy_mode=None, security=None,
        timestamp=datetime.now(timezone.utc),
    )
    body = _wifi_detail_text(r)
    assert "Beacon IE" not in body


def test_wifi_detail_redacted_bssid_renders_tcc_hint_and_omits_vendor():
    """When BSSID is None (CoreWLAN TCC-redacted scan), the Identity
    section shows the user-facing hint instead of going silent, and
    the OUI-derived vendor row is absent (no BSSID = no OUI)."""
    r = ScanResult(
        ssid="testnet", bssid=None,
        rssi_dbm=-58, noise_dbm=-94, channel=48,
        channel_width_mhz=80, channel_band="5 GHz",
        phy_mode=None, security=None,
        timestamp=datetime.now(timezone.utc),
    )
    body = _wifi_detail_text(r)
    assert "redacted by TCC" in body
    assert "Location Services" in body
    # No vendor row, because we don't have an OUI to look up.
    # The Identity heading appears; the literal "vendor" label
    # MUST NOT (we use a single ``  vendor`` field row).
    assert "  vendor" not in body


def test_wifi_detail_renders_ap_name_when_inventory_matches():
    """A BSSID listed in aps.yaml surfaces as an "AP name" row in the
    Identity section. The modal is the user's most likely path to
    re-attach a label to a row they recognise."""
    bssid = "40:fe:95:89:c7:e3"
    inv = NetworkInventory(aps=(
        APEntry(name="kitchen ceiling", mgmt_mac=bssid),
    ))
    r = ScanResult(
        ssid="x", bssid=bssid,
        rssi_dbm=-58, noise_dbm=-94, channel=48,
        channel_width_mhz=80, channel_band="5 GHz",
        phy_mode=None, security=None,
        timestamp=datetime.now(timezone.utc),
    )
    body = _wifi_detail_text(r, inv=inv)
    assert "AP name" in body
    assert "kitchen ceiling" in body


def test_wifi_detail_omits_ap_name_row_when_inventory_misses():
    """No aps.yaml entry → the row is absent entirely, not "—". This
    keeps the Identity section a tight summary instead of advertising
    that a field exists but is empty."""
    r = ScanResult(
        ssid="x", bssid="40:fe:95:89:c7:e3",
        rssi_dbm=-58, noise_dbm=-94, channel=48,
        channel_width_mhz=80, channel_band="5 GHz",
        phy_mode=None, security=None,
        timestamp=datetime.now(timezone.utc),
    )
    body = _wifi_detail_text(r)
    assert "AP name" not in body


# --- WifiDetailScreen enrichment sections ---------------------------
#
# Each enrichment section is omitted when its underlying ref is None
# or its data is empty. The tests assert both halves of that contract
# so a future refactor can't silently leak placeholder rows.

def _wifi_detail_with(
    scan, *, connection=None, inv=None,
    environment_monitor=None, event_ring=None, latest_scan=None,
):
    from diting.tui import WifiDetailScreen
    screen = WifiDetailScreen(
        scan=scan,
        connection=connection,
        inv=inv if inv is not None else NetworkInventory(aps=()),
        environment_monitor=environment_monitor,
        event_ring=event_ring,
        latest_scan=latest_scan,
    )
    return screen._render_body().plain


def test_wifi_detail_signal_history_omitted_when_no_env_monitor():
    """Section is gated on the env-monitor ref. Without it we have no
    history data; the section MUST NOT render an empty placeholder."""
    r = _scan("40:fe:95:89:c7:e3")
    body = _wifi_detail_with(r)
    assert "Signal history" not in body


def test_wifi_detail_signal_history_omitted_when_under_two_samples():
    """Single RSSI sample is not a "history" worth drawing. _rssi_sparkline
    itself returns "" for n<2; the modal MUST treat that as "omit", not
    "render header + blank line"."""
    from diting.environment import EnvironmentMonitor
    monitor = EnvironmentMonitor(inventory=NetworkInventory(aps=()))
    monitor.ingest("40:fe:95:89:c7:e3", -55, datetime.now())
    r = _scan("40:fe:95:89:c7:e3")
    body = _wifi_detail_with(r, environment_monitor=monitor)
    assert "Signal history" not in body


def test_wifi_detail_signal_history_renders_sparkline_and_sigma():
    """With ≥2 samples the section renders. We don't assert the exact
    sparkline glyphs (Unicode block characters vary per terminal) — we
    just confirm the header + sample-count summary appear. Uses naive
    datetimes to match the monitor's internal `datetime.now()` calls."""
    from diting.environment import EnvironmentMonitor
    monitor = EnvironmentMonitor(inventory=NetworkInventory(aps=()))
    now = datetime.now()
    for offset, rssi in enumerate([-58, -57, -56, -55]):
        monitor.ingest(
            "40:fe:95:89:c7:e3", rssi,
            now - timedelta(seconds=20 - offset * 5),
        )
    r = _scan("40:fe:95:89:c7:e3")
    body = _wifi_detail_with(r, environment_monitor=monitor)
    assert "Signal history" in body
    assert "4 samples" in body


def test_wifi_detail_siblings_omitted_when_singleton():
    """An AP with no sibling radios in latest_scan is a singleton.
    The section MUST omit rather than render a header with no rows."""
    r = _scan("40:fe:95:89:c7:e3")
    body = _wifi_detail_with(r, latest_scan=[r])
    assert "Same physical AP" not in body


def test_wifi_detail_siblings_renders_when_inv_groups_radios():
    """When inventory groups the inspected BSSID with another radio in
    latest_scan, that radio appears in the section. The grouping rule
    is `NetworkInventory.is_same_ap` — we use the auto-cluster heuristic
    (matching mid-4 octets) since neither BSSID is in aps.yaml."""
    me = _scan("40:fe:95:8a:3c:58", channel=48)
    sibling = _scan("40:fe:95:8a:3c:54", channel=6)  # same mid-4
    body = _wifi_detail_with(me, latest_scan=[me, sibling])
    assert "Same physical AP" in body
    assert "40:fe:95:8a:3c:54" in body


def test_wifi_detail_roam_history_omitted_when_ring_empty():
    """No event ring → no section. Empty event ring → also no section
    (no RoamEvents to match this BSSID)."""
    from diting.events import EventRing
    r = _scan("40:fe:95:8a:3c:58")
    body = _wifi_detail_with(r, event_ring=EventRing())
    assert "Roam history" not in body


def test_wifi_detail_roam_history_renders_matching_events_newest_first():
    """RoamEvents whose previous_bssid OR new_bssid matches the
    inspected BSSID appear in the section; non-matching events are
    filtered out; newest-first ordering follows `EventRing.snapshot`."""
    from diting.events import EventRing
    ring = EventRing()
    now = datetime.now(timezone.utc)
    # 1st: roam INTO this BSSID
    ring.push(RoamEvent(
        timestamp=now - timedelta(seconds=120),
        previous_bssid="40:fe:95:8a:3c:5a", previous_channel=6,
        new_bssid="40:fe:95:8a:3c:58", new_channel=48,
    ))
    # 2nd: unrelated roam (shouldn't appear)
    ring.push(RoamEvent(
        timestamp=now - timedelta(seconds=60),
        previous_bssid="aa:bb:cc:dd:ee:ff", previous_channel=11,
        new_bssid="aa:bb:cc:dd:ee:f0", new_channel=36,
    ))
    # 3rd: roam OUT of this BSSID
    ring.push(RoamEvent(
        timestamp=now - timedelta(seconds=10),
        previous_bssid="40:fe:95:8a:3c:58", previous_channel=48,
        new_bssid="40:fe:95:8a:3c:5a", new_channel=6,
    ))
    r = _scan("40:fe:95:8a:3c:58")
    body = _wifi_detail_with(r, event_ring=ring)
    assert "Roam history" in body
    # Both matching events render; the unrelated one does not.
    assert "40:fe:95:8a:3c:5a" in body
    assert "aa:bb:cc:dd:ee:ff" not in body


def test_wifi_detail_recommendation_omitted_when_not_associated():
    """The recommendation only makes sense when the user is currently
    *on* this BSSID — inspecting a non-associated row, the user isn't
    going to "switch away" from a row they aren't on. Section omits."""
    r = _scan("40:fe:95:8a:3c:58", ssid="home", rssi=-55)
    better = _scan("40:fe:95:8a:3c:5a", ssid="home", rssi=-30)
    conn = _conn(bssid="aa:bb:cc:dd:ee:ff", ssid="home", rssi=-70)
    body = _wifi_detail_with(r, connection=conn, latest_scan=[r, better])
    assert "Recommendation" not in body


def test_wifi_detail_recommendation_renders_for_associated_row_with_better_candidate():
    """When the inspected row IS the connection's BSSID AND a same-SSID
    candidate is ≥15 dB stronger, the section renders with the +N dB delta."""
    weak = _scan("40:fe:95:8a:3c:58", ssid="home", rssi=-75, channel=48)
    strong = _scan("40:fe:95:8a:3c:5a", ssid="home", rssi=-50, channel=6)
    conn = _conn(bssid="40:fe:95:8a:3c:58", ssid="home", rssi=-75, channel=48)
    body = _wifi_detail_with(weak, connection=conn, latest_scan=[weak, strong])
    assert "Recommendation" in body
    # The stronger candidate's BSSID shows up; delta is +25 dB.
    assert "40:fe:95:8a:3c:5a" in body
    assert "+25" in body


def test_wifi_detail_recommendation_omitted_when_no_clearly_better():
    """A 5 dB delta is below the 15 dB threshold — nothing to recommend."""
    weak = _scan("40:fe:95:8a:3c:58", ssid="home", rssi=-70)
    slightly_better = _scan("40:fe:95:8a:3c:5a", ssid="home", rssi=-65)
    conn = _conn(bssid="40:fe:95:8a:3c:58", ssid="home", rssi=-70)
    body = _wifi_detail_with(
        weak, connection=conn, latest_scan=[weak, slightly_better],
    )
    assert "Recommendation" not in body


# --- BonjourDetailScreen rendering ----------------------------------

class _BD:
    """Lightweight stand-in for BonjourDevice. We don't construct the
    real dataclass to avoid coupling these tests to the mdns module's
    import surface; the modal only reads attribute names."""

    def __init__(
        self, *, name="Office HomePod._raop._tcp.local.",
        service_type="_raop._tcp.local.",
        host="HomePod-Office.local.",
        port=7000, addresses=("192.168.1.42",),
        txt=None, vendor="Apple, Inc.", category="AirPlay audio",
        vendor_trace=None,
        first_seen=None, last_seen=None,
    ):
        self.name = name
        self.service_type = service_type
        self.host = host
        self.port = port
        self.addresses = addresses
        self.txt = txt or {}
        self.vendor = vendor
        self.category = category
        self.vendor_trace = vendor_trace
        now = datetime.now(timezone.utc)
        self.first_seen = first_seen or (now - timedelta(minutes=12))
        self.last_seen = last_seen or (now - timedelta(seconds=3))


def _bonjour_detail_text(device):
    screen = BonjourDetailScreen(device=device)
    return screen._render_body().plain


def test_bonjour_detail_renders_identity_network_txt_activity_sections():
    """Every section renders, with TXT records present when the
    device carries them."""
    d = _BD(txt={"md": "AppleTV5,3", "am": "AppleTV5,3"})
    body = _bonjour_detail_text(d)
    assert "Identity" in body
    assert "Network" in body
    assert "TXT records" in body
    assert "Activity" in body
    # Core fields render.
    assert "Office HomePod" in body
    assert "192.168.1.42" in body
    assert "AppleTV5,3" in body


def test_bonjour_detail_folds_long_txt_values():
    """Opaque blob values (AirPlay `pk`, HomeKit pairing IDs) are
    folded to a `<N-byte payload>` placeholder + a one-line hex
    preview so 30-key receivers don't blow out the modal height."""
    long_value = "a" * 200  # > 60-char threshold
    d = _BD(txt={"pk": long_value})
    body = _bonjour_detail_text(d)
    assert "<200-byte payload>" in body
    # First 16 bytes of "aaaa…" → 16 × 0x61.
    assert "61616161" in body


def test_bonjour_detail_omits_txt_section_when_empty():
    """A service with no TXT (rare but valid) gets no TXT section —
    same omit-when-empty discipline as Beacon IE."""
    d = _BD(txt={})
    body = _bonjour_detail_text(d)
    assert "TXT records" not in body


def test_bonjour_detail_renders_translated_category_when_known():
    """Categories with an i18n catalog entry render via t() so the
    user sees the localised label, not the internal English string."""
    from diting import i18n
    d = _BD(category="AirPlay audio")
    saved = i18n.get_lang()
    try:
        i18n.set_lang("zh")
        body = _bonjour_detail_text(d)
        assert "AirPlay 音频" in body
    finally:
        i18n.set_lang(saved)


def test_bonjour_detail_omits_category_row_when_unknown():
    """A service with no recognised category renders just the raw
    service-type token; the ``category`` label row is absent. Same
    omit-when-empty discipline as Beacon IE."""
    d = _BD(category=None)
    body = _bonjour_detail_text(d)
    # `_label`'s row is two-space-indented then padded; matching the
    # exact field-label prefix avoids a false positive from a section
    # header that happens to contain "category" in some future revision.
    assert "  category" not in body


# --- BonjourDetailScreen enrichment sections ------------------------

def _bonjour_detail_with(device, *, latest_mdns=None):
    """Construct a BonjourDetailScreen with the Stage-2 kwargs and
    return the rendered body as a plain string. Mirrors the existing
    `_bonjour_detail_text` helper but lets us thread the new context
    refs in."""
    screen = BonjourDetailScreen(
        device=device,
        latest_mdns=latest_mdns,
    )
    return screen._render_body().plain


def test_bonjour_detail_vendor_trace_annotation_appears_when_set():
    """Stage 2: when `vendor_trace` is set, the Identity section's
    vendor row appends ` · via <trace>`. Pure UX annotation — the
    underlying vendor field stays the same."""
    d = _BD(vendor="Apple, Inc.", vendor_trace="hostname-pattern")
    body = _bonjour_detail_text(d)
    assert "Apple, Inc." in body
    assert "via hostname-pattern" in body


def test_bonjour_detail_vendor_trace_omitted_when_none():
    """No `vendor_trace` set (legacy `_BD` default) → vendor row
    renders cleanly without the trace annotation."""
    d = _BD(vendor="Apple, Inc.", vendor_trace=None)
    body = _bonjour_detail_text(d)
    assert "Apple, Inc." in body
    assert "via " not in body


def test_bonjour_detail_other_services_omitted_when_lone_host():
    """The Other-services section is gated on at least one other
    BonjourDevice sharing the host. With nothing else in
    latest_mdns the section MUST omit."""
    d = _BD(host="Living-Room.local.", service_type="_raop._tcp.local.")
    body = _bonjour_detail_with(d, latest_mdns=[d])
    assert "Other services on this host" not in body


def test_bonjour_detail_other_services_lists_same_host_categories():
    """When latest_mdns contains additional services on the same host,
    they render newest-first with their category + age."""
    now = datetime.now(timezone.utc)
    primary = _BD(
        name="Office._raop._tcp.local.",
        service_type="_raop._tcp.local.",
        host="ccy-MBP2024-M4.local.",
        category="AirPlay audio",
        last_seen=now - timedelta(seconds=15),
    )
    sibling_a = _BD(
        name="Office._airplay._tcp.local.",
        service_type="_airplay._tcp.local.",
        host="ccy-MBP2024-M4.local.",
        category="AirPlay",
        last_seen=now - timedelta(seconds=5),
    )
    sibling_b = _BD(
        name="Office._companion-link._tcp.local.",
        service_type="_companion-link._tcp.local.",
        host="ccy-MBP2024-M4.local.",
        category="Apple Companion",
        last_seen=now - timedelta(seconds=20),
    )
    body = _bonjour_detail_with(
        primary, latest_mdns=[primary, sibling_a, sibling_b],
    )
    assert "Other services on this host" in body
    # Both siblings' categories appear; primary itself is excluded.
    assert "AirPlay" in body
    assert "Apple Companion" in body


def test_bonjour_detail_other_services_falls_back_to_addresses():
    """When `host` is None on either side, the matcher falls back to
    intersecting the `addresses` tuple. Covers anonymous announcers
    (some printers / IoT lack a hostname)."""
    primary = _BD(
        name="Anon._http._tcp.local.",
        service_type="_http._tcp.local.",
        host=None,
        addresses=("10.0.0.42",),
        category="HTTP server",
    )
    sibling = _BD(
        name="Anon._ipp._tcp.local.",
        service_type="_ipp._tcp.local.",
        host=None,
        addresses=("10.0.0.42",),
        category="Printer (IPP)",
    )
    body = _bonjour_detail_with(primary, latest_mdns=[primary, sibling])
    assert "Other services on this host" in body
    assert "Printer (IPP)" in body


def test_bonjour_detail_decoded_txt_appears_for_known_keys():
    """Stage 2: well-known TXT keys (model / osxvers / srcvers /
    deviceid) get decoded into named fields. The raw table renders
    only keys without a registered decoder."""
    d = _BD(txt={
        "model": "MacBookPro18,1",
        "osxvers": "26",
        "srcvers": "405.6",
        "deviceid": "aa:bb:cc:dd:ee:ff",
        "unknown_key": "some-value",
    })
    body = _bonjour_detail_text(d)
    # Decoded fields render with their friendly label.
    assert "MacBook Pro 16-inch (M1 Pro, 2021)" in body
    assert "Tahoe" in body  # macOS 26
    assert "405.6" in body  # firmware passthrough
    # Decoded keys SHALL NOT also show in the raw table.
    # The raw table prefixes the key with two spaces + padding;
    # exact prefix `  model` would be the raw row.
    assert "  model               MacBookPro18,1" not in body
    # Unknown key still shows up in raw.
    assert "unknown_key" in body
    assert "some-value" in body


def test_bonjour_detail_decoded_txt_skipped_when_no_known_keys():
    """When TXT has only unknown keys, the Decoded sub-block is empty
    (no spurious section header). The raw table renders normally."""
    d = _BD(txt={"foo": "bar", "baz": "qux"})
    body = _bonjour_detail_text(d)
    assert "foo" in body
    assert "baz" in body
    # Decoder-only labels do NOT leak when their source keys are absent.
    assert "macOS" not in body
    assert "firmware" not in body


# --- Cross-surface correlation (stage 3) ----------------------------
#
# Rule 1 (IP match) has a clean fixture: pass a Connection whose
# ip_address matches one of the BonjourDevice's addresses. Rules 2
# (TXT deviceid → BLE manufacturer_hex byte-search) and 3 (hostname
# pattern + Apple-Proximity BLE) need fake BLEDevice-like objects;
# we stand them in with a small dataclass-shaped stub to avoid
# coupling tests to BLEDevice's frozen-slot internals.

class _BLERow:
    """Stand-in for BLEDevice carrying just the fields the cross-
    surface rules read. Test-local because we don't need the rest of
    BLEDevice's schema-4 plumbing."""

    def __init__(
        self, *,
        identifier="11111111-2222-3333-4444-555555555555",
        name=None, vendor=None, services=(),
        rssi_dbm=-55, manufacturer_hex=None, type=None,
    ):
        self.identifier = identifier
        self.name = name
        self.vendor = vendor
        self.services = services
        self.rssi_dbm = rssi_dbm
        self.manufacturer_hex = manufacturer_hex
        self.type = type


def _bonjour_detail_cross_surface(
    device, *, latest_ble=None, latest_connection=None,
):
    from diting.tui import BonjourDetailScreen
    screen = BonjourDetailScreen(
        device=device,
        latest_ble=latest_ble,
        latest_connection=latest_connection,
    )
    return screen._render_body().plain


def test_bonjour_cross_surface_omitted_when_no_refs():
    """No connection, no BLE list → no cross-surface section. Matches
    the omit-when-empty discipline of the other enrichment sections."""
    d = _BD()
    body = _bonjour_detail_cross_surface(d)
    assert "Cross-surface" not in body


def test_bonjour_cross_surface_local_mac_when_ip_matches():
    """Rule 1: the Bonjour announce carries the local Mac's IP → the
    section renders ``local Mac (this host is you)``."""
    d = _BD(host="ccy-MBP2024.local.", addresses=("192.168.1.42",))
    conn = _conn(rssi=-50)
    # Real Connection objects have `ip_address` attached; the helper
    # constructs one without it, so set it explicitly.
    conn = Connection(
        ssid=conn.ssid, bssid=conn.bssid, rssi_dbm=conn.rssi_dbm,
        noise_dbm=conn.noise_dbm, tx_rate_mbps=conn.tx_rate_mbps,
        channel=conn.channel, channel_width_mhz=conn.channel_width_mhz,
        channel_band=conn.channel_band, phy_mode=conn.phy_mode,
        security=conn.security, mcs_index=conn.mcs_index,
        nss=conn.nss, timestamp=conn.timestamp,
        ip_address="192.168.1.42",
    )
    body = _bonjour_detail_cross_surface(d, latest_connection=conn)
    assert "Cross-surface" in body
    assert "local Mac" in body


def test_bonjour_cross_surface_local_mac_omitted_when_ips_disagree():
    """Rule 1 requires an actual IP match. A different host's IP MUST
    NOT trigger the 'this host is you' line."""
    d = _BD(addresses=("192.168.1.99",))
    conn = Connection(
        ssid="x", bssid=None, rssi_dbm=-50, noise_dbm=-95,
        tx_rate_mbps=None, channel=48, channel_width_mhz=80,
        channel_band="5 GHz", phy_mode=None, security=None,
        mcs_index=None, nss=None, timestamp=datetime.now(timezone.utc),
        ip_address="192.168.1.42",
    )
    body = _bonjour_detail_cross_surface(d, latest_connection=conn)
    assert "local Mac" not in body


def test_bonjour_cross_surface_ble_via_deviceid_finds_mac_in_manufacturer_hex():
    """Rule 2: a TXT ``deviceid`` MAC parses canonically and its hex
    bytes appear inside a BLE row's manufacturer_hex. Renders the
    matched row by its name."""
    mac = "aa:bb:cc:dd:ee:ff"
    d = _BD(txt={"deviceid": mac})
    ble = _BLERow(
        name="My Printer",
        # MAC bytes embedded in manufacturer data ("aabbccddeeff").
        manufacturer_hex="0049" + "aabbccddeeff" + "0000",
        rssi_dbm=-62,
    )
    body = _bonjour_detail_cross_surface(d, latest_ble=[ble])
    assert "Cross-surface" in body
    assert "My Printer" in body
    assert "-62 dBm" in body


def test_bonjour_cross_surface_ble_via_deviceid_omitted_when_no_match():
    """Rule 2 doesn't fire when the BLE list has no row whose
    manufacturer_hex contains the TXT MAC bytes."""
    d = _BD(txt={"deviceid": "aa:bb:cc:dd:ee:ff"})
    ble = _BLERow(name="Unrelated", manufacturer_hex="004c1234abcd")
    body = _bonjour_detail_cross_surface(d, latest_ble=[ble])
    assert "also on BLE" not in body


def test_bonjour_cross_surface_ble_via_hostname_pattern_hedges_likely():
    """Rule 3: an Apple-named host + a nearby Apple-Proximity-class
    BLE row → render the hedge ``likely the same device as BLE row
    <short-id>``. The hedge is required because hostname-pattern
    correlation is probabilistic."""
    d = _BD(
        host="iPhone.local.",   # matches _NAME_PATTERN_VENDORS Apple rule
        txt={},
    )
    ble = _BLERow(
        identifier="11111111-2222-3333-4444-555555555555",
        type="Nearby Info",
        rssi_dbm=-44,
    )
    body = _bonjour_detail_cross_surface(d, latest_ble=[ble])
    assert "Cross-surface" in body
    assert "likely" in body
    # The short-id is the first 8 chars of the identifier.
    assert "11111111" in body


def test_bonjour_cross_surface_ble_via_hostname_skipped_for_non_apple_host():
    """Rule 3 only fires when the hostname pattern resolves to Apple.
    A generic hostname → no rule 3 match even with Apple-Proximity
    BLE peers nearby (they could be anyone else's iPhone)."""
    d = _BD(host="random-printer-2391.local.", txt={})
    ble = _BLERow(type="Nearby Info", rssi_dbm=-44)
    body = _bonjour_detail_cross_surface(d, latest_ble=[ble])
    assert "Cross-surface" not in body

# --- BLEDetailScreen rendering --------------------------------------


def _ble_detail_text(device, history=None):
    """Construct a BLEDetailScreen and return the rendered body as a
    plain string. Mirrors `_wifi_detail_text` / `_bonjour_detail_text`.
    """
    from diting.tui import BLEDetailScreen
    screen = BLEDetailScreen(
        device=device,
        history=history,
    )
    return screen._render_body().plain


def test_ble_detail_services_empty_state_has_no_trailing_emdash():
    """`_section_services` used to call `_label(name, None)` which
    appends an em-dash for "no value"; the result was the visible
    string `(none advertised)—`. Now it renders the placeholder as a
    standalone line and no em-dash should appear on that line."""
    d = _ble_dev(services=())  # no advertised services
    body = _ble_detail_text(d)
    assert "(none advertised)" in body
    # Find the line carrying the placeholder and assert no em-dash
    # appears on it. (Em-dashes might exist on OTHER lines, e.g.
    # the Identity 'type —' row when type is None — those are
    # legitimately label-with-empty-value.)
    placeholder_lines = [
        line for line in body.splitlines() if "(none advertised)" in line
    ]
    assert placeholder_lines
    assert all("—" not in line for line in placeholder_lines)


def test_ble_detail_manufacturer_empty_state_has_no_trailing_emdash():
    """Same em-dash regression on `_section_manufacturer_data`. The
    section only renders when type or device_class is non-None (else
    the caller skips it); we set device_class to trigger entry, leave
    vendor_id / manufacturer_hex None to hit the placeholder branch."""
    d = _ble_dev(
        vendor=None, vendor_id=None,
        device_class="iPhone",
    )
    body = _ble_detail_text(d)
    assert "(no manufacturer-specific data)" in body
    placeholder_lines = [
        line for line in body.splitlines()
        if "(no manufacturer-specific data)" in line
    ]
    assert placeholder_lines
    assert all("—" not in line for line in placeholder_lines)


def test_ble_detail_extra_uuids_empty_state_has_no_trailing_emdash():
    """The Extra UUID lists section is skipped entirely when both
    solicited and overflow lists are empty. No heading orphan, no
    label/em-dash artefact."""
    d = _ble_dev()  # default has no solicited / overflow UUIDs
    body = _ble_detail_text(d)
    assert "Extra UUID lists" not in body


# --- ConnectionPanel Tx Rate (idle) annotation ----------------------


def _render_connection_panel_text(conn, inv=None):
    """Construct a ConnectionPanel, call its `_paint` directly, and
    capture whatever was passed to `self.update`. Returns the plain
    text of the rendered Group."""
    from diting.tui import ConnectionPanel
    from diting.network import NetworkInventory
    panel = ConnectionPanel()
    captured: list = []
    panel.update = lambda renderable: captured.append(renderable)  # type: ignore[assignment]
    panel._paint(conn, inv or NetworkInventory(aps=()))
    assert captured, "panel._paint did not call self.update"
    rendered = captured[-1]
    # The renderable is a Rich Group of Text rows. Flatten it to text.
    parts: list[str] = []
    for row in getattr(rendered, "renderables", [rendered]):
        if hasattr(row, "plain"):
            parts.append(row.plain)
        else:
            parts.append(str(row))
    return "\n".join(parts)


def _conn_full(**overrides):
    """Connection factory for ConnectionPanel tests — distinct from
    the smaller `_conn` factory at the top of this file (which is
    optimised for merge / link-score tests). Renamed to avoid
    silently shadowing it at module scope."""
    from diting.models import Connection
    base = dict(
        ssid="tedo_5G",
        bssid="40:fe:95:8a:3c:58",
        rssi_dbm=-74,
        noise_dbm=-94,
        tx_rate_mbps=144.0,
        channel=40,
        channel_width_mhz=80,
        channel_band="5 GHz",
        phy_mode="802.11ax",
        security="WPA2 Personal",
        mcs_index=3,
        nss=1,
        timestamp=datetime(2026, 5, 17, 14, 5, tzinfo=timezone.utc),
        interface_mac="84:2f:57:9b:15:59",
        country_code="CN",
        ip_address="192.168.124.5",
        router_ip="192.168.124.1",
        max_link_speed_mbps=867,
        tx_rate_idle=False,
    )
    base.update(overrides)
    return Connection(**base)


def test_connection_panel_renders_tx_idle_annotation():
    """`Connection.tx_rate_idle=True` makes the Tx / Max row append
    " (idle)" after the Tx value so the field reads
    `144.0 Mbps (idle)  /  867 Mbps`. Stops the flicker between
    `144 Mbps` and `n/a` on a stable association."""
    body = _render_connection_panel_text(_conn_full(tx_rate_idle=True))
    assert "(idle)" in body
    assert "144.0 Mbps" in body


def test_connection_panel_no_idle_annotation_when_flag_false():
    body = _render_connection_panel_text(_conn_full(tx_rate_idle=False))
    assert "(idle)" not in body
    assert "144.0 Mbps" in body


def test_connection_panel_hides_max_when_tx_exceeds_it():
    """CoreWLAN's `maximumLinkSpeed()` returns stale / under-reported
    values on macOS 26; surfacing both Tx and Max when Max < Tx
    reads as nonsense (the radio cannot transmit faster than its
    negotiated maximum). The renderer drops the Max half in that
    case."""
    body = _render_connection_panel_text(_conn_full(
        tx_rate_mbps=286.0, max_link_speed_mbps=229,
    ))
    assert "286.0 Mbps" in body
    # The trailing `/ <smaller> Mbps` segment is omitted entirely.
    assert "229 Mbps" not in body
    assert "286.0 Mbps  /  229 Mbps" not in body


def test_connection_panel_shows_both_when_max_ge_tx():
    """Legacy path: Max >= Tx renders both numbers, slash-separated."""
    body = _render_connection_panel_text(_conn_full(
        tx_rate_mbps=144.0, max_link_speed_mbps=867,
    ))
    assert "144.0 Mbps" in body
    assert "867 Mbps" in body


def test_connection_panel_shows_tx_only_when_max_is_none():
    """Pre-existing fallback: Max unknown renders `n/a` after Tx."""
    body = _render_connection_panel_text(_conn_full(
        tx_rate_mbps=144.0, max_link_speed_mbps=None,
    ))
    assert "144.0 Mbps" in body
    assert "n/a" in body


# --- BonjourPanel by-host mode + diagnostics label parity -----------


def _bd_mock(*, vendor, name, host, category, service_type, last_seen,
             addresses=()):
    """Minimal BonjourDevice-shaped object for panel-mode tests.

    A real `BonjourDevice` has many more fields; the renderer touches
    just `vendor / name / host / category / service_type / last_seen`
    (and `addresses` as a fallback host key), so a lightweight namespace
    is enough."""
    from types import SimpleNamespace
    return SimpleNamespace(
        vendor=vendor,
        name=name,
        host=host,
        category=category,
        service_type=service_type,
        last_seen=last_seen,
        addresses=tuple(addresses),
    )


def test_bonjour_panel_by_host_mode_folds_services_alphabetically():
    """A host that announces multiple services collapses to one row
    whose services column starts with the alphabetically-first short
    name. The services-column width can truncate the tail; the prefix
    order is the contract."""
    from diting.tui import _bonjour_by_host_rows
    now = datetime(2026, 5, 17, 14, 5, tzinfo=timezone.utc)
    # Two short categories that both fit so we can assert full strings
    # without the column truncating either.
    base = dict(
        vendor="Apple, Inc.", name="Blue Pod._airplay._tcp.local.",
        host="Blue-Pod.local.", last_seen=now,
    )
    devs = [
        _bd_mock(category="HomeKit",
                 service_type="_hap._tcp.local.", **base),
        _bd_mock(category="AirPlay",
                 service_type="_airplay._tcp.local.", **base),
    ]
    rows = _bonjour_by_host_rows(devs, now)
    assert len(rows) == 1
    text, key = rows[0]
    assert key == "Blue-Pod"
    body = text.plain
    # Alphabetical: AirPlay before HomeKit.
    air_idx = body.index("AirPlay")
    homekit_idx = body.index("HomeKit")
    assert air_idx < homekit_idx


def test_bonjour_panel_by_host_multiple_hosts_freshest_first():
    """`by-host` mode sorts rows newest-freshest-host first so a
    re-advertising HomePod surfaces to the top of the panel."""
    from diting.tui import _bonjour_by_host_rows
    base_now = datetime(2026, 5, 17, 14, 5, tzinfo=timezone.utc)
    older = _bd_mock(
        vendor="Apple, Inc.", name="Red Pod._airplay._tcp.local.",
        host="Red-Pod.local.", category="AirPlay",
        service_type="_airplay._tcp.local.",
        last_seen=base_now - timedelta(seconds=120),
    )
    newer = _bd_mock(
        vendor="Apple, Inc.", name="Blue Pod._airplay._tcp.local.",
        host="Blue-Pod.local.", category="AirPlay",
        service_type="_airplay._tcp.local.",
        last_seen=base_now,
    )
    rows = _bonjour_by_host_rows([older, newer], base_now)
    assert [k for _, k in rows] == ["Blue-Pod", "Red-Pod"]


def test_bonjour_panel_by_host_truncates_long_services_with_ellipsis():
    """A host with many service announces produces a folded services
    string longer than the column width; `fit_cells` truncates it with
    an ellipsis instead of overflowing into the next column."""
    from diting.tui import _bonjour_by_host_rows, _COL_MDNS_SERVICES
    now = datetime(2026, 5, 17, 14, 5, tzinfo=timezone.utc)
    long_cats = [
        "AirPlay", "AirPlay audio", "Apple Companion",
        "HomeKit", "Printer", "File share", "Remote audio",
    ]
    devs = [
        _bd_mock(
            vendor="Apple, Inc.",
            name=f"Pod._svc{i}._tcp.local.",
            host="Pod.local.",
            category=cat,
            service_type=f"_svc{i}._tcp.local.",
            last_seen=now,
        )
        for i, cat in enumerate(long_cats)
    ]
    rows = _bonjour_by_host_rows(devs, now)
    assert len(rows) == 1
    body = rows[0][0].plain
    # The full joined string would be > 60 chars; the column is
    # ~16 cells. Truncated form ends with an ellipsis.
    assert "…" in body


def test_bonjour_panel_s_key_cycles_modes_in_app_state():
    """The app-level state cycles `service → by-host → service` when
    the active view is `mdns`. This test exercises the state-machine
    half of the binding without spinning up Textual's full app loop;
    the full keystroke path is covered by the snapshot regression."""
    from diting.tui import DitingApp

    class _StubBackend:
        def get_connection(self): return None
        def scan(self): return []
        def force_reroam(self): return True

    app = DitingApp(_StubBackend(), inv=None)
    app._view_mode = "mdns"
    assert app._bonjour_sort_mode == "service"
    # Patch out the refresh; we only care about state, not Textual
    # query_one calls.
    app._refresh_mdns_panel = lambda: None
    app._build_subtitle = lambda: ""
    app.action_cycle_sort()
    assert app._bonjour_sort_mode == "by-host"
    app.action_cycle_sort()
    assert app._bonjour_sort_mode == "service"


def test_bonjour_panel_s_key_in_wifi_view_does_not_touch_bonjour_mode():
    """Pressing `s` while on the Wi-Fi view cycles `_sort_mode`
    (signal ↔ ap), NOT the Bonjour-side mode. Keeps the two cycles
    independent."""
    from diting.tui import DitingApp

    class _StubBackend:
        def get_connection(self): return None
        def scan(self): return []
        def force_reroam(self): return True

    app = DitingApp(_StubBackend(), inv=None)
    app._view_mode = "wifi"
    app._refresh_scan_panel = lambda: None
    app._build_subtitle = lambda: ""
    before = app._bonjour_sort_mode
    app.action_cycle_sort()
    assert app._bonjour_sort_mode == before


def test_mdns_diagnostics_top_vendors_uses_unknown_label():
    """The "Top vendors" line labels the unresolved bucket as
    `(unknown) N` instead of `? N` so it matches the column
    placeholder and reads as a sensible English sentence."""
    from diting.tui import _bonjour_diagnostic_lines

    class _D:
        def __init__(self, vendor, category):
            self.vendor = vendor
            self.category = category

    devices = (
        [_D("Apple, Inc.", "AirPlay") for _ in range(16)]
        + [_D(None, "HTTP") for _ in range(5)]
    )
    rows = _bonjour_diagnostic_lines(devices)
    joined = "".join(r.plain for r in rows)
    assert "(unknown) 5" in joined
    # The literal `?` glyph must not appear in this bucket's label.
    assert "? 5" not in joined


# --- LAN inventory rendering ----------------------------------------

def _lan_host(
    *,
    mac="aa:bb:cc:11:22:33",
    ip="192.168.1.10",
    vendor="Apple, Inc.",
    vendor_raw=None,
    bonjour_name=None,
    bonjour_services=(),
    hostname=None,
    is_self=False,
    is_gateway=False,
    is_randomised_mac=False,
    ttl=None,
    ttl_class=None,
    device_class=None,
    nbns_name=None,
    upnp_server=None,
    upnp_friendly_name=None,
    upnp_model=None,
    bonjour_model=None,
):
    from datetime import datetime, timezone
    from diting.lan import LANHost
    now = datetime(2026, 5, 17, 12, 0, 0, tzinfo=timezone.utc)
    return LANHost(
        mac=mac,
        ip=ip,
        vendor=vendor,
        hostname=hostname,
        bonjour_name=bonjour_name,
        bonjour_services=bonjour_services,
        first_seen=now,
        last_seen=now,
        is_gateway=is_gateway,
        is_self=is_self,
        is_randomised_mac=is_randomised_mac,
        vendor_raw=vendor_raw,
        ttl=ttl,
        ttl_class=ttl_class,
        device_class=device_class,
        nbns_name=nbns_name,
        upnp_server=upnp_server,
        upnp_friendly_name=upnp_friendly_name,
        upnp_model=upnp_model,
        bonjour_model=bonjour_model,
    )


def _lan_update(hosts, *, capped=False, cap=24):
    from datetime import datetime, timezone
    from diting.lan import LANInventoryUpdate
    now = datetime(2026, 5, 17, 12, 0, 0, tzinfo=timezone.utc)
    return LANInventoryUpdate(
        hosts=tuple(hosts),
        subnet="192.168.1.0/24",
        subnet_capped=capped,
        cap_prefix=cap,
        last_sweep_at=now,
        next_sweep_at=now,
    )


def test_lan_panel_renders_self_and_gateway_pinned_to_top():
    """The first row is the self entry (★ + this Mac), the second
    is the gateway (★ + gateway)."""
    from diting.tui import _lan_row_line
    from datetime import datetime, timezone
    self_host = _lan_host(mac="84:2f:57:9b:15:59", is_self=True)
    gateway = _lan_host(mac="aa:bb:cc:11:22:33", ip="192.168.1.1", is_gateway=True)
    other = _lan_host(mac="de:ad:be:ef:00:01", ip="192.168.1.42")
    now = datetime.now(timezone.utc)
    self_text = _lan_row_line(self_host, now).plain
    gw_text = _lan_row_line(gateway, now).plain
    other_text = _lan_row_line(other, now).plain
    assert "★" in self_text and "this Mac" in self_text
    assert "★" in gw_text and "gateway" in gw_text
    assert "★" not in other_text


def test_lan_panel_sorts_remaining_rows_by_ip_ascending():
    """Self / gateway aside, the remaining LANHost rows render in
    IP-ascending order — verified through the _sort_key helper."""
    from diting.lan import _sort_key
    a = _lan_host(mac="aa:00:00:00:00:01", ip="192.168.1.50")
    b = _lan_host(mac="aa:00:00:00:00:02", ip="192.168.1.10")
    c = _lan_host(mac="aa:00:00:00:00:03", ip="192.168.1.99")
    ordered = sorted([a, b, c], key=_sort_key)
    assert [h.ip for h in ordered] == ["192.168.1.10", "192.168.1.50", "192.168.1.99"]


def test_lan_panel_marks_random_mac_with_label():
    """A locally-administered (random) MAC's vendor cell shows
    "(random MAC)" instead of the vendor / (unknown) string."""
    from diting.tui import _lan_row_line
    from datetime import datetime, timezone
    host = _lan_host(
        mac="02:11:22:33:44:55", vendor=None, is_randomised_mac=True,
    )
    text = _lan_row_line(host, datetime.now(timezone.utc)).plain
    assert "(random MAC)" in text


def test_lan_diagnostics_renders_full_summary_line():
    """The diagnostics block carries host count, named-via-Bonjour
    count, unknown-vendor count, subnet, and last-sweep relative
    time on three rows."""
    from diting.tui import _lan_diagnostic_lines
    hosts = [
        _lan_host(mac="01:00:00:00:00:01", vendor="Apple, Inc.",
                  bonjour_name="apple-1"),
        _lan_host(mac="02:00:00:00:00:02", vendor="Apple, Inc.",
                  bonjour_name="apple-2"),
        _lan_host(mac="03:00:00:00:00:03", vendor=None),
    ]
    update = _lan_update(hosts)
    rows = _lan_diagnostic_lines(update)
    joined = "".join(r.plain for r in rows)
    assert "3 hosts" in joined
    assert "2 named" in joined
    assert "1 unknown vendor" in joined
    assert "192.168.1.0/24" in joined
    # Last-sweep row carries a relative-time value. The exact value
    # depends on `datetime.now() - update.last_sweep_at`; here both
    # are "now" so the rendered text is "0s ago".
    assert "0s ago" in joined or "ago" in joined


def test_lan_diagnostics_annotates_capped_subnet_when_netmask_wider():
    from diting.tui import _lan_diagnostic_lines
    update = _lan_update([_lan_host()], capped=True)
    joined = "".join(r.plain for r in _lan_diagnostic_lines(update))
    assert "capped" in joined


def test_lan_diagnostics_omits_capped_annotation_when_full_subnet_swept():
    from diting.tui import _lan_diagnostic_lines
    update = _lan_update([_lan_host()], capped=False)
    joined = "".join(r.plain for r in _lan_diagnostic_lines(update))
    assert "capped" not in joined


def test_lan_detail_modal_renders_all_sections():
    """LANDetailScreen renders Identity / Network / Bonjour services
    / Activity sections for a Bonjour-named host."""
    from diting.tui import LANDetailScreen
    host = _lan_host(
        bonjour_name="my-mac",
        bonjour_services=("AirPlay", "AirPlay audio"),
    )
    screen = LANDetailScreen(host=host)
    body = screen._render_body()
    # `body` is a rich Group; collect its renderable strings.
    rendered = "\n".join(
        getattr(r, "plain", str(r)) for r in body.renderables
    )
    assert "Identity" in rendered
    assert "Network" in rendered
    assert "Bonjour services" in rendered
    assert "Activity" in rendered
    assert "AirPlay" in rendered
    assert "AirPlay audio" in rendered


def test_lan_detail_modal_renders_bonjour_empty_state_when_no_services():
    """A LAN host with no Bonjour services renders the section
    header followed by a `(no Bonjour services)` placeholder. We
    keep the section visible so users see the cross-reference
    channel was checked."""
    from diting.tui import LANDetailScreen
    host = _lan_host(bonjour_name=None, bonjour_services=())
    screen = LANDetailScreen(host=host)
    body = screen._render_body()
    rendered = "\n".join(
        getattr(r, "plain", str(r)) for r in body.renderables
    )
    assert "Identity" in rendered
    assert "Bonjour services" in rendered
    assert "(no Bonjour services)" in rendered


def test_lan_detail_modal_renders_bonjour_services_when_present():
    """Sanity: when services exist, the section header is followed
    by one row per category and the placeholder is absent."""
    from diting.tui import LANDetailScreen
    host = _lan_host(
        bonjour_name="my-mac",
        bonjour_services=("AirPlay", "AirPlay audio"),
    )
    screen = LANDetailScreen(host=host)
    body = screen._render_body()
    rendered = "\n".join(
        getattr(r, "plain", str(r)) for r in body.renderables
    )
    assert "Bonjour services" in rendered
    assert "AirPlay" in rendered
    assert "AirPlay audio" in rendered
    assert "(no Bonjour services)" not in rendered


def test_lan_detail_shows_raw_ieee_continuation_when_normalized():
    """When `vendor_raw != vendor` (normalization shortened the IEEE
    name), the modal renders the raw form on a dim continuation line
    so the user can reconcile odd normalisations."""
    from diting.tui import LANDetailScreen
    host = _lan_host(
        vendor="New H3C",
        vendor_raw="NEW H3C TECHNOLOGIES CO., LTD",
        bonjour_services=(),
    )
    screen = LANDetailScreen(host=host)
    body = screen._render_body()
    rendered = "\n".join(
        getattr(r, "plain", str(r)) for r in body.renderables
    )
    assert "New H3C" in rendered
    assert "NEW H3C TECHNOLOGIES CO., LTD" in rendered


def test_lan_detail_omits_raw_continuation_when_unchanged():
    """When normalization didn't change the name, the modal does NOT
    add a second continuation line — that would be noise."""
    from diting.tui import LANDetailScreen
    host = _lan_host(
        vendor="Apple, Inc.",
        vendor_raw="Apple, Inc.",
        bonjour_services=(),
    )
    screen = LANDetailScreen(host=host)
    body = screen._render_body()
    rendered = "\n".join(
        getattr(r, "plain", str(r)) for r in body.renderables
    )
    # Vendor row appears exactly once.
    assert rendered.count("Apple, Inc.") == 1


def test_lan_detail_omits_raw_continuation_when_raw_none():
    """`vendor_raw=None` (older snapshot path, or random MAC) must
    not add a continuation line either."""
    from diting.tui import LANDetailScreen
    host = _lan_host(
        vendor="Apple, Inc.",
        vendor_raw=None,
        bonjour_services=(),
    )
    screen = LANDetailScreen(host=host)
    body = screen._render_body()
    rendered = "\n".join(
        getattr(r, "plain", str(r)) for r in body.renderables
    )
    assert rendered.count("Apple, Inc.") == 1


# ---------- Phase 3: Class + TTL rows ----------


def test_lan_detail_shows_class_row_when_device_class_present():
    from diting.tui import LANDetailScreen
    host = _lan_host(device_class="tv", bonjour_services=())
    screen = LANDetailScreen(host=host)
    body = screen._render_body()
    rendered = "\n".join(
        getattr(r, "plain", str(r)) for r in body.renderables
    )
    assert "Class" in rendered
    assert "tv" in rendered


def test_lan_detail_omits_class_row_when_device_class_none():
    """A row whose classifier didn't fire must not show a `Class:`
    line — empty value would just be noise."""
    from diting.tui import LANDetailScreen
    host = _lan_host(device_class=None, bonjour_services=())
    screen = LANDetailScreen(host=host)
    body = screen._render_body()
    rendered = "\n".join(
        getattr(r, "plain", str(r)) for r in body.renderables
    )
    assert "Class" not in rendered


def test_lan_detail_shows_ttl_row_with_class():
    from diting.tui import LANDetailScreen
    from dataclasses import replace as _replace
    host = _lan_host(bonjour_services=())
    host = _replace(host, ttl=64, ttl_class="unix")
    screen = LANDetailScreen(host=host)
    body = screen._render_body()
    rendered = "\n".join(
        getattr(r, "plain", str(r)) for r in body.renderables
    )
    assert "TTL" in rendered
    assert "64" in rendered
    # TTL class is rendered parenthesised. Match the class token
    # itself rather than the parenthesis to stay i18n-tolerant.
    assert "unix" in rendered


def test_lan_detail_shows_ttl_row_without_class():
    """A TTL value outside the bucketed bands (ttl_class=None) still
    shows the raw value — just without the parenthesised class."""
    from diting.tui import LANDetailScreen
    from dataclasses import replace as _replace
    host = _lan_host(bonjour_services=())
    host = _replace(host, ttl=90, ttl_class=None)
    screen = LANDetailScreen(host=host)
    body = screen._render_body()
    rendered = "\n".join(
        getattr(r, "plain", str(r)) for r in body.renderables
    )
    assert "TTL" in rendered
    assert "90" in rendered


def test_lan_detail_shows_active_discovery_section_with_nbns():
    """When NBNS / UPnP enrichments are present the Active discovery
    section renders them; the placeholder is absent."""
    from diting.tui import LANDetailScreen
    host = _lan_host(
        bonjour_services=(),
        nbns_name="LAB-PRINTER-01",
        upnp_server="Linux/3.10 UPnP/1.0 HiSenseTV/2024.01",
        upnp_friendly_name="Living Room TV",
        upnp_model="HiSense 75U7K",
    )
    screen = LANDetailScreen(host=host)
    body = screen._render_body()
    rendered = "\n".join(
        getattr(r, "plain", str(r)) for r in body.renderables
    )
    assert "Active discovery" in rendered
    assert "LAB-PRINTER-01" in rendered
    assert "Linux/3.10 UPnP/1.0 HiSenseTV/2024.01" in rendered
    assert "Living Room TV" in rendered
    assert "HiSense 75U7K" in rendered
    # Placeholder is absent when at least one field is present.
    assert "(not probed)" not in rendered


def test_lan_detail_shows_active_discovery_placeholder_when_nothing_probed():
    """A host whose four active-discovery fields are all None
    renders the section header + `(not probed)` placeholder."""
    from diting.tui import LANDetailScreen
    host = _lan_host(bonjour_services=())
    screen = LANDetailScreen(host=host)
    body = screen._render_body()
    rendered = "\n".join(
        getattr(r, "plain", str(r)) for r in body.renderables
    )
    assert "Active discovery" in rendered
    assert "(not probed)" in rendered


def test_lan_detail_identity_shows_model_when_upnp_model_set():
    """The Identity section gains a `Model:` row when UPnP discovery
    populated `upnp_model`."""
    from diting.tui import LANDetailScreen
    host = _lan_host(
        bonjour_services=(),
        upnp_model="HiSense 75U7K",
    )
    screen = LANDetailScreen(host=host)
    body = screen._render_body()
    rendered = "\n".join(
        getattr(r, "plain", str(r)) for r in body.renderables
    )
    assert "Model" in rendered
    assert "HiSense 75U7K" in rendered


def test_lan_detail_identity_prefers_bonjour_model_with_friendly_name():
    """When `bonjour_model` is set (e.g. `Mac14,2` from Bonjour TXT),
    Identity Model row renders `<friendly-name> (<raw-code>)` via the
    `_APPLE_MODELS` lookup table — preferred over the UPnP source."""
    from diting.tui import LANDetailScreen
    host = _lan_host(
        bonjour_services=(),
        bonjour_model="Mac14,2",
    )
    screen = LANDetailScreen(host=host)
    body = screen._render_body()
    rendered = "\n".join(
        getattr(r, "plain", str(r)) for r in body.renderables
    )
    assert "MacBook Air 13-inch (M2, 2022)" in rendered
    assert "Mac14,2" in rendered


def test_lan_detail_identity_uses_raw_code_when_apple_model_unknown():
    """Unknown / future Apple model codes still render as the raw
    string — the user can match against Apple's external tables."""
    from diting.tui import LANDetailScreen
    host = _lan_host(bonjour_services=(), bonjour_model="Mac99,99")
    screen = LANDetailScreen(host=host)
    body = screen._render_body()
    rendered = "\n".join(
        getattr(r, "plain", str(r)) for r in body.renderables
    )
    # Raw code shown bare (no parenthesised friendly name).
    assert "Mac99,99" in rendered


def test_lan_detail_identity_falls_back_to_friendly_name_when_no_model():
    """When `upnp_model` is None but `upnp_friendly_name` is set,
    the Identity Model row falls back to the friendly name."""
    from diting.tui import LANDetailScreen
    host = _lan_host(
        bonjour_services=(),
        upnp_friendly_name="Living Room TV",
    )
    screen = LANDetailScreen(host=host)
    body = screen._render_body()
    rendered = "\n".join(
        getattr(r, "plain", str(r)) for r in body.renderables
    )
    # First occurrence is the Identity Model row.
    assert rendered.index("Living Room TV") >= 0


def test_lan_detail_identity_omits_model_when_neither_field_set():
    """No UPnP model AND no UPnP friendly name → no Model row in
    Identity. Keeps the section tight for hosts that haven't been
    probed."""
    from diting.tui import LANDetailScreen
    host = _lan_host(bonjour_services=())
    screen = LANDetailScreen(host=host)
    body = screen._render_body()
    rendered = "\n".join(
        getattr(r, "plain", str(r)) for r in body.renderables
    )
    # Active discovery section header still appears but Identity
    # has no Model row, so the only "Model" string would be in the
    # Active discovery section — and that section shows
    # "(not probed)" here. Hence "Model" should NOT appear.
    assert "Model" not in rendered


def test_lan_detail_ttl_row_suppresses_class_for_gateway():
    """CN consumer routers (H3C / Huawei / some TP-Link firmwares)
    ship with TTL=128, which our `windows` heuristic catches. For
    the gateway row that label is more confusing than useful — the
    is_gateway rule already wins router-class, and 'TTL 128 (windows)'
    on a router reads wrong. Suppress the parenthesised label for
    gateways only — non-gateway rows keep it."""
    from diting.tui import LANDetailScreen
    from dataclasses import replace as _replace
    host = _lan_host(is_gateway=True, bonjour_services=())
    host = _replace(host, ttl=128, ttl_class="windows")
    screen = LANDetailScreen(host=host)
    body = screen._render_body()
    rendered = "\n".join(
        getattr(r, "plain", str(r)) for r in body.renderables
    )
    assert "TTL" in rendered
    assert "128" in rendered
    # Gateway: parenthesised class is suppressed.
    assert "windows" not in rendered.lower()
    assert "(" not in rendered.split("TTL")[1].split("Reachable")[0]


def test_lan_detail_ttl_row_keeps_class_for_non_gateway():
    """Sanity that the gateway-only suppression doesn't strip the
    label from regular hosts too — a Windows desktop should still
    show `TTL 128 (windows)`."""
    from diting.tui import LANDetailScreen
    from dataclasses import replace as _replace
    host = _lan_host(is_gateway=False, bonjour_services=())
    host = _replace(host, ttl=128, ttl_class="windows")
    screen = LANDetailScreen(host=host)
    body = screen._render_body()
    rendered = "\n".join(
        getattr(r, "plain", str(r)) for r in body.renderables
    )
    assert "128" in rendered
    assert "windows" in rendered.lower()


def test_lan_detail_omits_ttl_row_when_ttl_none():
    from diting.tui import LANDetailScreen
    host = _lan_host(bonjour_services=())
    assert host.ttl is None
    screen = LANDetailScreen(host=host)
    body = screen._render_body()
    rendered = "\n".join(
        getattr(r, "plain", str(r)) for r in body.renderables
    )
    assert "TTL" not in rendered


# ---------- Phase 4: LAN row layout (class column + [new] chip) ----------


def test_lan_row_includes_class_column_when_device_class_set():
    from datetime import timedelta
    from dataclasses import replace as _replace
    from diting.tui import _lan_row_line
    host = _lan_host(device_class="tv", vendor="Hisense", bonjour_services=())
    # Push first_seen back 48 h so the [new] chip is NOT present —
    # this test isolates the class column.
    host = _replace(
        host,
        first_seen=host.first_seen - timedelta(hours=48),
        last_seen=host.last_seen - timedelta(hours=48),
    )
    row = _lan_row_line(host, now=host.last_seen)
    rendered = row.plain
    assert "tv" in rendered
    assert "Hisense" in rendered
    # `tv` must appear BEFORE `Hisense` (class is leftmost data
    # column per the Fing-inspired layout).
    assert rendered.index("tv") < rendered.index("Hisense")


def test_lan_row_class_column_blank_when_device_class_none():
    from datetime import timedelta
    from dataclasses import replace as _replace
    from diting.tui import _lan_row_line, _COL_LAN_CLASS
    host = _lan_host(device_class=None, vendor="Apple, Inc.", bonjour_services=())
    host = _replace(
        host,
        first_seen=host.first_seen - timedelta(hours=48),
        last_seen=host.last_seen - timedelta(hours=48),
    )
    row = _lan_row_line(host, now=host.last_seen)
    rendered = row.plain
    # No class label rendered, but column-width spacing is preserved.
    # Length of the prefix slot + star + class column should be at
    # least 7 + 2 + 8 = 17 cells.
    # We assert via the vendor coming AFTER 17 cells of padding.
    assert "Apple" in rendered
    assert rendered.index("Apple") >= _COL_LAN_CLASS


def test_lan_row_new_chip_present_when_first_seen_within_24h():
    from datetime import timedelta
    from dataclasses import replace as _replace
    from diting.tui import _lan_row_line
    host = _lan_host(vendor="Apple, Inc.", bonjour_services=())
    # first_seen 2 h ago — within the 24 h window.
    host = _replace(
        host, first_seen=host.last_seen - timedelta(hours=2),
    )
    row = _lan_row_line(host, now=host.last_seen)
    assert "[new]" in row.plain


def test_lan_row_new_chip_absent_when_first_seen_outside_24h():
    from datetime import timedelta
    from dataclasses import replace as _replace
    from diting.tui import _lan_row_line
    host = _lan_host(vendor="Apple, Inc.", bonjour_services=())
    host = _replace(
        host, first_seen=host.last_seen - timedelta(hours=48),
    )
    row = _lan_row_line(host, now=host.last_seen)
    assert "[new]" not in row.plain


def test_lan_row_new_chip_absent_for_self():
    from datetime import timedelta
    from dataclasses import replace as _replace
    from diting.tui import _lan_row_line
    # Self is fresh-looking but conceptually never new — it
    # represents the user's own machine.
    host = _lan_host(is_self=True, vendor="Apple, Inc.", bonjour_services=())
    host = _replace(
        host, first_seen=host.last_seen - timedelta(minutes=5),
    )
    row = _lan_row_line(host, now=host.last_seen)
    assert "[new]" not in row.plain


def test_lan_row_new_chip_absent_for_gateway():
    from datetime import timedelta
    from dataclasses import replace as _replace
    from diting.tui import _lan_row_line
    host = _lan_host(is_gateway=True, vendor="New H3C", bonjour_services=())
    host = _replace(
        host, first_seen=host.last_seen - timedelta(minutes=5),
    )
    row = _lan_row_line(host, now=host.last_seen)
    assert "[new]" not in row.plain


def test_lan_row_new_chip_suppressed_for_initial_sweep_with_anchor():
    """A host whose `first_seen` lands within the grace window of the
    poller's `_constructed_at` (`chip_anchor`) is considered session
    baseline — `[new]` chip must NOT fire. Regression for the
    2026-05-23 tui-audit where every host on the user's home network
    carried `[new]` because the LAN poller is lazy-constructed and
    stamps first_seen=now on the initial sweep."""
    from datetime import timedelta
    from dataclasses import replace as _replace
    from diting.tui import _lan_row_line
    host = _lan_host(vendor="Apple, Inc.", bonjour_services=())
    # First sweep fires ~3s after the poller starts.
    anchor = host.last_seen - timedelta(seconds=3)
    host = _replace(host, first_seen=anchor + timedelta(seconds=1))
    row = _lan_row_line(host, now=host.last_seen, chip_anchor=anchor)
    assert "[new]" not in row.plain


def test_lan_row_new_chip_still_fires_after_grace_with_anchor():
    """A host that joined the network well after the poller started
    (outside the grace window) should still trip the chip — that's
    the case the chip exists for."""
    from datetime import timedelta
    from dataclasses import replace as _replace
    from diting.tui import _lan_row_line
    host = _lan_host(vendor="Apple, Inc.", bonjour_services=())
    # Poller has been running for an hour; this host showed up 5
    # minutes ago — that's a truly new device, fire the chip.
    anchor = host.last_seen - timedelta(hours=1)
    host = _replace(host, first_seen=host.last_seen - timedelta(minutes=5))
    row = _lan_row_line(host, now=host.last_seen, chip_anchor=anchor)
    assert "[new]" in row.plain


def test_lan_row_new_chip_falls_back_to_old_behavior_without_anchor():
    """Existing test fixtures + back-compat callers that don't pass
    `chip_anchor` keep the original 24-h-window-only semantics. The
    grace check is opt-in."""
    from datetime import timedelta
    from dataclasses import replace as _replace
    from diting.tui import _lan_row_line
    host = _lan_host(vendor="Apple, Inc.", bonjour_services=())
    host = _replace(host, first_seen=host.last_seen - timedelta(hours=2))
    row = _lan_row_line(host, now=host.last_seen)  # no chip_anchor
    assert "[new]" in row.plain


def test_lan_header_line_includes_class_column_before_vendor():
    from diting.tui import _lan_header_line
    header = _lan_header_line().plain
    assert "class" in header
    assert "vendor" in header
    assert header.index("class") < header.index("vendor")


# ---------- Phase 4: LANProbeConsentScreen modal contents ----------


def test_lan_probe_consent_modal_body_lists_packets_and_consequences():
    from diting.tui import LANProbeConsentScreen
    screen = LANProbeConsentScreen(scene="public", ssid="HotelGuest")
    body = screen._render_body()
    rendered = "\n".join(
        getattr(r, "plain", str(r)) for r in body.renderables
    )
    assert "public" in rendered
    assert "HotelGuest" in rendered
    assert "NBNS" in rendered and "137" in rendered
    assert "SSDP" in rendered and "1900" in rendered
    assert "mDNS" in rendered and "5353" in rendered
    # Consequences statement is present.
    assert (
        "guests' devices" in rendered
        or "guests" in rendered
        or "其他客人" in rendered  # ZH catalog
    )


def test_lan_probe_consent_modal_renders_disassociated_when_ssid_none():
    from diting.tui import LANProbeConsentScreen
    screen = LANProbeConsentScreen(scene="public", ssid=None)
    body = screen._render_body()
    rendered = "\n".join(
        getattr(r, "plain", str(r)) for r in body.renderables
    )
    assert (
        "(disassociated)" in rendered or "（未连接 Wi-Fi）" in rendered
    )


def test_lan_probe_consent_modal_footer_shows_wait_during_cooldown():
    """Right after instantiation, before on_mount fires, the
    cooldown is not yet elapsed. `_render_footer` returns the
    `wait 2s` form."""
    from diting.tui import LANProbeConsentScreen
    screen = LANProbeConsentScreen(scene="public", ssid="x")
    # _opened_at is None until on_mount — _cooldown_elapsed() returns
    # False so the footer renders the wait form.
    footer = screen._render_footer().plain
    assert (
        "wait 2s" in footer or "等待 2 秒" in footer
    )


def test_event_ts_renders_local_time_for_utc_aware_event(monkeypatch):
    """A UTC-aware event timestamp must render as the operator's
    local time in the events panel — matches the JSONL `_iso`
    contract. Regression for the audit finding where 16:19 local
    rendered as 08:19 in the events modal."""
    import time
    from datetime import datetime, timezone
    from diting.events import LANHostSeenEvent
    from diting.tui import _ev_ts

    monkeypatch.setenv("TZ", "Asia/Shanghai")
    try:
        time.tzset()
    except AttributeError:
        pass  # Windows — tzset doesn't exist; the test still passes
    ev = LANHostSeenEvent(
        timestamp=datetime(2026, 5, 23, 8, 19, 13, tzinfo=timezone.utc),
        mac="aa:bb:cc:dd:ee:ff", ip="0.0.0.0",
        vendor=None, hostname=None, bonjour_name=None,
        is_randomised_mac=False,
    )
    # 08:19:13 UTC → 16:19:13 in Asia/Shanghai (UTC+8).
    assert _ev_ts(ev) == "16:19:13"


def test_event_ts_handles_naive_datetime():
    """Naive datetimes fall through `.astimezone()` (which treats them
    as local) unchanged. Existing test fixtures that build naive
    timestamps keep working."""
    from datetime import datetime
    from diting.events import LANHostSeenEvent
    from diting.tui import _ev_ts
    ev = LANHostSeenEvent(
        timestamp=datetime(2026, 5, 23, 14, 30, 45),  # no tzinfo
        mac="aa:bb:cc:dd:ee:ff", ip="0.0.0.0",
        vendor=None, hostname=None, bonjour_name=None,
        is_randomised_mac=False,
    )
    # Naive datetime stays at its own clock face.
    assert _ev_ts(ev) == "14:30:45"


def test_lan_probe_consent_action_confirm_is_silent_during_cooldown():
    """During the cooldown, `action_confirm` must be a pure no-op —
    no exception, no event logged, modal stays open."""
    from diting.tui import LANProbeConsentScreen
    screen = LANProbeConsentScreen(scene="public", ssid="x")
    # _opened_at is None → cooldown not elapsed.
    assert screen._cooldown_elapsed() is False
    # The action must not raise and must not invoke any app-side
    # callback. We assert by checking the screen has no app yet —
    # any attempt to call self.app.pop_screen would AttributeError.
    screen.action_confirm()  # silent no-op


def test_lan_detail_modal_renders_latency_row_when_rtt_known():
    """`Latency  2.4 ms` row appears in the Network section when
    last_rtt_ms is known."""
    from diting.tui import LANDetailScreen
    host = _lan_host(bonjour_services=())
    from dataclasses import replace as _replace
    host = _replace(host, last_rtt_ms=2.4)
    screen = LANDetailScreen(host=host)
    body = screen._render_body()
    rendered = "\n".join(
        getattr(r, "plain", str(r)) for r in body.renderables
    )
    assert "Latency" in rendered
    assert "2.4 ms" in rendered


def test_lan_detail_modal_omits_latency_row_when_rtt_unknown():
    """When last_rtt_ms is None the Latency row is omitted (no info
    to surface)."""
    from diting.tui import LANDetailScreen
    host = _lan_host(bonjour_services=())
    assert host.last_rtt_ms is None
    screen = LANDetailScreen(host=host)
    body = screen._render_body()
    rendered = "\n".join(
        getattr(r, "plain", str(r)) for r in body.renderables
    )
    assert "Latency" not in rendered


def test_lan_detail_modal_renders_reachable_row_this_sweep():
    """`Reachable  this sweep` when last_reachable_at is within the
    sweep window."""
    from diting.tui import LANDetailScreen
    from datetime import datetime, timezone
    host = _lan_host(bonjour_services=())
    from dataclasses import replace as _replace
    host = _replace(host, last_reachable_at=datetime.now(timezone.utc))
    screen = LANDetailScreen(host=host)
    body = screen._render_body()
    rendered = "\n".join(
        getattr(r, "plain", str(r)) for r in body.renderables
    )
    assert "Reachable" in rendered
    assert "this sweep" in rendered


def test_lan_detail_modal_renders_reachable_row_with_relative_time_when_older():
    """Older last_reachable_at renders as `Xm Ys ago` via the
    existing duration helper."""
    from diting.tui import LANDetailScreen
    from datetime import datetime, timedelta, timezone
    host = _lan_host(bonjour_services=())
    from dataclasses import replace as _replace
    host = _replace(
        host,
        last_reachable_at=datetime.now(timezone.utc) - timedelta(seconds=125),
    )
    screen = LANDetailScreen(host=host)
    body = screen._render_body()
    rendered = "\n".join(
        getattr(r, "plain", str(r)) for r in body.renderables
    )
    assert "Reachable" in rendered
    assert "ago" in rendered
    assert "this sweep" not in rendered


def test_lan_detail_modal_renders_never_when_never_reachable():
    """last_reachable_at None → `never` (host is in ARP cache but
    diting has not seen a ping reply for it yet)."""
    from diting.tui import LANDetailScreen
    host = _lan_host(bonjour_services=())
    assert host.last_reachable_at is None
    screen = LANDetailScreen(host=host)
    body = screen._render_body()
    rendered = "\n".join(
        getattr(r, "plain", str(r)) for r in body.renderables
    )
    assert "Reachable" in rendered
    assert "never" in rendered


def test_lan_panel_renders_sweeping_placeholder_before_first_snapshot():
    """The panel renders the dim-italic '(sweeping subnet…)' line
    when the latest update is None."""
    from diting.tui import LANPanel
    panel = LANPanel(id="lan-test")
    # Direct invocation of update_hosts(None) goes through the early
    # return — we exercise the placeholder branch by inspecting the
    # _y_to_key state after.
    panel._y_to_key = ["sentinel"]  # something for us to verify gets cleared
    # Body widget isn't mounted; assert the contract that update_hosts(None)
    # resets selection rather than rendering rows. We do this without
    # a live Textual app by stubbing query_one to a sentinel:
    class _FakeStatic:
        def update(self, *_a, **_k): pass
    panel.query_one = lambda *_a, **_k: _FakeStatic()  # type: ignore[assignment]
    panel.update_hosts(None)
    assert panel._y_to_key == []


def test_lan_panel_renders_rows_after_first_snapshot():
    """When an update has hosts, the y_to_key map carries one entry
    per row (one None header + one per host)."""
    from diting.tui import LANPanel
    panel = LANPanel(id="lan-test")
    hosts = [
        _lan_host(mac="aa:00:00:00:00:01", ip="192.168.1.10"),
        _lan_host(mac="aa:00:00:00:00:02", ip="192.168.1.42",
                  bonjour_name="other"),
    ]
    update = _lan_update(hosts)

    class _FakeStatic:
        def update(self, *_a, **_k): pass
    panel.query_one = lambda *_a, **_k: _FakeStatic()  # type: ignore[assignment]
    panel.update_hosts(update)
    # First entry is the header (None); then one per host.
    assert panel._y_to_key == [None, "aa:00:00:00:00:01", "aa:00:00:00:00:02"]


# --- EventsPanel rendering for the 7 new transition events ----------

def _tui_inv():
    from diting.network import NetworkInventory
    return NetworkInventory(aps=[])


def _event_text(event):
    """Helper: render via the same code path the panel uses."""
    from diting.tui import _event_format_line
    line = _event_format_line(event, _tui_inv())
    return line.plain if line is not None else ""


def test_events_panel_renders_ble_device_seen_line():
    from datetime import datetime, timezone
    from diting.events import BLEDeviceSeenEvent
    ev = BLEDeviceSeenEvent(
        timestamp=datetime(2026, 5, 20, 12, 0, 0, tzinfo=timezone.utc),
        identifier="abc",
        name="Magic Keyboard", vendor="Apple, Inc.",
        rssi_dbm=-55, service_categories=("HID",),
    )
    text = _event_text(ev)
    assert "[BLE]" in text
    assert "device seen" in text
    assert "Apple, Inc." in text
    assert "Magic Keyboard" in text


def test_events_panel_renders_ble_device_left_line_with_duration():
    from datetime import datetime, timezone
    from diting.events import BLEDeviceLeftEvent
    ev = BLEDeviceLeftEvent(
        timestamp=datetime(2026, 5, 20, 12, 0, 0, tzinfo=timezone.utc),
        identifier="abc",
        name="Magic Keyboard", vendor="Apple, Inc.",
        last_rssi_dbm=-80, service_categories=("HID",),
        seen_for_seconds=3600.0,
    )
    text = _event_text(ev)
    assert "[BLE]" in text
    assert "device left" in text
    assert "1h" in text


def test_events_panel_renders_bonjour_service_seen_line():
    from datetime import datetime, timezone
    from diting.events import BonjourServiceSeenEvent
    ev = BonjourServiceSeenEvent(
        timestamp=datetime(2026, 5, 20, 12, 0, 0, tzinfo=timezone.utc),
        service_type="_airplay._tcp.local.",
        name="Blue Pod._airplay._tcp.local.",
        host="Blue-Pod", category="AirPlay", vendor="Apple, Inc.",
        addresses=("192.168.1.42",),
    )
    text = _event_text(ev)
    assert "[BJ]" in text
    assert "service seen" in text
    assert "AirPlay" in text
    assert "Blue-Pod" in text


def test_events_panel_renders_bonjour_service_left_line_with_duration():
    from datetime import datetime, timezone
    from diting.events import BonjourServiceLeftEvent
    ev = BonjourServiceLeftEvent(
        timestamp=datetime(2026, 5, 20, 12, 0, 0, tzinfo=timezone.utc),
        service_type="_raop._tcp.local.",
        name="HomePod._raop._tcp.local.",
        host="HomePod", category="AirPlay audio", vendor=None,
        seen_for_seconds=86400.0,
    )
    text = _event_text(ev)
    assert "[BJ]" in text
    assert "service left" in text
    assert "HomePod" in text


def test_events_panel_renders_lan_host_seen_line():
    from datetime import datetime, timezone
    from diting.events import LANHostSeenEvent
    ev = LANHostSeenEvent(
        timestamp=datetime(2026, 5, 20, 12, 0, 0, tzinfo=timezone.utc),
        mac="de:ad:be:ef:00:01", ip="192.168.1.42",
        vendor="Apple, Inc.", hostname=None,
        bonjour_name="ccy-MBP24-M4-Office",
        is_randomised_mac=False,
    )
    text = _event_text(ev)
    assert "[LAN]" in text
    assert "host seen" in text
    assert "Apple, Inc." in text
    assert "ccy-MBP24-M4-Office" in text


def test_events_panel_renders_lan_host_left_line_with_duration():
    from datetime import datetime, timezone
    from diting.events import LANHostLeftEvent
    ev = LANHostLeftEvent(
        timestamp=datetime(2026, 5, 20, 12, 0, 0, tzinfo=timezone.utc),
        mac="de:ad:be:ef:00:01", ip="192.168.1.42",
        vendor="Apple, Inc.", hostname=None, bonjour_name=None,
        is_randomised_mac=False,
        seen_for_seconds=7200.0,
        last_reachable_ago_seconds=305.0,
    )
    text = _event_text(ev)
    assert "[LAN]" in text
    assert "host left" in text
    assert "2h" in text


def test_events_panel_renders_lan_dhcp_rotation_line():
    from datetime import datetime, timezone
    from diting.events import LANHostDHCPRotationEvent
    ev = LANHostDHCPRotationEvent(
        timestamp=datetime(2026, 5, 20, 12, 0, 0, tzinfo=timezone.utc),
        mac="de:ad:be:ef:00:01",
        previous_ip="192.168.1.42", new_ip="192.168.1.77",
        vendor="Apple, Inc.", hostname=None,
        bonjour_name="ccy-MBP24-M4-Office",
    )
    text = _event_text(ev)
    assert "[LAN]" in text
    assert "192.168.1.42" in text
    assert "192.168.1.77" in text
    assert "moved" in text


# --- EventsScreen filter cycle ---------------------------------------

def test_events_screen_filter_cycle_has_eight_buckets():
    """`_events_filter_match` accepts the eight buckets specified by
    the tui-shell spec delta."""
    from diting.tui import _events_filter_match
    from datetime import datetime, timezone
    from diting.events import BLEDeviceSeenEvent
    ev = BLEDeviceSeenEvent(
        timestamp=datetime(2026, 5, 20, 12, 0, 0, tzinfo=timezone.utc),
        identifier="x", name=None, vendor=None, rssi_dbm=None,
        service_categories=(),
    )
    assert _events_filter_match(ev, "all") is True
    assert _events_filter_match(ev, "ble") is True
    assert _events_filter_match(ev, "bonjour") is False
    assert _events_filter_match(ev, "lan") is False
    assert _events_filter_match(ev, "roam") is False


def test_events_screen_filter_keys_map_to_buckets_in_order():
    """The spec pins keys `0`-`7` to the eight buckets in order."""
    from diting.tui import EventsScreen
    bindings_by_action = {b.action: b.key for b in EventsScreen.BINDINGS}
    assert bindings_by_action["set_filter('all')"] == "0"
    assert bindings_by_action["set_filter('roam')"] == "1"
    assert bindings_by_action["set_filter('stir')"] == "2"
    assert bindings_by_action["set_filter('latency')"] == "3"
    assert bindings_by_action["set_filter('link')"] == "4"
    assert bindings_by_action["set_filter('ble')"] == "5"
    assert bindings_by_action["set_filter('bonjour')"] == "6"
    assert bindings_by_action["set_filter('lan')"] == "7"


# --- EventsScreen consecutive BLE-seen grouping (v1.7.2) ------------

def _ble_seen(ts_sec: int, vendor: str | None, name: str | None,
              identifier: str | None = None):
    """Compact factory for BLEDeviceSeenEvent fixtures."""
    from datetime import datetime, timezone
    from diting.events import BLEDeviceSeenEvent
    return BLEDeviceSeenEvent(
        timestamp=datetime(2026, 5, 25, 18, 10, ts_sec, tzinfo=timezone.utc),
        identifier=identifier or f"id-{ts_sec}",
        name=name, vendor=vendor, rssi_dbm=-70, service_categories=(),
    )


def test_events_screen_collapses_three_consecutive_identical_ble_seens():
    from diting.tui import _group_consecutive_ble_seen
    events = [
        _ble_seen(33, "Apple, Inc.", None, "a"),
        _ble_seen(34, "Apple, Inc.", None, "b"),
        _ble_seen(36, "Apple, Inc.", None, "c"),
    ]
    grouped = _group_consecutive_ble_seen(events)
    assert len(grouped) == 1
    rep, count, latest = grouped[0]
    assert rep is events[0]
    assert count == 3
    assert latest is events[-1]


def test_events_screen_does_not_collapse_across_vendor_change():
    from diting.tui import _group_consecutive_ble_seen
    events = [
        _ble_seen(33, "Apple, Inc.", None, "a"),
        _ble_seen(34, "Microsoft", None, "b"),
    ]
    grouped = _group_consecutive_ble_seen(events)
    assert len(grouped) == 2
    assert all(count == 1 and latest is None
               for _ev, count, latest in grouped)


def test_events_screen_non_ble_event_breaks_the_grouping_run():
    from diting.tui import _group_consecutive_ble_seen
    from diting.poller import RoamEvent
    from datetime import datetime, timezone
    roam = RoamEvent(
        timestamp=datetime(2026, 5, 25, 18, 10, 35, tzinfo=timezone.utc),
        previous_bssid="aa:bb:cc:dd:ee:01", new_bssid="aa:bb:cc:dd:ee:02",
        previous_channel=36, new_channel=44,
        previous_ssid="diting", new_ssid="diting",
    )
    events = [
        _ble_seen(33, "Apple, Inc.", None, "a"),
        _ble_seen(34, "Apple, Inc.", None, "b"),
        roam,
        _ble_seen(36, "Apple, Inc.", None, "c"),
    ]
    grouped = _group_consecutive_ble_seen(events)
    # Two BLE folded → one row, roam → one row, trailing BLE → one row.
    assert len(grouped) == 3
    assert grouped[0][1] == 2
    assert grouped[1][0] is roam and grouped[1][1] == 1
    assert grouped[2][1] == 1


def test_events_screen_collapses_rotating_id_label_across_different_identifiers():
    """Three Apple-Continuity-shaped names with DIFFERENT raw values
    still fold because the label `(rotating ID)` is the same."""
    from diting.tui import _group_consecutive_ble_seen
    events = [
        _ble_seen(33, "Apple, Inc.", "NZ1NhvIw3H5T5cSy3kULrJ", "a"),
        _ble_seen(34, "Apple, Inc.", "Mc7g8sUZpL0eX2qY4Wt1Pq", "b"),
        _ble_seen(35, "Apple, Inc.", "qFt5kJ2sLm9wXyZpQrBaUd", "c"),
    ]
    grouped = _group_consecutive_ble_seen(events)
    assert len(grouped) == 1
    assert grouped[0][1] == 3


def test_events_screen_grouped_row_renders_arrow_to_latest_timestamp():
    from diting.tui import _format_ble_device_seen_event
    first = _ble_seen(33, "Apple, Inc.", None, "a")
    latest = _ble_seen(36, "Apple, Inc.", None, "c")
    text = _format_ble_device_seen_event(
        first, count=3, latest=latest,
    ).plain
    assert "×3" in text
    # Timestamps render in local time; compute the expected prefix /
    # arrow from the events' own timezone-aware values so the test
    # passes regardless of the runner's TZ.
    first_local = first.timestamp.astimezone().strftime("%H:%M:%S")
    latest_local = latest.timestamp.astimezone().strftime("%H:%M:%S")
    assert text.startswith(first_local)
    assert f"→ {latest_local}" in text


def test_events_screen_jsonl_log_untouched_by_modal_grouping():
    """Grouping is render-only. The underlying event objects, and any
    per-event JSONL serialization the EventLogger would do, must not
    see the `×N` suffix or the folded representation."""
    from diting.events import event_to_jsonl
    ev = _ble_seen(33, "Apple, Inc.", None, "a")
    line = event_to_jsonl(ev)
    assert '"type":"ble_device_seen"' in line.replace(" ", "")
    assert "×" not in line
    # The per-event renderer also stays at count=1 by default.
    from diting.tui import _format_ble_device_seen_event
    text = _format_ble_device_seen_event(ev).plain
    assert "×" not in text


def test_events_screen_filter_then_group_order_is_filter_first():
    """Filtering to a non-BLE bucket suppresses every BLE row before
    grouping runs; no `×N` row survives. Switching back to BLE
    re-runs grouping over the filtered-down set."""
    from diting.tui import _events_filter_match, _group_consecutive_ble_seen
    from diting.poller import RoamEvent
    from datetime import datetime, timezone
    roam = RoamEvent(
        timestamp=datetime(2026, 5, 25, 18, 10, 35, tzinfo=timezone.utc),
        previous_bssid="aa:bb:cc:dd:ee:01", new_bssid="aa:bb:cc:dd:ee:02",
        previous_channel=36, new_channel=44,
        previous_ssid="diting", new_ssid="diting",
    )
    events = [
        _ble_seen(33, "Apple, Inc.", None, "a"),
        _ble_seen(34, "Apple, Inc.", None, "b"),
        roam,
    ]
    # Filter to roam first.
    filtered_roam = [ev for ev in events
                     if _events_filter_match(ev, "roam")]
    grouped_roam = _group_consecutive_ble_seen(filtered_roam)
    assert len(grouped_roam) == 1
    assert grouped_roam[0][0] is roam
    # Filter to BLE — now grouping fires over the BLE-only set.
    filtered_ble = [ev for ev in events
                    if _events_filter_match(ev, "ble")]
    grouped_ble = _group_consecutive_ble_seen(filtered_ble)
    assert len(grouped_ble) == 1
    assert grouped_ble[0][1] == 2


# ---- events-cascade-census-fold: event-label cascade ----

def _ble_seen_full(vendor, name=None, *, device_type=None,
                   device_class=None, at_launch=False, ts_sec=10):
    from dataclasses import replace
    return replace(
        _ble_seen(ts_sec, vendor, name),
        device_type=device_type, device_class=device_class,
        at_launch=at_launch,
    )


def test_format_ble_seen_uses_helper_name():
    ev = _ble_seen_full("Apple, Inc.", "Magic Keyboard")
    text = _event_text(ev)
    assert "Magic Keyboard" in text
    assert "(unknown)" not in text
    assert "(anonymous)" not in text


def test_format_ble_seen_falls_back_to_device_type():
    ev = _ble_seen_full("Apple, Inc.", None, device_type="Find My target")
    text = _event_text(ev)
    assert "Find My target" in text
    assert "(anonymous)" not in text


def test_format_ble_seen_falls_back_to_device_class():
    ev = _ble_seen_full("Apple, Inc.", None, device_class="iPhone")
    text = _event_text(ev)
    assert "Apple, Inc." in text
    assert "iPhone" in text
    assert "(anonymous)" not in text


def test_format_ble_seen_unknown_when_vendor_only():
    # Vendor resolved but no name / type / class → name slot is
    # (unknown), NOT (anonymous): the device did broadcast a company id.
    ev = _ble_seen_full("HUAWEI Technologies", None)
    text = _event_text(ev)
    assert "HUAWEI Technologies" in text
    assert "(unknown)" in text
    assert "(anonymous)" not in text


def test_format_ble_seen_anonymous_only_when_truly_silent():
    # Nothing at all → (anonymous) occupies the vendor slot (mirroring
    # the BLE list cell), the name slot falls to (unknown).
    ev = _ble_seen_full(None, None)
    text = _event_text(ev)
    assert "(anonymous)" in text
    # Order: vendor slot is anonymous, name slot is unknown.
    assert text.index("(anonymous)") < text.index("(unknown)")


def test_format_ble_left_uses_cascade():
    from datetime import datetime, timezone
    from diting.events import BLEDeviceLeftEvent
    ev = BLEDeviceLeftEvent(
        timestamp=datetime(2026, 5, 20, 12, 0, 0, tzinfo=timezone.utc),
        identifier="abc", name=None, vendor="Apple, Inc.",
        last_rssi_dbm=-80, service_categories=(), seen_for_seconds=12.0,
        device_class="iPhone",
    )
    text = _event_text(ev)
    assert "iPhone" in text
    assert "(anonymous)" not in text


# ---- events-cascade-census-fold: at-launch census fold ----

def test_events_screen_folds_at_launch_census_into_summary_row():
    from diting.tui import _group_consecutive_ble_seen, _fold_at_launch_census, _CensusFold
    events = [
        _ble_seen_full("Apple, Inc.", None, at_launch=True, ts_sec=10),
        _ble_seen_full("Apple, Inc.", None, at_launch=True, ts_sec=11),
        _ble_seen_full("Apple, Inc.", None, at_launch=True, ts_sec=12),
        _ble_seen_full("Microsoft", None, at_launch=True, ts_sec=13),
        _ble_seen_full("Microsoft", None, at_launch=True, ts_sec=14),
    ]
    folded = _fold_at_launch_census(_group_consecutive_ble_seen(events))
    assert len(folded) == 1
    assert isinstance(folded[0], _CensusFold)
    assert folded[0].total == 5
    # Render-only: the fold references the original event objects, so the
    # EventRing and JSONL log are never touched by the modal grouping.
    assert folded[0].groups[0][0] is events[0]


def test_events_screen_census_summary_vendor_breakdown_top3():
    from diting.tui import (
        _group_consecutive_ble_seen, _fold_at_launch_census,
        _format_census_summary, _CensusFold,
    )
    events = (
        [_ble_seen_full("Apple, Inc.", None, at_launch=True, ts_sec=s) for s in (10, 11, 12)]
        + [_ble_seen_full("Microsoft", None, at_launch=True, ts_sec=s) for s in (13, 14)]
        + [_ble_seen_full("Samsung", None, at_launch=True, ts_sec=15)]
        + [_ble_seen_full("Zyxel", None, at_launch=True, ts_sec=16)]
    )
    folded = _fold_at_launch_census(_group_consecutive_ble_seen(events))
    fold = folded[0]
    assert isinstance(fold, _CensusFold)
    assert fold.total == 7
    text = _format_census_summary(fold, expanded=False).plain
    assert "7 devices already present" in text
    assert "Apple, Inc. ×3" in text
    assert "Microsoft ×2" in text
    assert "Samsung ×1" in text
    # Fourth vendor overflows into the ellipsis, not the inline list.
    assert "Zyxel" not in text
    assert "…" in text


def test_events_screen_expand_collapse_census_summary():
    from diting.tui import (
        _group_consecutive_ble_seen, _fold_at_launch_census,
        _format_census_summary,
    )
    events = [_ble_seen_full("Apple, Inc.", None, at_launch=True, ts_sec=s)
              for s in (10, 11)]
    fold = _fold_at_launch_census(_group_consecutive_ble_seen(events))[0]
    assert "enter to expand" in _format_census_summary(fold, expanded=False).plain
    assert "enter to collapse" in _format_census_summary(fold, expanded=True).plain


def test_events_screen_mid_session_seen_not_folded():
    from diting.tui import (
        _group_consecutive_ble_seen, _fold_at_launch_census, _CensusFold,
    )
    # at_launch=False seens are genuine arrivals — never folded.
    events = [
        _ble_seen_full("Apple, Inc.", "Magic Keyboard", at_launch=False, ts_sec=20),
        _ble_seen_full("Microsoft", "Surface", at_launch=False, ts_sec=21),
    ]
    folded = _fold_at_launch_census(_group_consecutive_ble_seen(events))
    assert not any(isinstance(item, _CensusFold) for item in folded)
    assert len(folded) == 2


def test_events_screen_census_fold_respects_ble_filter():
    from diting.tui import (
        _events_filter_match, _group_consecutive_ble_seen,
        _fold_at_launch_census, _CensusFold,
    )
    from diting.poller import RoamEvent
    from datetime import datetime, timezone
    roam = RoamEvent(
        timestamp=datetime(2026, 5, 25, 18, 10, 35, tzinfo=timezone.utc),
        previous_bssid="aa:bb:cc:dd:ee:01", new_bssid="aa:bb:cc:dd:ee:02",
        previous_channel=36, new_channel=44,
        previous_ssid="diting", new_ssid="diting",
    )
    events = [
        _ble_seen_full("Apple, Inc.", None, at_launch=True, ts_sec=10),
        _ble_seen_full("Apple, Inc.", None, at_launch=True, ts_sec=11),
        roam,
    ]
    # Filter to roam → no BLE seens reach the fold → no census row.
    filtered = [ev for ev in events if _events_filter_match(ev, "roam")]
    folded = _fold_at_launch_census(_group_consecutive_ble_seen(filtered))
    assert not any(isinstance(item, _CensusFold) for item in folded)
    # Filter to BLE → the census fold reappears.
    filtered_ble = [ev for ev in events if _events_filter_match(ev, "ble")]
    folded_ble = _fold_at_launch_census(_group_consecutive_ble_seen(filtered_ble))
    assert any(isinstance(item, _CensusFold) for item in folded_ble)


def test_events_screen_census_single_device_not_folded():
    # A lone at-launch device reads worse as a one-line summary than as
    # its own row, so the < 2 threshold passes it through unfolded — and
    # the passthrough is the original triple (fold is render-only).
    from diting.tui import (
        _group_consecutive_ble_seen, _fold_at_launch_census, _CensusFold,
    )
    ev = _ble_seen_full("Apple, Inc.", None, at_launch=True)
    folded = _fold_at_launch_census(_group_consecutive_ble_seen([ev]))
    assert not any(isinstance(item, _CensusFold) for item in folded)
    assert folded[0][0] is ev
