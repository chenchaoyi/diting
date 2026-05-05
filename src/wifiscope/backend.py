"""Pluggable WiFi data-acquisition backend.

v0.1 ships only the macOS CoreWLAN implementation (lands in step 3); this
abstract base class exists so a future Linux backend can drop in without
touching the UI / data-flow layer. No Linux placeholder is included.
"""

from abc import ABC, abstractmethod
from typing import Literal

from .models import Connection, ScanResult

PermissionState = Literal["granted", "denied", "unknown"]


class WiFiBackend(ABC):
    """Contract for any WiFi data source."""

    name: str

    @abstractmethod
    def get_connection(self) -> Connection | None:
        """Return the current WiFi association, or None if unassociated.

        Synchronous and fast (sub-millisecond on macOS via CoreWLAN).
        Safe to call once per second from a UI refresh loop.
        """

    @abstractmethod
    def scan(self) -> list[ScanResult]:
        """Perform an active scan of nearby APs.

        Blocking: a CoreWLAN scan takes roughly 3 seconds. Callers running
        an asyncio event loop must wrap this in `run_in_executor` to avoid
        stalling the loop. The macOS API also throttles scans internally;
        do not invoke this more often than every 3 seconds.
        """

    @abstractmethod
    def permission_state(self) -> PermissionState:
        """Whether the backend can read network identity (SSID/BSSID).

        - "granted": identity fields are populated when associated
        - "denied": associated but identity is being redacted by the OS
          (macOS 14.4+ requires Location Services permission for the
          host process to read SSID and BSSID)
        - "unknown": cannot determine right now (typically when the host
          is unassociated, so there is no identity to compare against)

        UIs use this to surface a one-line hint instead of silently
        showing "n/a" forever.
        """
