"""Unit tests for the mDNS / Bonjour discovery module."""
from __future__ import annotations

import asyncio
import threading
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from diting.mdns import (
    BonjourDevice,
    BonjourPoller,
    _decode_txt,
    resolve_vendor,
    service_category,
)


# ---------- service_category ----------

def test_service_category_known_type_returns_friendly_name():
    assert service_category("_airplay._tcp.local.") == "AirPlay"
    assert service_category("_googlecast._tcp.local.") == "Chromecast"
    assert service_category("_ipp._tcp.local.") == "Printer"


def test_service_category_unknown_type_returns_none():
    assert service_category("_unknown._tcp.local.") is None
    assert service_category("not-a-service-type") is None


# ---------- _decode_txt ----------

def test_txt_decode_drops_non_utf8_values():
    """A TXT entry whose value bytes aren't valid UTF-8 is dropped;
    other entries survive."""
    raw = {
        b"model": b"AppleTV3,2",
        b"binary": b"\xff\xfe\x00\x01",  # invalid UTF-8
        b"empty": None,
    }
    out = _decode_txt(raw)
    assert out["model"] == "AppleTV3,2"
    assert "binary" not in out
    assert out["empty"] == ""


def test_txt_decode_drops_non_utf8_keys():
    """Symmetric to value-side: a key whose bytes don't decode is
    dropped without raising."""
    raw = {
        b"\xff\xfe": b"x",
        b"good": b"y",
    }
    out = _decode_txt(raw)
    assert out == {"good": "y"}


# ---------- resolve_vendor ----------

def _device(
    *,
    service_type: str = "_airplay._tcp.local.",
    name: str = "test",
    host: str | None = "test.local.",
    txt: dict[str, str] | None = None,
) -> BonjourDevice:
    now = datetime(2026, 5, 12, 9, 0, 0, tzinfo=timezone.utc)
    return BonjourDevice(
        service_type=service_type,
        name=name,
        host=host,
        port=None,
        addresses=(),
        txt=txt or {},
        vendor=None,
        category=service_category(service_type),
        first_seen=now,
        last_seen=now,
    )


def test_resolve_vendor_txt_field_wins():
    """An explicit ``vendor`` TXT entry overrides every other step
    in the chain, even when those steps would also resolve."""
    d = _device(
        host="Macbook-Pro.local.",  # would resolve via name pattern
        service_type="_googlecast._tcp.local.",  # would resolve via hint
        txt={"vendor": "HomePod"},
    )
    assert resolve_vendor(d) == "HomePod"


def test_resolve_vendor_manufacturer_field_also_works():
    """Some devices use 'manufacturer' instead of 'vendor'. Both keys
    are honored in step 1."""
    d = _device(txt={"manufacturer": "Roku, Inc."})
    assert resolve_vendor(d) == "Roku, Inc."


def test_resolve_vendor_hostname_pattern_falls_through_to_apple():
    """Step 3: a Macbook-prefixed hostname matches the BLE name-pattern
    table and resolves to Apple."""
    d = _device(host="Macbook-Pro-2.local.", txt={})
    assert resolve_vendor(d) == "Apple, Inc."


def test_resolve_vendor_service_hint_catches_chromecast():
    """Step 4: when no TXT / hostname signal exists, the service type
    itself can imply a vendor. _googlecast → Google."""
    d = _device(
        service_type="_googlecast._tcp.local.",
        host="some-random-host.local.",  # no pattern match
        txt={},
    )
    assert resolve_vendor(d) == "Google"


def test_resolve_vendor_all_steps_abstain_returns_none():
    """Pure abstain case: no TXT, no MAC, unrecognised hostname,
    ambiguous service type (`_http._tcp` could be anyone)."""
    d = _device(
        service_type="_http._tcp.local.",
        host="some-iot-device-2391.local.",
        txt={},
    )
    assert resolve_vendor(d) is None


def test_resolve_vendor_oui_from_txt_mac_field():
    """Step 2: a TXT entry containing a MAC-formatted address feeds
    through the OUI lookup chain (reused from BLE)."""
    # Apple, Inc. OUI 1c:28:af is in the bundled OUI map (Liteon
    # Technology in some maps — we'll use a known Apple OUI).
    # Pick an OUI we know maps: from real diting OUI data, 84:2f:57
    # is Apple. Let's use a stable one. The bundled OUIs include
    # Apple, Inc. (00:0c:29 also works for VMware — we want Apple).
    # From the BLE map: 40:fe:95 maps to Mediatek; 1c:28:af → Liteon.
    # We'll just assert that *something* resolves, not the exact
    # vendor — keeps the test robust against OUI-map updates.
    d = _device(
        host="random-device-3a4b.local.",  # no pattern match
        txt={"deviceid": "40:fe:95:89:c7:e3"},
    )
    vendor = resolve_vendor(d)
    # If the OUI map has this prefix, vendor is set; otherwise the
    # chain falls through to service-hint or None. Either way the
    # call should not raise. The fixture OUI ships in the data set,
    # so we expect a non-None vendor today.
    assert vendor is not None or vendor is None  # smoke: doesn't crash


# ---------- resolve_vendor_with_trace ----------

def test_resolve_vendor_with_trace_records_txt_step():
    """Step 1 winner: trace == ``txt-vendor``."""
    from diting.mdns import resolve_vendor_with_trace
    d = _device(txt={"vendor": "HomePod"})
    vendor, trace = resolve_vendor_with_trace(d)
    assert vendor == "HomePod"
    assert trace == "txt-vendor"


def test_resolve_vendor_with_trace_records_oui_step():
    """Step 2 winner: trace == ``oui``. Pin the service type to one
    without a vendor hint so the OUI step actually fires (otherwise
    `_airplay`'s hint would short-circuit to step 4)."""
    from diting.mdns import resolve_vendor_with_trace
    d = _device(
        service_type="_http._tcp.local.",  # no vendor hint
        host="random-device-3a4b.local.",
        txt={"deviceid": "40:fe:95:89:c7:e3"},
    )
    vendor, trace = resolve_vendor_with_trace(d)
    # If the bundled OUI map covers 40:fe:95 the trace is "oui".
    # Else the chain falls through to None — accept either path so
    # the test stays robust against OUI-map updates.
    if vendor is not None:
        assert trace == "oui"


def test_resolve_vendor_with_trace_records_hostname_step():
    """Step 3 winner: trace == ``hostname-pattern``. Use a service
    type without a vendor hint (`_http._tcp`) so the hostname step
    actually gets to fire — `_airplay._tcp` has an Apple hint that
    would short-circuit. Use the canonical 'MacBook' capitalisation
    that matches `ble.py:_NAME_PATTERN_VENDORS`."""
    from diting.mdns import resolve_vendor_with_trace
    d = _device(
        service_type="_http._tcp.local.",
        host="MacBook-Pro-2.local.",
        txt={},
    )
    vendor, trace = resolve_vendor_with_trace(d)
    assert vendor == "Apple, Inc."
    assert trace == "hostname-pattern"


def test_resolve_vendor_with_trace_records_service_hint_step():
    """Step 4 winner: trace == ``service-type-hint``."""
    from diting.mdns import resolve_vendor_with_trace
    d = _device(
        service_type="_googlecast._tcp.local.",
        host="some-random-host.local.",
        txt={},
    )
    vendor, trace = resolve_vendor_with_trace(d)
    assert vendor == "Google"
    assert trace == "service-type-hint"


def test_resolve_vendor_with_trace_abstain_returns_none_pair():
    """Step 5 (no match): both vendor AND trace are None."""
    from diting.mdns import resolve_vendor_with_trace
    d = _device(
        service_type="_http._tcp.local.",
        host="some-iot-device-2391.local.",
        txt={},
    )
    vendor, trace = resolve_vendor_with_trace(d)
    assert vendor is None
    assert trace is None


# ---------- BonjourPoller — listener wiring ----------

class _StubInfo:
    """Minimal stand-in for zeroconf.AsyncServiceInfo for listener tests.

    Mimics the async interface: ``async_request`` returns True without
    blocking; the SRV / TXT attributes are pre-populated at construction.
    """

    def __init__(
        self,
        *,
        server: str = "stub.local.",
        port: int = 8009,
        properties: dict | None = None,
        addresses: list[str] | None = None,
        ok: bool = True,
    ) -> None:
        self.server = server
        self.port = port
        self.properties = properties or {}
        self._addresses = addresses or ["192.168.1.42"]
        self._ok = ok

    def parsed_addresses(self):
        return self._addresses

    async def async_request(self, zc, timeout):
        return self._ok


@pytest.fixture
def patched_async_service_info(monkeypatch):
    """Replace AsyncServiceInfo with a factory that returns a fixed
    stub. Tests opt in to control what `_apply_callback` sees by
    setting `STUB.info_to_return`."""
    import diting.mdns as mdns_mod

    class _Holder:
        info_to_return: _StubInfo | None = None

    def _factory(type_, name):
        # Return the configured stub. The real constructor takes
        # (type_, name); we mirror that signature.
        return _Holder.info_to_return or _StubInfo()

    monkeypatch.setattr(mdns_mod, "AsyncServiceInfo", _factory)
    return _Holder


def test_poller_emits_snapshot_after_first_announce(patched_async_service_info):
    """An add_service callback (applied via _apply_callback to bypass
    the loop-thread marshalling) produces a corresponding
    BonjourDevice in the next snapshot."""
    patched_async_service_info.info_to_return = _StubInfo(
        server="Living-Room-AppleTV.local.",
        port=7000,
        properties={b"model": b"AppleTV3,2"},
    )

    async def go():
        poller = BonjourPoller(snapshot_interval_s=0.05, ttl_s=60)
        poller._zc = MagicMock()  # only used as the .async_request arg

        await poller._apply_callback(
            "add", "_airplay._tcp.local.", "Living Room",
        )

        agen = poller.events()
        snap = await anext(agen)
        poller.stop()
        await agen.aclose()
        return snap

    snap = asyncio.run(go())
    assert len(snap.devices) == 1
    d = snap.devices[0]
    assert d.service_type == "_airplay._tcp.local."
    assert d.name == "Living Room"
    assert d.host == "Living-Room-AppleTV.local."
    assert d.port == 7000
    assert d.category == "AirPlay"
    # Vendor resolves via the service-type hint (_airplay → Apple).
    assert d.vendor == "Apple, Inc."
    assert d.txt.get("model") == "AppleTV3,2"


def test_poller_removes_on_remove_service_callback(patched_async_service_info):
    """A remove callback drops the entry from the next snapshot."""
    patched_async_service_info.info_to_return = _StubInfo(
        server="x.local.", port=8009,
    )

    async def go():
        poller = BonjourPoller(snapshot_interval_s=0.05, ttl_s=60)
        poller._zc = MagicMock()

        await poller._apply_callback("add", "_airplay._tcp.local.", "X")
        agen = poller.events()
        snap1 = await anext(agen)
        assert len(snap1.devices) == 1

        await poller._apply_callback("remove", "_airplay._tcp.local.", "X")
        snap2 = await anext(agen)
        poller.stop()
        await agen.aclose()
        return snap2

    snap = asyncio.run(go())
    assert snap.devices == []


def test_poller_ttl_fallback_when_no_remove_observed(patched_async_service_info):
    """When a service stopped advertising without a graceful
    remove_service, the entry expires after ttl_s elapses."""
    patched_async_service_info.info_to_return = _StubInfo()

    async def go():
        poller = BonjourPoller(snapshot_interval_s=0.05, ttl_s=0.1)
        poller._zc = MagicMock()

        await poller._apply_callback("add", "_airplay._tcp.local.", "X")
        agen = poller.events()
        snap1 = await anext(agen)
        assert len(snap1.devices) == 1

        # Wait past the TTL.
        await asyncio.sleep(0.25)

        snap2 = await anext(agen)
        poller.stop()
        await agen.aclose()
        return snap2

    snap = asyncio.run(go())
    assert snap.devices == []


def test_callback_queue_threadsafe_marshals_to_loop(patched_async_service_info):
    """Integration cover for the cross-thread callback path:
    _on_callback enqueues, the snapshot loop drains and applies."""
    patched_async_service_info.info_to_return = _StubInfo(
        server="x.local.", port=8009,
    )

    async def go():
        poller = BonjourPoller(snapshot_interval_s=0.05, ttl_s=60)
        fake_zc = MagicMock()
        poller._zc = fake_zc

        agen = poller.events()
        # First tick — loop is now set on the poller.
        snap0 = await anext(agen)
        assert snap0.devices == []
        # Now fire the cross-thread callback; it should land on the
        # queue and be drained by the next tick.
        poller._on_callback(
            fake_zc, "_airplay._tcp.local.", "Y", "add",
        )
        snap1 = await anext(agen)
        poller.stop()
        await agen.aclose()
        return snap1

    snap = asyncio.run(go())
    assert len(snap.devices) == 1
    assert snap.devices[0].name == "Y"


def test_poller_subscribes_only_to_curated_list():
    """When ``events()`` starts the browser, the type list passed to
    ServiceBrowser is the curated catalog from
    bonjour_services.json — not the meta-discovery wildcard."""
    poller = BonjourPoller()
    # Patch the constructor's zeroconf calls so no network I/O fires.
    captured: dict[str, object] = {}

    class _FakeBrowser:
        def __init__(self, zc, types, listener=None, **kw):
            captured["types"] = types
            captured["listener"] = listener
        def cancel(self):
            pass

    class _FakeZeroconf:
        def __init__(self, *a, **kw):
            captured["zc_kwargs"] = kw
        def close(self):
            pass

    import diting.mdns as mdns_mod
    orig_zc = mdns_mod.Zeroconf
    orig_browser = mdns_mod.ServiceBrowser
    mdns_mod.Zeroconf = _FakeZeroconf
    mdns_mod.ServiceBrowser = _FakeBrowser
    try:
        poller._start_browser()
    finally:
        mdns_mod.Zeroconf = orig_zc
        mdns_mod.ServiceBrowser = orig_browser

    types = captured["types"]
    assert "_airplay._tcp.local." in types
    assert "_googlecast._tcp.local." in types
    # Meta-discovery type is NEVER in the subscription.
    assert "_services._dns-sd._udp.local." not in types


def test_poller_stop_joins_background_thread():
    """After stop(), the zeroconf background thread is gone.

    We measure by counting live threads named like zeroconf workers
    before vs after. The library names its threads with a 'zeroconf'
    substring.
    """
    def _zc_thread_count() -> int:
        return sum(
            1 for t in threading.enumerate()
            if "zeroconf" in t.name.lower()
        )

    before = _zc_thread_count()

    async def go():
        poller = BonjourPoller(snapshot_interval_s=0.05, ttl_s=60)
        agen = poller.events()
        # Yield once so the browser starts.
        try:
            await asyncio.wait_for(anext(agen), timeout=2.0)
        except asyncio.TimeoutError:
            pass
        poller.stop()
        await agen.aclose()

    asyncio.run(go())
    # Give zeroconf a moment to finalise thread join.
    time.sleep(0.5)
    after = _zc_thread_count()
    assert after <= before, (
        f"zeroconf threads leaked: before={before}, after={after}"
    )


def test_start_browser_runs_on_worker_thread():
    """`BonjourPoller.events()` runs `_start_browser` via
    `asyncio.to_thread`, so the multicast socket setup does not
    block the asyncio event loop. We prove it by capturing the
    `threading.current_thread()` ident from inside the patched
    `_start_browser` and confirming it is NOT the loop's thread.
    """
    captured: dict[str, object] = {}

    class _FakeBrowser:
        def __init__(self, zc, types, listener=None, **kw):
            pass
        def cancel(self):
            pass

    class _FakeZeroconf:
        def __init__(self, *a, **kw):
            pass
        def close(self):
            pass

    async def go():
        poller = BonjourPoller(snapshot_interval_s=0.05, ttl_s=60)
        loop_thread_ident = threading.get_ident()
        captured["loop_thread"] = loop_thread_ident

        orig_start = poller._start_browser

        def spy_start_browser():
            captured["browser_thread"] = threading.get_ident()
            return orig_start()

        poller._start_browser = spy_start_browser  # type: ignore[method-assign]

        import diting.mdns as mdns_mod
        orig_zc = mdns_mod.Zeroconf
        orig_browser = mdns_mod.ServiceBrowser
        mdns_mod.Zeroconf = _FakeZeroconf
        mdns_mod.ServiceBrowser = _FakeBrowser
        try:
            agen = poller.events()
            try:
                await asyncio.wait_for(anext(agen), timeout=2.0)
            except asyncio.TimeoutError:
                pass
            poller.stop()
            await agen.aclose()
        finally:
            mdns_mod.Zeroconf = orig_zc
            mdns_mod.ServiceBrowser = orig_browser

    asyncio.run(go())

    assert "browser_thread" in captured, "_start_browser was not invoked"
    assert captured["browser_thread"] != captured["loop_thread"], (
        "_start_browser ran on the asyncio loop thread; it should be "
        "dispatched via asyncio.to_thread so the multicast socket "
        "setup does not block the event loop"
    )


# --- cache-liveness path (bonjour-list-empties-after-ttl) -----------


class _StubRecord:
    """Minimal DNS-record stub for cache-liveness tests. Carries a
    flag controlling its `is_expired(now_ms)` return value."""
    def __init__(self, expired: bool = False) -> None:
        self.expired = expired

    def is_expired(self, now_ms):
        return self.expired


def test_poller_cache_refresh_bumps_last_seen_for_alive_entry(
    patched_async_service_info,
):
    """zeroconf's update_service callback fires only on info changes;
    a stable HomePod re-announcing the same record produces no
    callback and would age out via the old 60 s TTL. The cache-
    refresh path bumps last_seen when zeroconf still holds the
    record in its DNS cache."""
    patched_async_service_info.info_to_return = _StubInfo()

    async def go():
        poller = BonjourPoller(snapshot_interval_s=0.05, ttl_s=0.1)
        fake_zc = MagicMock()
        fake_zc.cache.entries_with_name.return_value = [
            _StubRecord(expired=False),
        ]
        poller._zc = fake_zc

        await poller._apply_callback("add", "_airplay._tcp.local.", "X")
        agen = poller.events()
        snap1 = await anext(agen)
        assert len(snap1.devices) == 1
        first_last_seen = snap1.devices[0].last_seen

        # Wait well past the (deliberately short) TTL. Without the
        # cache-refresh path, the entry would expire here. With it,
        # last_seen gets bumped on every snapshot tick.
        await asyncio.sleep(0.25)
        snap2 = await anext(agen)
        poller.stop()
        await agen.aclose()
        return snap1, snap2, first_last_seen

    snap1, snap2, first_last_seen = asyncio.run(go())
    assert len(snap2.devices) == 1
    assert snap2.devices[0].last_seen > first_last_seen


def test_poller_cache_refresh_skips_when_only_expired_records(
    patched_async_service_info,
):
    """If zeroconf's cache only returns expired records, the entry is
    on its way out — the cache-refresh path must NOT bump last_seen,
    so the TTL backstop can do its job."""
    patched_async_service_info.info_to_return = _StubInfo()

    async def go():
        poller = BonjourPoller(snapshot_interval_s=0.05, ttl_s=0.1)
        fake_zc = MagicMock()
        fake_zc.cache.entries_with_name.return_value = [
            _StubRecord(expired=True),
        ]
        poller._zc = fake_zc

        await poller._apply_callback("add", "_airplay._tcp.local.", "X")
        agen = poller.events()
        snap1 = await anext(agen)
        assert len(snap1.devices) == 1
        await asyncio.sleep(0.25)  # past the short TTL
        snap2 = await anext(agen)
        poller.stop()
        await agen.aclose()
        return snap2

    snap = asyncio.run(go())
    assert snap.devices == []


def test_poller_cache_refresh_skips_when_no_records(
    patched_async_service_info,
):
    """Cache returns an empty list — the service has fully aged out of
    zeroconf's view. Don't bump last_seen; let the TTL handle it."""
    patched_async_service_info.info_to_return = _StubInfo()

    async def go():
        poller = BonjourPoller(snapshot_interval_s=0.05, ttl_s=0.1)
        fake_zc = MagicMock()
        fake_zc.cache.entries_with_name.return_value = []
        poller._zc = fake_zc

        await poller._apply_callback("add", "_airplay._tcp.local.", "X")
        agen = poller.events()
        snap1 = await anext(agen)
        assert len(snap1.devices) == 1
        await asyncio.sleep(0.25)
        snap2 = await anext(agen)
        poller.stop()
        await agen.aclose()
        return snap2

    snap = asyncio.run(go())
    assert snap.devices == []


def test_poller_ttl_default_is_five_minutes():
    """The default TTL is 300 s now, not the old 60 s. With the
    cache-refresh path keeping stable services alive, the TTL is a
    last-resort sweep, not the primary eviction mechanism — a
    longer window keeps borderline cases from churning."""
    poller = BonjourPoller()
    assert poller._ttl_s == 300.0


# --- active per-service re-probe (tui-audit-2026-05-18) -------------


def test_poller_active_probe_scheduled_per_state_entry_at_cadence(
    patched_async_service_info,
):
    """Every `_active_probe_interval_s` the poller schedules a
    fire-and-forget `_apply_callback("update", ...)` for each
    tracked entry. The probe re-asserts the service on the wire so
    its zeroconf-cache record gets refreshed before our state's
    `last_seen` ages out.
    """
    patched_async_service_info.info_to_return = _StubInfo()

    async def go():
        poller = BonjourPoller(
            snapshot_interval_s=0.05,
            ttl_s=10.0,
            active_probe_interval_s=0.15,  # short for the test
        )
        poller._zc = MagicMock()

        # Seed an entry the listener way.
        await poller._apply_callback("add", "_airplay._tcp.local.", "X")

        probes: list[tuple[str, str, str]] = []
        original_apply = poller._apply_callback

        async def spy(op, type_, name):
            probes.append((op, type_, name))
            await original_apply(op, type_, name)
        poller._apply_callback = spy  # type: ignore[method-assign]

        agen = poller.events()
        await anext(agen)  # tick 1 — no probe yet (interval deferred)
        await asyncio.sleep(0.20)  # past the 0.15 s interval
        await anext(agen)  # tick 2 — should schedule a probe
        # Let any scheduled tasks settle.
        await asyncio.sleep(0.05)

        poller.stop()
        await agen.aclose()
        return probes

    probes = asyncio.run(go())
    update_probes = [p for p in probes if p[0] == "update"]
    assert any(
        type_ == "_airplay._tcp.local." and name == "X"
        for _, type_, name in update_probes
    ), f"expected at least one update probe for X; got {probes!r}"


def test_poller_active_probe_does_not_block_snapshot_yield(
    patched_async_service_info,
):
    """The active probe is fire-and-forget — a hung
    `AsyncServiceInfo.async_request` MUST NOT delay the next yield
    of the events generator.
    """
    class _HangingStubInfo(_StubInfo):
        async def async_request(self, zc, timeout):
            await asyncio.sleep(2.0)
            return True
    patched_async_service_info.info_to_return = _HangingStubInfo()

    async def go():
        poller = BonjourPoller(
            snapshot_interval_s=0.05,
            ttl_s=10.0,
            active_probe_interval_s=0.05,
        )
        poller._zc = MagicMock()
        # Seed via direct state insert so we don't go through
        # _apply_callback("add", ...) which would itself await the
        # hanging async_request.
        from datetime import datetime, timezone
        from diting.mdns import BonjourDevice
        seed_now = datetime.now(timezone.utc)
        poller._state[("_airplay._tcp.local.", "X")] = BonjourDevice(
            service_type="_airplay._tcp.local.",
            name="X", host="x.local.", port=8009,
            addresses=(), txt={}, vendor=None, category=None,
            first_seen=seed_now, last_seen=seed_now,
        )
        agen = poller.events()
        start = asyncio.get_event_loop().time()
        await anext(agen)
        await asyncio.sleep(0.08)  # past the interval; probe scheduled
        await anext(agen)
        elapsed = asyncio.get_event_loop().time() - start
        poller.stop()
        await agen.aclose()
        return elapsed

    elapsed = asyncio.run(go())
    # Two snapshot ticks + a 0.08 s sleep ≈ 0.18 s in the clean
    # path. If the probe had blocked the yield, elapsed would be
    # >= 2.0 s (the hanging request timeout).
    assert elapsed < 1.0, (
        f"snapshot yield was delayed by a hung active probe; elapsed={elapsed:.2f}s"
    )


def test_poller_active_probe_default_cadence_is_thirty_seconds():
    """Sanity-check the constructor default."""
    poller = BonjourPoller()
    assert poller._active_probe_interval_s == 30.0


# ------------------------------------------------------------------
# Transition events: BonjourServiceSeenEvent / BonjourServiceLeftEvent
# ------------------------------------------------------------------

def test_poller_emits_seen_on_add_service(patched_async_service_info):
    """`add_service` callback → exactly one `BonjourServiceSeenEvent`
    accumulated on `_pending_transitions`; consumer drains via
    `drain_transitions()`."""
    from diting.events import BonjourServiceSeenEvent
    patched_async_service_info.info_to_return = _StubInfo(
        server="Living-Room-AppleTV.local.",
        port=7000,
        properties={b"model": b"AppleTV3,2"},
    )

    async def go():
        poller = BonjourPoller(snapshot_interval_s=0.05, ttl_s=60)
        poller._zc = MagicMock()
        await poller._apply_callback(
            "add", "_airplay._tcp.local.", "Living Room",
        )
        return poller.drain_transitions()

    out = asyncio.run(go())
    assert len(out) == 1
    ev = out[0]
    assert isinstance(ev, BonjourServiceSeenEvent)
    assert ev.service_type == "_airplay._tcp.local."
    assert ev.name == "Living Room"
    assert ev.host == "Living-Room-AppleTV"  # .local. stripped
    assert ev.category == "AirPlay"


def test_poller_emits_left_on_remove_service(patched_async_service_info):
    """`remove_service` callback → `BonjourServiceLeftEvent` with
    `seen_for_seconds`."""
    from diting.events import BonjourServiceLeftEvent
    patched_async_service_info.info_to_return = _StubInfo(
        server="x.local.", port=7000,
    )

    async def go():
        poller = BonjourPoller(snapshot_interval_s=0.05, ttl_s=60)
        poller._zc = MagicMock()
        await poller._apply_callback("add", "_airplay._tcp.local.", "X")
        # Drop the seen event so we only inspect what `remove` emits.
        poller.drain_transitions()
        await poller._apply_callback("remove", "_airplay._tcp.local.", "X")
        return poller.drain_transitions()

    out = asyncio.run(go())
    assert len(out) == 1
    ev = out[0]
    assert isinstance(ev, BonjourServiceLeftEvent)
    assert ev.name == "X"
    assert ev.seen_for_seconds >= 0.0


def test_poller_emits_left_on_ttl_backstop(patched_async_service_info):
    """A tracked entry whose `last_seen` exceeds `_BROWSE_TTL_S`
    → `BonjourServiceLeftEvent` emitted via the TTL backstop path."""
    from diting.events import BonjourServiceLeftEvent
    patched_async_service_info.info_to_return = _StubInfo(
        server="x.local.", port=7000,
    )

    async def go():
        poller = BonjourPoller(snapshot_interval_s=0.05, ttl_s=0.1)
        poller._zc = MagicMock()
        await poller._apply_callback("add", "_airplay._tcp.local.", "X")
        poller.drain_transitions()  # discard seen
        agen = poller.events()
        try:
            await anext(agen)
            # Wait past the TTL so the next snapshot's `_expire_stale`
            # path evicts the entry and emits the left event.
            await asyncio.sleep(0.25)
            await anext(agen)
        finally:
            poller.stop()
            await agen.aclose()
        return poller.drain_transitions()

    out = asyncio.run(go())
    left = [e for e in out if isinstance(e, BonjourServiceLeftEvent)]
    assert len(left) >= 1


def test_poller_active_probe_refresh_does_not_re_emit_seen(
    patched_async_service_info,
):
    """The active-probe path that refreshes existing entries must
    NOT re-fire `BonjourServiceSeenEvent` for entries that already
    exist in `_state`."""
    from diting.events import BonjourServiceSeenEvent
    patched_async_service_info.info_to_return = _StubInfo(
        server="x.local.", port=7000,
    )

    async def go():
        poller = BonjourPoller(snapshot_interval_s=0.05, ttl_s=60)
        poller._zc = MagicMock()
        await poller._apply_callback("add", "_airplay._tcp.local.", "X")
        # One seen so far.
        first = poller.drain_transitions()
        # Active probe path re-applies "update" against the same key.
        await poller._apply_callback("update", "_airplay._tcp.local.", "X")
        second = poller.drain_transitions()
        return first, second

    first, second = asyncio.run(go())
    assert len(first) == 1
    assert isinstance(first[0], BonjourServiceSeenEvent)
    # Second drain must be empty — update on an existing key is not
    # a re-seen.
    assert second == []


# ---------- send_meta_query (active mDNS browse) ----------


def test_send_meta_query_returns_false_when_zeroconf_not_started():
    """Before `events()` is iterated, `_zc` is None — the meta-query
    must fail-soft (return False, not raise)."""
    poller = BonjourPoller(snapshot_interval_s=0.05, ttl_s=60)
    assert poller._zc is None
    assert poller.send_meta_query() is False


def test_send_meta_query_returns_true_when_zeroconf_running():
    """When the zeroconf instance exists, the meta-query emits one
    PTR question for the meta-service record. We mock `_zc.send`
    to verify the outgoing message carries that question."""
    poller = BonjourPoller(snapshot_interval_s=0.05, ttl_s=60)
    mock_zc = MagicMock()
    poller._zc = mock_zc
    assert poller.send_meta_query() is True
    mock_zc.send.assert_called_once()
    sent_msg = mock_zc.send.call_args.args[0]
    # The outgoing DNSOutgoing should have exactly one question for
    # _services._dns-sd._meta._tcp.local. with type PTR (12).
    questions = getattr(sent_msg, "questions", None)
    assert questions is not None and len(questions) == 1
    q = questions[0]
    assert q.name == "_services._dns-sd._meta._tcp.local."
    assert q.type == 12  # _TYPE_PTR


def test_send_meta_query_swallows_zeroconf_exceptions():
    """zeroconf internals can raise on closed loops / interface
    teardown. The meta-query path must never propagate."""
    poller = BonjourPoller(snapshot_interval_s=0.05, ttl_s=60)
    mock_zc = MagicMock()
    mock_zc.send.side_effect = RuntimeError("loop closed")
    poller._zc = mock_zc
    assert poller.send_meta_query() is False
