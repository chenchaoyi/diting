# Tasks — document bluetooth-scanning

## 1. Spec backfill — no implementation
- [x] 1.1 Spec extracted from `src/wifiscope/ble.py` (`_build_device`, `_build_connected_device`, `lookup_*` chain, `merge_for_display`, `is_silent_device`, `BLEHistory`).
- [x] 1.2 Cross-checked against the live regression scenario `ble_normal` and the `live_ble` explore-mode capture.

## 2. Optional polish (not blocking archive)
- [x] 2.1 README "BLE devices" section gains a one-liner pointing to `openspec/specs/bluetooth-scanning/spec.md`.
- [x] 2.2 The `(anonymous)` vs `(unknown)` distinction gets a short paragraph in the basics modal.
