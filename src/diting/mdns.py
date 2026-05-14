"""mDNS / Bonjour passive discovery.

A third observation surface alongside Wi-Fi (CoreWLAN) and BLE
(diting-tianer): every device on the local link that announces itself
via DNS-SD becomes visible here — AppleTVs, HomePods, printers, NAS,
Chromecasts, HomeKit accessories, your colleague's ``Macbook-Pro.local``.

Listen-only: subscribes to a curated list of well-known service types
(see ``data/bonjour_services.json``) and never browses the meta-
discovery type ``_services._dns-sd._udp.local.``. No active probes,
no host A/AAAA lookups beyond what the announce already includes.

The ``zeroconf`` library is imported at top level inside this module
ONLY — ``tui.py`` MUST NOT import this module at load time. The TUI
imports ``BonjourPoller`` lazily on first activation of the mDNS view
so users who never press ``n`` past BLE pay nothing.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import threading
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Mapping

from zeroconf import (
    InterfaceChoice,
    ServiceBrowser,
    ServiceListener,
    Zeroconf,
)
from zeroconf.asyncio import AsyncServiceInfo

from .ble import _NAME_PATTERN_VENDORS, load_ouis, lookup_oui_vendor

# Cached OUI table for the vendor-resolution chain. Loaded lazily on
# first vendor lookup so module import stays cheap.
_OUI_TABLE: dict[str, str] | None = None


def _ouis() -> dict[str, str]:
    global _OUI_TABLE
    if _OUI_TABLE is None:
        _OUI_TABLE = load_ouis()
    return _OUI_TABLE


_log = logging.getLogger(__name__)


# Catalog of well-known service types we subscribe to. Loaded at
# import time from data/bonjour_services.json so the curated list is
# easy to extend without touching code.
def _load_services() -> dict[str, str]:
    path = Path(__file__).parent / "data" / "bonjour_services.json"
    return json.loads(path.read_text(encoding="utf-8"))


_SERVICE_CATEGORIES: dict[str, str] = _load_services()


def service_category(service_type: str) -> str | None:
    """Return the friendly category name for a service type, or None.

    Forward-compatible with future service types that aren't yet in
    the curated list: ``None`` signals "we don't have a friendly
    label". In v1 ``BonjourPoller`` only subscribes to types in
    ``_SERVICE_CATEGORIES``, so unknown types never reach the panel —
    but the function stays honest in case the curated list grows
    without callers updating.
    """
    return _SERVICE_CATEGORIES.get(service_type)


_SERVICE_VENDOR_HINTS: dict[str, str] = {
    "_googlecast._tcp.local.": "Google",
    "_sonos._tcp.local.": "Sonos",
    "_airplay._tcp.local.": "Apple, Inc.",
    "_raop._tcp.local.": "Apple, Inc.",
    "_companion-link._tcp.local.": "Apple, Inc.",
    "_hap._tcp.local.": "Apple, Inc.",
    "_homekit._tcp.local.": "Apple, Inc.",
}

_MAC_RE = re.compile(
    r"\b([0-9a-fA-F]{2}[:-]){5}[0-9a-fA-F]{2}\b"
)


@dataclass(frozen=True, slots=True)
class BonjourDevice:
    service_type: str
    name: str
    host: str | None
    port: int | None
    addresses: tuple[str, ...]
    txt: dict[str, str]
    vendor: str | None
    category: str | None
    first_seen: datetime
    last_seen: datetime


@dataclass(frozen=True, slots=True)
class BonjourScanUpdate:
    devices: list[BonjourDevice]


def _decode_txt(raw_txt: Mapping[bytes, bytes | None]) -> dict[str, str]:
    """Decode the bytes-keyed TXT dict that zeroconf hands us.

    Drops entries whose key OR value bytes don't decode as UTF-8.
    Empty values become ``""``. The `name=` pseudo-key that zeroconf
    sometimes synthesises is preserved if it decodes cleanly.
    """
    out: dict[str, str] = {}
    for k_bytes, v_bytes in raw_txt.items():
        try:
            k = k_bytes.decode("utf-8")
        except (UnicodeDecodeError, AttributeError):
            continue
        if v_bytes is None:
            out[k] = ""
            continue
        try:
            out[k] = v_bytes.decode("utf-8")
        except UnicodeDecodeError:
            continue
    return out


def _name_pattern_vendor(host: str | None) -> str | None:
    """Match host against the BLE name-pattern table.

    Reuses ``ble._NAME_PATTERN_VENDORS`` because the hardware
    ecosystem (Apple / HP / Sonos / Synology / Roku) overlaps between
    the radio-layer BLE world and the network-layer mDNS world.
    """
    if not host:
        return None
    # Strip trailing `.local.` / `.local` so the regex sees a clean
    # device name.
    bare = host.rstrip(".")
    if bare.endswith(".local"):
        bare = bare[: -len(".local")]
    for pattern, vendor in _NAME_PATTERN_VENDORS:
        if vendor is None:
            continue
        if re.match(pattern, bare):
            return vendor
    return None


def resolve_vendor(device: BonjourDevice) -> str | None:
    """5-step deterministic vendor chain.

    1. TXT explicit ``vendor`` / ``manufacturer`` field.
    2. OUI lookup against any MAC-formatted address in TXT.
    3. Hostname pattern (Apple- / Sonos- / Macbook- / HP- …).
    4. Service-type vendor hint (``_googlecast._tcp`` → Google).
    5. Abstain → None.
    """
    # Step 1: TXT explicit vendor field.
    for key in ("vendor", "manufacturer"):
        v = device.txt.get(key)
        if v:
            return v
    # Step 2: OUI lookup against any MAC-looking TXT value.
    for value in device.txt.values():
        match = _MAC_RE.search(value)
        if match:
            vendor = lookup_oui_vendor(match.group(0), _ouis())
            if vendor:
                return vendor
    # Step 3: hostname pattern.
    if device.host:
        vendor = _name_pattern_vendor(device.host)
        if vendor:
            return vendor
    # Step 4: service-type hint.
    hint = _SERVICE_VENDOR_HINTS.get(device.service_type)
    if hint:
        return hint
    # Step 5: abstain.
    return None


class _Listener(ServiceListener):
    """zeroconf callback shim.

    The library fires callbacks on a background thread; we marshal
    each one onto the asyncio loop the poller owns via
    ``call_soon_threadsafe`` so all state mutation stays single-
    threaded.
    """

    def __init__(self, poller: BonjourPoller) -> None:
        self._poller = poller

    def add_service(
        self, zc: Zeroconf, type_: str, name: str,
    ) -> None:
        self._poller._on_callback(zc, type_, name, "add")

    def update_service(
        self, zc: Zeroconf, type_: str, name: str,
    ) -> None:
        self._poller._on_callback(zc, type_, name, "update")

    def remove_service(
        self, zc: Zeroconf, type_: str, name: str,
    ) -> None:
        self._poller._on_callback(zc, type_, name, "remove")


class BonjourPoller:
    """Async iterator over snapshots of the local mDNS airspace.

    Mirrors ``BLEPoller``'s contract:

    * ``__init__`` configures cadence + TTL but does not start any
      I/O.
    * ``events()`` async-iterates ``BonjourScanUpdate`` values; the
      first iteration starts the zeroconf browser.
    * ``stop()`` synchronously closes zeroconf so background threads
      join before the TUI exits.

    The browser is bound to all "up" interfaces (the zeroconf
    default), which on a typical Mac means the active Wi-Fi link —
    exactly the local airspace the user cares about.
    """

    def __init__(
        self,
        *,
        snapshot_interval_s: float = 2.0,
        ttl_s: float = 60.0,
    ) -> None:
        self._snapshot_interval_s = snapshot_interval_s
        self._ttl_s = ttl_s
        self._zc: Zeroconf | None = None
        self._browser: ServiceBrowser | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stopped = False
        # State keyed by (service_type, name) — the canonical
        # service-instance identifier per RFC 6763.
        self._state: dict[tuple[str, str], BonjourDevice] = {}
        # Pending callbacks the listener pushed onto the loop;
        # processed in the snapshot tick to keep state ops single-
        # threaded.
        self._queue: asyncio.Queue[tuple[str, str, str]] = asyncio.Queue()

    async def events(self) -> AsyncIterator[BonjourScanUpdate]:
        """Yield one ``BonjourScanUpdate`` per snapshot interval.

        Idempotent: the first invocation starts the browser; later
        invocations of the same generator continue ticking.
        """
        self._loop = asyncio.get_running_loop()
        if self._zc is None:
            # `Zeroconf()` opens a UDP multicast socket and joins
            # 224.0.0.251:5353; that handshake can take 100 – 500 ms
            # on macOS. Run it on a worker thread so the asyncio
            # event loop stays responsive across view switches.
            await asyncio.to_thread(self._start_browser)
        try:
            while not self._stopped:
                # Drain anything the listener queued since the last
                # tick. ``queue.get_nowait`` raises QueueEmpty when
                # nothing's there — wrap in a defensive try.
                while True:
                    try:
                        op, type_, name = self._queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                    await self._apply_callback(op, type_, name)
                self._expire_stale(datetime.now(timezone.utc))
                yield BonjourScanUpdate(
                    devices=sorted(
                        self._state.values(),
                        key=lambda d: (
                            d.category or "",
                            (d.vendor or "").lower(),
                            d.name.lower(),
                        ),
                    ),
                )
                await asyncio.sleep(self._snapshot_interval_s)
        finally:
            # Best-effort cleanup if the generator is closed early.
            if not self._stopped:
                self.stop()

    def stop(self) -> None:
        """Close the zeroconf browser and join its background thread.

        Idempotent — safe to call from on_unmount even if ``events()``
        was never iterated.
        """
        self._stopped = True
        if self._browser is not None:
            try:
                self._browser.cancel()
            except Exception:
                pass
            self._browser = None
        if self._zc is not None:
            try:
                self._zc.close()
            except Exception:
                pass
            self._zc = None

    def _start_browser(self) -> None:
        self._zc = Zeroconf(interfaces=InterfaceChoice.Default)
        listener = _Listener(self)
        self._browser = ServiceBrowser(
            self._zc,
            list(_SERVICE_CATEGORIES.keys()),
            listener=listener,
        )

    def _on_callback(
        self, zc: Zeroconf, type_: str, name: str, op: str,
    ) -> None:
        """Called on the zeroconf background thread.

        We forward to the asyncio loop via ``call_soon_threadsafe``
        rather than mutating state directly, so all state changes
        happen on the loop thread.
        """
        if self._loop is None or self._stopped:
            return
        try:
            self._loop.call_soon_threadsafe(
                self._queue.put_nowait, (op, type_, name),
            )
        except RuntimeError:
            # Loop is closed; we're shutting down. Drop silently.
            pass

    async def _apply_callback(
        self, op: str, type_: str, name: str,
    ) -> None:
        key = (type_, name)
        if op == "remove":
            self._state.pop(key, None)
            return
        if self._zc is None:
            return
        # zeroconf >= 0.130 forbids the sync `get_service_info` from
        # within an asyncio loop ("RuntimeError: Use
        # AsyncServiceInfo.async_request from the event loop"). Use
        # the async path which fetches SRV / TXT / addresses via the
        # library's own non-blocking primitives.
        info = AsyncServiceInfo(type_, name)
        try:
            ok = await info.async_request(self._zc, 1500)
        except Exception:
            return
        if not ok:
            return
        now = datetime.now(timezone.utc)
        addresses = tuple(info.parsed_addresses())
        txt = _decode_txt(info.properties)
        host = info.server  # e.g. "Living-Room.local."
        port = info.port
        category = service_category(type_)
        existing = self._state.get(key)
        # Build a candidate so vendor resolution sees the latest data.
        candidate = BonjourDevice(
            service_type=type_,
            name=name,
            host=host,
            port=port,
            addresses=addresses,
            txt=txt,
            vendor=None,
            category=category,
            first_seen=existing.first_seen if existing else now,
            last_seen=now,
        )
        vendor = resolve_vendor(candidate)
        self._state[key] = replace(candidate, vendor=vendor)

    def _expire_stale(self, now: datetime) -> None:
        cutoff = now.timestamp() - self._ttl_s
        stale = [
            key for key, d in self._state.items()
            if d.last_seen.timestamp() < cutoff
        ]
        for key in stale:
            self._state.pop(key, None)
