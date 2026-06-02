# Generic manufacturer-data recogniser for long-tail vendors

## Why

A tui-audit (2026-06-01) flagged ~10 BLE rows with a resolved vendor but no
name / type / device_class and, crucially, **zero decoded fields** — the
"decoded protocols" section was empty for any vendor without a dedicated
decoder (Polar, Garmin, Honor, and chip/module makers like Telink and Silicon
Labs/Bluegiga). We can see exactly what these devices broadcast; they just
weren't surfaced in a structured way.

## What Changes

- Add a `manufacturer` decoder: for any device whose company-id has no
  dedicated decoder, emit `mfg.cid`, `mfg.vendor` (when resolved),
  `mfg.body_hex`, `mfg.body_len`. It skips the company-ids already owned by a
  dedicated decoder (Apple / Microsoft / Xiaomi-Huami / Ruuvi) to avoid
  redundant output, abstains on missing/short/invalid manufacturer data, and
  never raises.
- It deliberately does NOT assign a `device_type` / `device_class` from the
  company-id: a chip-vendor id says nothing about the product, so that would
  be a fabricated claim (consistent with the existing no-semantic-claims rule).

## Impact

- Affected specs: `ble-decoders` (a new generic-recogniser requirement).
- Affected code: `src/diting/decoders/manufacturer.py` (new), registered in
  `decoders/__init__.py`. The detail modal renders it via the existing
  `protocol.`-prefix grouping — no UI change.
- No wire/protocol change; desktop-only (manufacturer_hex is not on the
  companion wire event).
