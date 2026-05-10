# Contributing a BLE decoder

Adding a new per-protocol decoder is a small, mechanical task. The
framework's contract is in
[`openspec/specs/ble-decoders/spec.md`](../../../openspec/specs/ble-decoders/spec.md);
**read it first**.

## Shape

```python
# src/diting/decoders/<protocol>.py
from __future__ import annotations
from typing import Any
from ..ble import BLEDevice
from . import register

@register
def decode(d: BLEDevice) -> dict[str, Any] | None:
    """One-paragraph summary of the protocol + spec link."""
    # Gate first
    if d.vendor_id != _MY_CID:
        return None
    if not d.manufacturer_hex:
        return None
    # Parse defensively
    try:
        blob = bytes.fromhex(d.manufacturer_hex)
    except ValueError:
        return None
    if len(blob) < <minimum>:
        return None
    # Emit protocol-namespaced keys
    return {
        "<protocol>.field_a": ...,
        "<protocol>.field_b": ...,
    }
```

## Hard rules (from the spec)

1. **Never raise** on malformed input — abstain by returning
   `None` or `{}`. The framework catches exceptions defensively
   but exception-as-flow is a bug, not a feature.
2. **Output keys MUST be protocol-namespaced** with a dot prefix
   (`ibeacon.uuid`, `eddystone.url`, ...). The detail modal groups
   output by prefix when rendering.
3. **Gate on identifying bytes** (vendor cid, service UUID,
   frame-type byte) before processing. Don't shotgun-decode every
   device.
4. **Don't claim semantics for unstable bits.** If public docs
   disagree on what a flag bit means, surface the byte hex
   verbatim with mechanical labels (`status_hex`, `flags`, etc.)
   instead of risking version-fragile interpretations.

## Register the new decoder

Add an import line to `src/diting/decoders/__init__.py`:

```python
from . import <protocol> as _<protocol>  # noqa: E402, F401
```

The `@register` decorator runs at import time and adds the function
to the global registry. `decode_all(d)` picks it up automatically.

## Tests

Add canonical happy-path + at least two negative tests to
`tests/test_decoders.py`. Use real captured byte sequences when
possible — the existing tests for iBeacon / Eddystone / Apple
Continuity / MS CDP / RuuviTag all use bytes pulled from real helper
output, not synthetic fixtures.

```python
def test_<protocol>_canonical_decode():
    raw = "..."  # real bytes from a real packet
    d = _dev(vendor_id=<cid>, manufacturer_hex=raw)
    out = decode_all(d)
    assert out["<protocol>.field_a"] == ...

def test_<protocol>_skips_when_cid_does_not_match():
    d = _dev(vendor_id=<other>, manufacturer_hex="...")
    assert "<protocol>.field_a" not in decode_all(out)

def test_<protocol>_skips_truncated_frame():
    d = _dev(vendor_id=<cid>, manufacturer_hex="<too short>")
    assert "<protocol>.field_a" not in decode_all(d)
```

## Spec delta

Adding a decoder is technically permitted by the existing
`ble-decoders` spec without a MODIFIED Requirement (the
"Bundled decoders" requirement enumerates the **minimum** set, not
a maximum). But if your decoder ships in the bundled five (e.g. it's
a public-spec protocol the existing five users would expect to
work), file a tiny change at `openspec/changes/add-<protocol>-decoder/`
that ADDs your protocol to the canonical spec's "bundled" list.

## Optional dependencies

Vendor-specific HA-ecosystem decoder packages (`xiaomi-ble`,
`govee-ble`, `switchbot-ble`, etc.) belong as optional `[extra]`
dependencies in `pyproject.toml`, not as runtime requirements. The
spike at `scripts/ble_decoder_survey.py` shows real-world coverage
gain is small (~1–2 rows in 200) — don't ship a hard dep for it.
