## Why

The BLE panel has a "select a row → press `i`/`Enter` → inspect every
field in a modal" pattern that the Wi-Fi and Bonjour panels do not.
Three consequences:

1. **Inconsistent gesture across views.** `n` cycles three panels that
   look like the same kind of list, but only one is interactive.
   Users learn the BLE gesture, switch to Wi-Fi, press `i`, nothing
   happens — they think the binding is broken or context-dependent in
   ways they can't predict.
2. **Information starved rows.** The Wi-Fi list shows ~7 columns; the
   actual scan record carries ~14 fields (beacon-IE flags, BSS load,
   roam-capability bits, country code, etc.) that have no surface.
   The Bonjour list shows 5 columns; the actual record carries
   addresses + TXT records (the whole point of mDNS) that have no
   surface either.
3. **No place to grow.** As we add more vendor-specific decoding to
   Bonjour (HomeKit accessories, Hue bridges) or per-BSSID history /
   anomaly annotations to Wi-Fi, the list view can't absorb that
   detail — but a modal can.

Bringing the same gesture to all three panels is the smallest unit of
work that unblocks all three.

## What Changes

- **Wi-Fi panel**: row selection (keyed by BSSID, falling back to a
  `(ssid, channel)` synthetic key when BSSID is redacted by TCC) +
  `i`/`Enter` opens a new `WifiDetailScreen` modal. Mouse click on a
  scan-list row selects-and-inspects in one gesture, mirroring BLE.
- **Bonjour panel**: row selection (keyed by service-instance
  fully-qualified name `f"{name}.{service_type}"`) + `i`/`Enter` opens
  a new `BonjourDetailScreen` modal. Mouse click on a row
  selects-and-inspects in one gesture.
- **Modals render every field the dataclass carries**:
  - `WifiDetailScreen` shows Identity (SSID / BSSID / AP-name from
    `aps.yaml` / OUI vendor), Radio (channel + band + width + PHY +
    security + MCS + NSS), Signal (RSSI + noise + SNR), Beacon IE
    diagnostics (BSS load %, station count, 802.11 r/k/v support),
    and Activity (first seen / last seen).
  - `BonjourDetailScreen` shows Identity (instance + service type +
    category + vendor), Network (host + port + every IPv4/IPv6
    address), TXT records (full key/value table), Activity.
- **`up`/`down` keys move selection within the active view**,
  priority=True so they win over `VerticalScroll`'s built-in scroll;
  no-ops outside the relevant view. Same contract as BLE.
- **Modal close** is `Esc` / `i` / `q`, identical to BLE. Closing does
  NOT clear selection — reopening shows the same row.
- **Live navigation inside the modal**: while a detail modal is open,
  `up` / `down` advance the underlying panel's selection AND re-render
  the modal body so it tracks the new row. Works on all three modals
  (Wi-Fi, BLE, Bonjour). Implemented via a single App-level dispatcher
  that calls a `sync_to_app_selection()` hook on whichever modal is on
  the screen stack — modal-level bindings would conflict with the
  App-level `priority=True` arrow bindings.
- **Selection survives sort + churn**: the highlighted row tracks its
  identifier, not its index. If the selected target leaves the
  snapshot, selection clears (no ghost cursor on a row that doesn't
  exist).
- **No new data sources, no new helper schema bump.** Both modals
  render fields that the existing `ScanResult` / `BonjourDevice`
  dataclasses already carry. Per-BSSID RSSI history is **out of
  scope** — punt to a follow-up change if useful (would need a
  `WiFiHistory` ring buffer parallel to `BLEHistory`).

## Capabilities

### New Capabilities

- `wifi-detail-modal`: per-AP inspect modal in the Wi-Fi view —
  selection state, key + mouse bindings, modal layout, field-by-field
  rendering rules.
- `bonjour-detail-modal`: per-service-instance inspect modal in the
  Bonjour view — selection state, key + mouse bindings, modal layout,
  field-by-field rendering rules (incl. TXT records and the full
  address list).

### Modified Capabilities

- `tui-shell`: lift the "row-select + inspect" gesture from a
  BLE-only contract to a cross-view contract (`up`/`down` move
  selection; `i`/`Enter` opens the active panel's detail modal;
  mouse click is a select-and-inspect shortcut). Each panel's modal
  is defined by its own capability spec; `tui-shell` just guarantees
  the binding behaviour is uniform.
- `ble-detail-modal`: add the live-navigation requirement so the
  existing BLE modal also tracks selection on `up`/`down` instead
  of being a frozen snapshot of the row it was opened on. Same UX
  as the new Wi-Fi / Bonjour modals.

## Impact

- **Code**:
  - `src/diting/tui.py` — new `WifiDetailScreen` + `BonjourDetailScreen`
    `ModalScreen` classes; new `_wifi_selected_key` /
    `_bonjour_selected_key` state on `App`; new `action_wifi_*` /
    `action_bonjour_*` action methods; mouse `on_click` on `ScanPanel`
    and `BonjourPanel`; `_y_to_key` line-to-identifier maps on both
    panels (mirrors `BLEPanel._y_to_id`).
  - `src/diting/i18n.py` — new strings for modal section titles,
    field labels, footer hint.
- **Tests**:
  - `tests/test_tui_smoke.py` — three new cases: open Wi-Fi modal on
    a row, open Bonjour modal on a row, verify selection stable
    across re-sort.
  - `tests/TESTING.md` (+ ZH mirror) — new rows for both modals.
  - `scripts/tui_snapshot.py` — new synthetic scenario:
    `wifi_detail_modal` + `bonjour_detail_modal` mode.
- **Docs**:
  - `README.md` + `docs/zh/README.md` — "press `i` to inspect any
    row" is no longer BLE-only; update the BLE section to a generic
    "row inspect" note.
  - Help modal copy — `i` description generalised across all three
    panels.
- **No new dependencies.** No helper schema bump. No CHANGELOG
  bullets (release-only policy).
