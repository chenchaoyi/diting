"""Unit tests for `WiFiPoller`'s roam-detection emission shape.

We drive `_maybe_emit_roam` directly with synthetic `Connection`
snapshots, then inspect the events queued by the poller.
"""
from __future__ import annotations

from datetime import datetime, timezone

from diting.models import Connection
from diting.poller import RoamEvent, WiFiPoller


def _conn(bssid: str, ssid: str | None, channel: int | None = 36) -> Connection:
    return Connection(
        ssid=ssid,
        bssid=bssid,
        rssi_dbm=-60,
        noise_dbm=-94,
        tx_rate_mbps=144.0,
        channel=channel,
        channel_width_mhz=80,
        channel_band="5 GHz",
        phy_mode="802.11ax",
        security="WPA2 Personal",
        mcs_index=3,
        nss=1,
        timestamp=datetime(2026, 5, 18, 9, 49, tzinfo=timezone.utc),
    )


def test_roam_event_fills_ssid_from_connection_updates():
    """Two consecutive `Connection`s with different BSSIDs produce a
    `RoamEvent` whose `previous_ssid` / `new_ssid` match the SSIDs
    the poller observed on each side."""
    poller = WiFiPoller(backend=None)
    poller._maybe_emit_roam(_conn(bssid="aa:aa:aa:aa:aa:01", ssid="tedo"))
    # First call seeds _last_bssid; no event emitted yet.
    assert poller._queue.empty()
    poller._maybe_emit_roam(_conn(bssid="aa:aa:aa:aa:aa:02", ssid="tedo_5G"))
    assert poller._queue.qsize() == 1
    event = poller._queue.get_nowait()
    assert isinstance(event, RoamEvent)
    assert event.previous_bssid == "aa:aa:aa:aa:aa:01"
    assert event.new_bssid == "aa:aa:aa:aa:aa:02"
    assert event.previous_ssid == "tedo"
    assert event.new_ssid == "tedo_5G"


def test_roam_event_ssid_pair_when_same_network():
    """Band-switch case: same SSID on both sides — both fields equal."""
    poller = WiFiPoller(backend=None)
    poller._maybe_emit_roam(
        _conn(bssid="aa:aa:aa:aa:aa:01", ssid="tedo", channel=1),
    )
    poller._maybe_emit_roam(
        _conn(bssid="aa:aa:aa:aa:aa:02", ssid="tedo", channel=36),
    )
    event = poller._queue.get_nowait()
    assert event.previous_ssid == "tedo"
    assert event.new_ssid == "tedo"


def test_roam_event_ssid_none_on_disassociation_reset():
    """Disassociation clears the SSID memo so the next associate
    doesn't synthesize a roam with a stale previous_ssid."""
    poller = WiFiPoller(backend=None)
    poller._maybe_emit_roam(_conn(bssid="aa:aa:aa:aa:aa:01", ssid="tedo"))
    poller._maybe_emit_roam(None)  # disassociation
    poller._maybe_emit_roam(_conn(bssid="aa:aa:aa:aa:aa:02", ssid="office"))
    # No roam event — the disassociation reset _last_bssid, so the
    # re-association is a fresh seed, not a roam.
    assert poller._queue.empty()
    assert poller._last_ssid == "office"
