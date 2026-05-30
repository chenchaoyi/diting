"""Shared error type for protocol parse / validation failures."""

from __future__ import annotations


class ProtocolError(ValueError):
    """A payload does not conform to the companion-protocol contract.

    Raised by the parse / validate helpers. Callers at trust boundaries
    (relay pulls, QR scans) catch this and abstain — they never let a
    malformed payload surface as fabricated event data.
    """
