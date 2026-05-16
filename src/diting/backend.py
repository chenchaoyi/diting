"""Pluggable WiFi data-acquisition backend.

v0.1 ships only the macOS CoreWLAN implementation (lands in step 3); this
abstract base class exists so a future Linux backend can drop in without
touching the UI / data-flow layer. No Linux placeholder is included.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal

from .models import Connection, ScanResult

PermissionState = Literal["granted", "fallback", "denied", "unknown"]

AssociateErrorCode = Literal[
    "cancelled",
    "auth_failed",
    "enterprise_unsupported",
    "ssid_not_found",
    "unknown",
]


@dataclass(frozen=True)
class AssociateResult:
    """Outcome of a `j`-initiated cross-SSID join attempt.

    Independent of any specific backend so the TUI consumer (and the
    helper-subprocess parser) speak the same shape. The action itself
    is not abstract on `WiFiBackend` — backends that cannot join
    expose `associate` via `getattr` lookup, the same pattern
    `force_reroam` uses. ``error_code`` is None iff ``ok`` is True.
    """

    ok: bool
    bssid: str | None = None
    keychain_saved: bool = False
    error_code: AssociateErrorCode | None = None
    error_message: str | None = None


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

        - "granted": CoreWLAN itself returns SSID and BSSID
        - "fallback": CoreWLAN is redacted, but a permission-free side
          channel (SCDynamicStore) is providing real values
        - "denied": both the official and fallback paths fail; identity
          fields will be None even mid-connection
        - "unknown": cannot determine (typically when unassociated)

        UIs use this to surface a one-line hint instead of silently
        showing "n/a" forever.
        """
