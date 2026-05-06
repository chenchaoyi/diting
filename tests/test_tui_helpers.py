"""Pure-logic tests for the TUI helpers — _merge_current and
_group_by_ap. These don't import Textual itself; they exercise the
data transforms that the panels apply before rendering. The TUI
smoke test (test_tui_smoke) covers actually mounting the App.
"""
from __future__ import annotations

from datetime import datetime

import pytest

from wifiscope.models import Connection, ScanResult
from wifiscope.network import APEntry, NetworkInventory
from wifiscope.tui import _group_by_ap, _merge_current


def _conn(bssid="40:fe:95:89:c7:e3", ssid="tedo_5G", rssi=-60, channel=48):
    return Connection(
        ssid=ssid, bssid=bssid, rssi_dbm=rssi, noise_dbm=-94,
        tx_rate_mbps=300.0, channel=channel, channel_width_mhz=80,
        channel_band="5 GHz", phy_mode="802.11ax", security="WPA2 Personal",
        mcs_index=5, nss=2, timestamp=datetime.now(),
    )


def _scan(bssid, ssid="x", rssi=-70, channel=36):
    return ScanResult(
        ssid=ssid, bssid=bssid, rssi_dbm=rssi, noise_dbm=-94,
        channel=channel, channel_width_mhz=20, channel_band="5 GHz",
        phy_mode=None, security=None, timestamp=datetime.now(),
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
