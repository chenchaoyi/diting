"""companion-protocol — the canonical wire contract.

diting owns this contract; diting-mobile vendors the JSON Schema +
golden fixtures under its own ``protocol/`` directory and conforms to
them. Everything here is pure structure — no crypto, no I/O — so it can
be imported in any context and so the fixtures stay reproducible.

Layout::

    protocol/
    ├── version.py     PROTOCOL_VERSION + supported-version check
    ├── envelope.py    relay envelope build / parse / validate (ciphertext opaque)
    ├── pairing.py     pairing-payload (QR contents) encode / decode
    ├── apns.py        content-free APNs trigger + coarse-category taxonomy
    ├── schema/        JSON Schema (draft 2020-12) — the vendored contract
    │   ├── event.schema.json
    │   ├── envelope.schema.json
    │   ├── pairing.schema.json
    │   └── apns-trigger.schema.json
    └── fixtures/
        ├── events.jsonl   golden lines, one per wire type
        └── manifest.json  protocol version + per-artifact sha256 (drift check)

The event payload sealed inside an envelope is exactly one diting event
object as produced by ``diting.event_log.EventLogger`` — English keys,
local-TZ ISO-8601 with offset, ``None`` fields omitted, empty tuples as
``[]``. This package does NOT define an alternate event vocabulary; the
``event.schema.json`` describes that existing wire shape.
"""

from __future__ import annotations

from .version import PROTOCOL_VERSION, is_supported_version

__all__ = ["PROTOCOL_VERSION", "is_supported_version"]
