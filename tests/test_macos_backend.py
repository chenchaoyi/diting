"""Unit tests for the Tx Rate idle cache in MacOSWiFiBackend.

The backend's `get_connection` reads `iface.transmitRate()` from
CoreWLAN; that value flickers to 0 when the radio is momentarily
idle. The idle cache substitutes the last non-zero observation
on the same (ssid, bssid) so the TUI doesn't render "n/a" on an
otherwise-stable link.

These tests exercise the cache logic without needing CoreWLAN or
pyobjc — the resolver is a pure method.
"""
from __future__ import annotations

import importlib.util
import sys


def _backend_class():
    """Import MacOSWiFiBackend without triggering pyobjc on non-mac
    runners. pyobjc IS available locally where we ship, so this is
    a straight import in CI as well."""
    from diting.macos_backend import MacOSWiFiBackend
    return MacOSWiFiBackend


def _resolver(monkeypatch):
    """Return a backend instance with the cache attrs initialised
    but no CoreWLAN client (we never touch `_client` from inside
    `_resolve_tx_rate`)."""
    cls = _backend_class()
    inst = cls.__new__(cls)
    inst._last_tx_rate_mbps = None
    inst._last_tx_rate_key = (None, None)
    return inst


def test_tx_rate_idle_cache_substitutes_on_zero_same_ap(monkeypatch):
    """Same (ssid, bssid), first poll returns 144, second poll returns
    0 → the cache substitutes 144 with `idle=True`."""
    b = _resolver(monkeypatch)
    rate, idle = b._resolve_tx_rate(
        ssid="tedo_5G", bssid="40:fe:95:8a:3c:58", observed=144.0,
    )
    assert rate == 144.0
    assert idle is False
    rate, idle = b._resolve_tx_rate(
        ssid="tedo_5G", bssid="40:fe:95:8a:3c:58", observed=None,
    )
    assert rate == 144.0
    assert idle is True


def test_tx_rate_idle_cache_clears_on_bssid_change(monkeypatch):
    """Roam to a new BSSID drops the prior cache so a `n/a` on the new
    AP doesn't surface a stale value from the old AP."""
    b = _resolver(monkeypatch)
    b._resolve_tx_rate(
        ssid="tedo_5G", bssid="40:fe:95:8a:3c:58", observed=144.0,
    )
    rate, idle = b._resolve_tx_rate(
        ssid="tedo_5G", bssid="40:fe:95:89:c7:e3", observed=None,
    )
    assert rate is None
    assert idle is False


def test_tx_rate_idle_cache_clears_on_ssid_change(monkeypatch):
    """Reassociating to a different SSID is also a key change — the
    new association starts with a clean cache."""
    b = _resolver(monkeypatch)
    b._resolve_tx_rate(
        ssid="tedo_5G", bssid="40:fe:95:8a:3c:58", observed=144.0,
    )
    rate, idle = b._resolve_tx_rate(
        ssid="OtherNet", bssid="40:fe:95:8a:3c:58", observed=None,
    )
    assert rate is None
    assert idle is False


def test_tx_rate_idle_flag_false_on_first_zero_with_no_history(monkeypatch):
    """First-ever poll on a fresh association returns 0 → no cached
    value exists, so the substitute path is NOT taken; the field
    surfaces `None` with `idle=False`. The TUI then renders `n/a`,
    which is the right answer when nothing has ever been observed."""
    b = _resolver(monkeypatch)
    rate, idle = b._resolve_tx_rate(
        ssid="tedo_5G", bssid="40:fe:95:8a:3c:58", observed=None,
    )
    assert rate is None
    assert idle is False


def test_tx_rate_idle_cache_resets_when_subsequent_observation_is_nonzero(
    monkeypatch,
):
    """A non-zero observation always wins over the cache. After
    surfacing a substituted value once, a real reading on the next
    tick clears the idle flag and refreshes the cache."""
    b = _resolver(monkeypatch)
    b._resolve_tx_rate(
        ssid="tedo_5G", bssid="40:fe:95:8a:3c:58", observed=144.0,
    )
    _, idle1 = b._resolve_tx_rate(
        ssid="tedo_5G", bssid="40:fe:95:8a:3c:58", observed=None,
    )
    assert idle1 is True
    rate, idle2 = b._resolve_tx_rate(
        ssid="tedo_5G", bssid="40:fe:95:8a:3c:58", observed=200.0,
    )
    assert rate == 200.0
    assert idle2 is False
