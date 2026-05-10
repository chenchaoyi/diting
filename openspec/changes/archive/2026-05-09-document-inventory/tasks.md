# Tasks — document inventory

## 1. Spec backfill — no implementation
- [x] 1.1 Spec extracted from `src/wifiscope/network.py` (`NetworkInventory`, `APEntry`, `_prefix5` / `_mid4`, `cluster_label`, `format_bssid`, `load_inventory`, `load_wifi_ouis`, `lookup_ap_vendor`).
- [x] 1.2 Cross-checked against `tests/test_network.py` and the resolution paths exercised in `tests/test_tui_helpers.py`.

## 2. Optional polish (not blocking archive)
- [x] 2.1 README "AP naming (aps.yaml)" section gains a one-liner pointing to `openspec/specs/inventory/spec.md`.
- [x] 2.2 `aps.example.yaml` header comment cross-links to the canonical spec.
