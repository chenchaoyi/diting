"""Pure-logic tests for the TUI helpers — _merge_current and
_group_by_ap. These don't import Textual itself; they exercise the
data transforms that the panels apply before rendering. The TUI
smoke test (test_tui_smoke) covers actually mounting the App.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

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
    _format_duration_short,
    _free_space_distance_m,
    _hex_dump,
    _rssi_sparkline,
    _channel_hint,
    _environment_diagnostic_line,
    _environment_line,
    _event_format_line,
    _group_by_ap,
    _health_line,
    _link_diagnostic_line,
    _link_score,
    _merge_current,
    _score_line,
    _recommended_channel,
    _scan_line,
    _security_badge,
    _sigma_sparkline,
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


def test_event_format_line_latency_spike():
    text = _event_format_line(_spike_event(), NetworkInventory()).plain
    assert "[LATENCY]" in text
    assert "router" in text
    assert "412" in text


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
