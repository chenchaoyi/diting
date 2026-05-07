"""Pure-logic tests for the TUI helpers — _merge_current and
_group_by_ap. These don't import Textual itself; they exercise the
data transforms that the panels apply before rendering. The TUI
smoke test (test_tui_smoke) covers actually mounting the App.
"""
from __future__ import annotations

from datetime import datetime

import pytest

from wifiscope.ble import BLEDevice
from wifiscope.models import Connection, ScanResult
from wifiscope.network import APEntry, NetworkInventory
from wifiscope.tui import (
    _best_same_ssid_candidate,
    _ble_categories_line,
    _ble_closest_line,
    _ble_connected_line,
    _ble_diagnostic_lines,
    _ble_label_summary,
    _ble_vendors_line,
    _ble_visible_line,
    _channel_hint,
    _environment_line,
    _group_by_ap,
    _health_line,
    _link_score,
    _merge_current,
    _score_line,
    _recommended_channel,
    _scan_line,
    _security_badge,
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


def test_environment_line_surfaces_scan_diagnostics():
    conn = _conn(channel=36)
    rows = [
        _scan("aa:aa:aa:aa:aa:01", ssid="x", channel=1, width=40,
              security="Open", country_code="CN"),
        _scan("aa:aa:aa:aa:aa:02", ssid="", channel=6, width=20,
              country_code="US"),
        _scan("aa:aa:aa:aa:aa:03", ssid="y", channel=36,
              country_code="CN"),
    ]
    text = _environment_line(rows, conn).plain
    assert "3 BSSIDs" in text
    assert "2.4G 2" in text
    assert "hidden in this scan: 1" in text
    assert "open 1" in text
    assert "2.4G HT40 1" in text
    assert "CC CN/US" in text
    assert "current ch peers 1" in text


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
    # Unknown (no vendor) gets a separate "? N" tag rather than being
    # silently dropped, so the user sees the full picture.
    assert "? 3" in text


def test_ble_categories_line_groups_by_service_category():
    # Apple Watch advertises both HID (1812) and Heart Rate (180D),
    # which should each contribute one to its bucket — never two.
    apple_watch = _ble_dev(identifier="aw1", services=("180D", "1812"))
    airpods = _ble_dev(identifier="ap1", services=("110A",))  # Audio
    nameless = _ble_dev(identifier="nx", services=())  # no category
    text = _ble_categories_line(
        [apple_watch, airpods, nameless]
    ).plain
    assert "Heart Rate 1" in text
    assert "HID 1" in text
    assert "Audio 1" in text
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
    assert "iBeacon 2" in text
    assert "AirTag 1" in text
    assert "iPhone 1" in text


def test_ble_label_summary_prefers_type_over_service_category():
    """A device tagged AirTag with FD5A service shows 'AirTag · Find My'
    rather than just 'Find My' or just 'AirTag' — the type answers
    'what is this' first, the category gives extra context. Identical
    halves collapse so we don't render 'Heart Rate · Heart Rate'."""
    airtag = _ble_dev(services=("FD5A",), type="AirTag")
    summary = _ble_label_summary(airtag)
    assert "AirTag" in summary
    assert "Find My" in summary
    assert summary == "AirTag · Find My"


def test_ble_label_summary_falls_back_to_service_category_when_no_type():
    """No type / device_class → label is just the service category,
    matching the v0.5.0 'services' column behaviour exactly. This is
    the path most non-Apple, non-Find-My devices take."""
    plain = _ble_dev(services=("180D",))  # Heart Rate only
    assert _ble_label_summary(plain) == "Heart Rate"


def test_ble_label_summary_uses_device_class_when_no_type():
    """Apple Nearby Info gives device_class but no type. The summary
    surfaces 'iPhone' / 'Mac' / 'Apple Watch' so the user can tell a
    laptop from a watch among the rotating Apple beacons."""
    iphone = _ble_dev(services=(), device_class="iPhone")
    assert _ble_label_summary(iphone) == "iPhone"


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
