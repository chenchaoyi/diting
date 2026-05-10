# Tasks — document ble-detail-modal

## 1. Spec backfill — no implementation
- [x] 1.1 Spec extracted from `BLEDetailScreen` class + `action_ble_select_prev/next/inspect` + `_ble_set_selected` + `_ble_ordered_ids` + `BLEPanel.on_click` in `src/wifiscope/tui.py`.
- [x] 1.2 Cross-checked against the `ble_detail_decoded` regression scenario and the `live_ble_detail` explore-mode capture.

## 2. Optional polish (not blocking archive)
- [x] 2.1 Help modal mentions `↑`/`↓`/`enter`/`i` BLE keybindings (currently only listed indirectly via Bindings group).
- [x] 2.2 Basics modal explains the (anonymous) vs (unknown) distinction in plain language.
