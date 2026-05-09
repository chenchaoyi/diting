"""Per-protocol payload decoders for ``BLEDevice``.

The helper plumbs raw advertisement bytes (manufacturer-data,
service-data, tx-power, solicited / overflow service UUIDs) through
to the Python side via schema-4. This package is where those bytes
get turned into protocol-specific structured fields the detail
modal — and the future per-protocol UI views — can render.

Each decoder is a small function:

    def decode(d: BLEDevice) -> dict[str, Any] | None:
        ...

Returning a non-empty dict signals "this protocol matched, here are
the fields"; ``None`` (or empty dict) means abstain. Decoders are
expected to be cheap, hermetic, and total — never raise on malformed
input. ``decode_all`` is defensive and swallows exceptions on a
per-decoder basis so one buggy plug-in cannot blank the panel.

The output dict is conventionally keyed with a protocol-namespaced
prefix so multiple decoders can coexist without collisions:

    {"ibeacon.uuid": "550e8400-...", "ibeacon.major": 1, ...}
    {"eddystone.frame": "URL", "eddystone.url": "https://...", ...}

Built-in decoders (iBeacon, Eddystone, Apple Continuity expansions
later) auto-register on import. Callers see a uniform surface:

    from wifiscope.decoders import decode_all
    fields = decode_all(device)  # dict, possibly empty
"""
from __future__ import annotations

from typing import Any, Callable

from ..ble import BLEDevice

Decoder = Callable[[BLEDevice], "dict[str, Any] | None"]

_DECODERS: list[Decoder] = []


def register(fn: Decoder) -> Decoder:
    """Add a decoder to the global registry. Use as a decorator."""
    _DECODERS.append(fn)
    return fn


def decoders() -> tuple[Decoder, ...]:
    """Snapshot of the current registry, mainly for tests."""
    return tuple(_DECODERS)


def decode_all(d: BLEDevice) -> dict[str, Any]:
    """Run every registered decoder against ``d``, merge their outputs.

    A decoder raising is a bug, not a user-visible failure: the panel
    silently drops that decoder's contribution and keeps going. The
    detail modal already renders the raw bytes regardless, so the
    user is never left with nothing.
    """
    out: dict[str, Any] = {}
    for fn in _DECODERS:
        try:
            r = fn(d)
        except Exception:
            continue
        if r:
            out.update(r)
    return out


# Auto-register built-in decoders at package import time. Order
# matters only for collision resolution; we currently have none, but
# keeping iBeacon (manufacturer-data path) before Eddystone
# (service-data path) follows the bytes-to-decoder dispatch the
# detail modal already prefers.
from . import ibeacon as _ibeacon  # noqa: E402, F401
from . import eddystone as _eddystone  # noqa: E402, F401
from . import apple_continuity as _apple_continuity  # noqa: E402, F401
from . import microsoft_cdp as _microsoft_cdp  # noqa: E402, F401
from . import ruuvi as _ruuvi  # noqa: E402, F401
