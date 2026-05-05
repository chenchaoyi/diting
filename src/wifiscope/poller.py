"""Async WiFi polling layer.

Drives the backend on a fixed cadence and emits a typed event stream
consumers (CLI, TUI) iterate over without caring about asyncio internals.

Cadences:
- connection: 1 Hz (cheap, sub-millisecond CoreWLAN call)
- scan: 0.2 Hz, run in a thread executor since macOS scan blocks ~3s

Roaming detection lives here, not in the UI: a roam is a property of
the data stream, not a rendering concern.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime

from .backend import WiFiBackend
from .models import Connection, ScanResult


@dataclass(frozen=True, slots=True)
class ConnectionUpdate:
    """One snapshot of the local association. None means unassociated."""
    connection: Connection | None


@dataclass(frozen=True, slots=True)
class ScanUpdate:
    """One full pass of nearby APs."""
    results: list[ScanResult]


@dataclass(frozen=True, slots=True)
class RoamEvent:
    """Two consecutive non-None BSSIDs differed.

    Carries the channel for each side so renderers can label band
    switches (same physical AP, different radio) without re-querying
    the inventory.
    """
    timestamp: datetime
    previous_bssid: str
    previous_channel: int | None
    new_bssid: str
    new_channel: int | None


Event = ConnectionUpdate | ScanUpdate | RoamEvent


class WiFiPoller:
    """Background polling driver.

    Single-use: call `events()` once and iterate it. On generator close
    (consumer breaks out, or the surrounding asyncio task is cancelled)
    the internal polling tasks are cancelled and awaited.
    """

    def __init__(
        self,
        backend: WiFiBackend,
        *,
        connection_interval: float = 1.0,
        scan_interval: float = 5.0,
    ) -> None:
        self._backend = backend
        self._connection_interval = connection_interval
        # CoreWLAN throttles scans internally; the spec says do not poll
        # more often than every 3s, so 5s is comfortably above the floor.
        self._scan_interval = max(scan_interval, 3.0)
        self._queue: asyncio.Queue[Event] = asyncio.Queue()
        self._last_bssid: str | None = None
        self._last_channel: int | None = None

    async def events(self) -> AsyncIterator[Event]:
        loop = asyncio.get_running_loop()
        tasks = [
            loop.create_task(self._connection_loop(), name="poller-conn"),
            loop.create_task(self._scan_loop(), name="poller-scan"),
        ]
        try:
            while True:
                yield await self._queue.get()
        finally:
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _connection_loop(self) -> None:
        while True:
            try:
                conn = self._backend.get_connection()
            except Exception:
                conn = None
            await self._queue.put(ConnectionUpdate(conn))
            self._maybe_emit_roam(conn)
            await asyncio.sleep(self._connection_interval)

    async def _scan_loop(self) -> None:
        loop = asyncio.get_running_loop()
        while True:
            try:
                results = await loop.run_in_executor(None, self._backend.scan)
            except Exception:
                results = []
            await self._queue.put(ScanUpdate(results))
            await asyncio.sleep(self._scan_interval)

    def _maybe_emit_roam(self, conn: Connection | None) -> None:
        # A real roam is two consecutive *known* BSSIDs that differ.
        # Cases:
        # - both BSSIDs known and differ -> emit
        # - now disassociated -> reset (so reconnecting to the same AP
        #   doesn't synthesize a phantom roam later)
        # - BSSID is None mid-connection (Location Services denied) ->
        #   leave _last_bssid alone; we genuinely cannot tell whether
        #   the AP changed
        if conn is None:
            self._last_bssid = None
            self._last_channel = None
            return
        if conn.bssid is None:
            return
        if self._last_bssid is not None and self._last_bssid != conn.bssid:
            self._queue.put_nowait(
                RoamEvent(
                    timestamp=conn.timestamp,
                    previous_bssid=self._last_bssid,
                    previous_channel=self._last_channel,
                    new_bssid=conn.bssid,
                    new_channel=conn.channel,
                )
            )
        self._last_bssid = conn.bssid
        self._last_channel = conn.channel
