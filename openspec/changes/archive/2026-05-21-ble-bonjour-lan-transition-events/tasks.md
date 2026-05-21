## 1. Test plan (test-first)

- [x] 1.1 `tests/TESTING.md` (EN) — under `### events`, add rows for the seven new event types (dataclass shape + JSONL round-trip). Under `### event-log`, add rows for the seven new emit methods + the None-field-omitted convention + empty-tuple-as-`[]` convention. Under `### bluetooth-scanning`, add rows for `BLEPoller` emitting seen/left at the right transitions. Under `### mdns-scanning`, mirror for Bonjour. Under `### lan-inventory`, add rows for the three LAN transitions (seen, left, dhcp_rotation) plus the self/gateway exclusion. Under `### tui-shell`, add rows for the eight-bucket filter cycle + the seven new EventsPanel render formats.
- [x] 1.2 `docs/zh/TESTING.md` — mirror.

## 2. New event dataclasses (`events`)

- [x] 2.1 `src/diting/events.py` — add seven frozen-dataclass classes per the proposal: `BLEDeviceSeenEvent`, `BLEDeviceLeftEvent`, `BonjourServiceSeenEvent`, `BonjourServiceLeftEvent`, `LANHostSeenEvent`, `LANHostLeftEvent`, `LANHostDHCPRotationEvent`. Each is `@dataclass(frozen=True, slots=True)` with `timestamp: datetime` plus event-specific fields.

## 3. JSONL writer + EventLogger (`event-log`)

- [x] 3.1 `src/diting/event_log.py::event_to_jsonl` — add seven new branches, each producing the locale-stable `type` value and snake_case English keys; None-valued fields omitted; tuple-valued fields emit as JSON arrays even when empty.
- [x] 3.2 `src/diting/event_log.py::EventLogger` — add seven new `emit_*` methods. Each calls `event_to_jsonl` + flushes; the no-op logger contract is preserved.

## 4. Poller emission paths

- [x] 4.1 `src/diting/ble.py::BLEPoller` — yield `BLEDeviceSeenEvent` on first observation of an identifier; yield `BLEDeviceLeftEvent` on TTL eviction. Update the `events()` return-type union to include the two new event classes.
- [x] 4.2 `src/diting/mdns.py::BonjourPoller` — enqueue `BonjourServiceSeenEvent` on `add_service` (and the rare `update_service` → cache-warmup path); enqueue `BonjourServiceLeftEvent` on `remove_service` AND on TTL backstop eviction. Snapshot-loop yields both kinds.
- [x] 4.3 `src/diting/lan.py::LANInventoryPoller` — collect transition events into a per-tick pending list. Three triggers: new MAC entering state (not self / not gateway) → `LANHostSeenEvent`; existing MAC at new IP → `LANHostDHCPRotationEvent` BEFORE the ip-field update; `last_reachable_at` older than `_HOST_LEFT_TIMEOUT_S` (default 300 s) AND MAC absent from latest triples → `LANHostLeftEvent`. Yield via the existing queue.

## 5. TUI integration (`tui-shell`)

- [x] 5.1 `src/diting/tui.py::DitingApp` — `_consume_ble_events`, `_consume_mdns_events`, `_consume_lan_inventory_events` dispatch the seven new event types to: (a) EventsPanel.append_event, (b) `_events_ring.push`, (c) the appropriate `_event_logger.emit_*` method.
- [x] 5.2 `src/diting/tui.py::EventsPanel.append_event` — add seven new formatting branches per the spec delta's render-format table. Use `fit_cells` for long-name truncation. i18n through `t()` for the human-facing labels.
- [x] 5.3 `src/diting/tui.py::EventsScreen` — extend the filter cycle to eight buckets (`all`, `roam`, `rf_stir`, `latency`, `link_state`, `ble`, `bonjour`, `lan`). Bind keys `5`, `6`, `7` to the new buckets via `show=False`. Update the filter-indicator rendering.

## 6. i18n

- [x] 6.1 `src/diting/i18n.py` — EN + ZH entries for:
  - `"device joined: "` → `"设备出现："`
  - `"device left: "` → `"设备消失："`
  - `"service joined: "` → `"服务出现："`
  - `"service left: "` → `"服务消失："`
  - `"host joined: "` → `"主机出现："`
  - `"host left: "` → `"主机消失："`
  - `" moved "` → `" 换地址 "`
  - Filter-bucket labels: `"ble"` → `"BLE"`, `"bonjour"` → `"Bonjour"`, `"lan"` → `"LAN"` (acronyms; ZH unchanged)

## 7. Tests

- [x] 7.1 `tests/test_events.py` — round-trip tests for all seven new event types through `event_to_jsonl`; assert None-field omission + empty-tuple-as-`[]` semantics.
- [x] 7.2 `tests/test_ble.py` — assert seen-on-first-observation, no-re-emit on subsequent observations, left-on-TTL-eviction.
- [x] 7.3 `tests/test_mdns.py` — assert seen on `add_service` callback, left on `remove_service`, left on TTL backstop, no re-seen on cache-refresh active-probe path.
- [x] 7.4 `tests/test_lan.py` — assert seen on new-non-self / non-gateway MAC, NO seen for self+gateway, DHCP rotation event before ip-field update, left on `_HOST_LEFT_TIMEOUT_S` timeout.
- [x] 7.5 `tests/test_tui_helpers.py` — assert each of the seven render formats in EventsPanel; assert filter cycle has eight buckets in the right order.

## 8. Snapshot regression scenario

- [x] 8.1 `scripts/tui_snapshot.py::_open_events_modal` — seed the synthetic event ring with one of each new event type so the modal regression captures the rendering.

## 9. CI gates

- [x] 9.1 `uv run pytest`
- [x] 9.2 `uv run python scripts/tui_snapshot.py --mode regression`
- [x] 9.3 `openspec validate --specs --strict`
- [x] 9.4 `openspec validate ble-bonjour-lan-transition-events --strict`
