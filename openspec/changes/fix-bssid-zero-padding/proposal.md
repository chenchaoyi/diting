# fix-bssid-zero-padding

## Why

A live session (2026-06-07) showed the same physical radio twice under
one AP group — two `tedo_5G` rows with BSSIDs `40:fe:95:8a:3c:0b` and
`40:fe:95:8a:3c:b`. macOS formats MAC octets without zero-padding in
some surfaces (the SCDynamicStore `CachedScanRecord` BSSID — the macOS
26 TCC fallback for the *current* connection), while scan paths return
zero-padded octets. diting only lowercases, so the two spellings are
treated as different BSSIDs: the synthetic "current" row fails to merge
with its scan row (duplicate row + inflated group counts), and the
un-padded form leaks into roam detection (phantom roam on the
`3c:b` ↔ `3c:0b` flip), the familiarity store (one AP becomes two
entities), and `aps.yaml` matching. The same macOS quirk was already
fixed independently in the ARP parser (`lan.py`) and the MiBeacon MAC
decoder (`ble.py`); the Wi-Fi BSSID path is the remaining gap.

## What Changes

- New shared `normalize_bssid()` (lowercase + per-octet zero-pad,
  fail-soft on non-MAC strings) in `models.py`.
- Applied at every Wi-Fi BSSID producer boundary: the SCDynamicStore
  fallback (`_dynamic_store`), CoreWLAN connection + scan
  (`macos_backend`), and the helper JSON parse (`_helper`).
- `_merge_current` compares normalized forms (defense in depth for
  injected/test backends).

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `wifi-scanning`: the scan-row field requirement is strengthened —
  every BSSID the backend emits (scan rows AND the `Connection`
  snapshot, whichever source produced it) SHALL be normalized to
  lowercase zero-padded colon-separated form, so one radio is one
  identity across all consumers.

## Impact

- `src/diting/models.py` — `normalize_bssid()`.
- `src/diting/_dynamic_store.py`, `src/diting/macos_backend.py`,
  `src/diting/_helper.py` — apply at the boundary.
- `src/diting/tui.py` — `_merge_current` normalizes before comparing.
- `tests/test_models.py` (or nearest unit home) + `tests/
  test_tui_helpers.py` — normalization cases + the un-padded
  current-row merge regression; `tests/TESTING.md` + `docs/zh/
  TESTING.md` first.
- Downstream identities (roam events, familiarity `ap:` keys,
  inventory matching) become consistent automatically; no wire-format
  change (JSONL consumers always saw mostly-padded values; the field
  type is unchanged).
