# Design

A1 of the long-timeline analysis effort. Wires transition events
into BLE, Bonjour, and LAN-inventory pollers so the JSONL log
captures "what was around me when" at a granularity beyond pure
Wi-Fi state. A2 (cross-session `analyze`) reads these.

## D1. Why no debounce, why record everything

User explicitly chose "record every transition" over "only stable
presence". The reasoning:

- Track A2's hour-of-day heatmap is only as good as the events that
  feed it. Dropping ghost MACs at the producer side throws away
  signal that downstream filtering / LLM analysis could recover.
- Volume is a tractable problem with `jq` / `grep` / future
  `--filter`; missing data is not.
- Debounce is easy to add later via env-var; debounce-by-default
  silently loses data.

JSONL volume estimate on representative environments:

| Environment | New events / hour (rough) |
|---|---|
| Home, evening | 5-20 (a phone joins / leaves; HomePod TTL flips) |
| Office floor | 200-800 (BLE adverts churn; LAN client isolation hides most LAN churn) |
| Hotel lobby | 1000-3000 (BLE-heavy; lots of random MACs) |
| Conference | 3000-10,000 (everyone has wearables) |

A 1 KB-per-line average × 10,000 lines = ~10 MB / hour. Comfortable
for a 1-day investigation; manageable for a week; users running
multi-week long-timeline studies in conference venues will need
`gzip` rotation. We'll note this in the README.

## D2. Event-emission timing — where in each poller

### BLE — `src/diting/ble.py::BLEPoller`

BLE events ride alongside the existing snapshot flow. The poller
already maintains a state dict keyed by `identifier`. The emit
points:

```
# Inside the snapshot-build loop (parse_advertisement / sentinel-prune path)
prev = self._state.get(ident)
if prev is None:
    # new device → emit BLEDeviceSeenEvent, then store
    yield BLEDeviceSeenEvent(...)
self._state[ident] = updated

# Inside the TTL eviction sweep (runs every snapshot tick)
for ident, dev in list(self._state.items()):
    if (now - dev.last_seen).total_seconds() > _BLE_TTL_S:
        yield BLEDeviceLeftEvent(...)
        del self._state[ident]
```

The poller's `events()` async generator already yields
`BLEScanUpdate` snapshots; we extend the yielded item type so it
can also be one of the new transition events. The consumer (TUI
loop in `tui.py`) already does `isinstance` dispatch.

### Bonjour — `src/diting/mdns.py::BonjourPoller`

Bonjour has two paths into `_state`:

1. `add_service` callback (new service first seen via zeroconf)
2. `update_service` callback (existing service refreshed)

`SeenEvent` fires only on path 1 (or on path 2 when the previous
state entry doesn't exist — rare but possible during cache
warm-up). `LeftEvent` fires on `remove_service` AND on the TTL
backstop's eviction sweep.

### LAN — `src/diting/lan.py::LANInventoryPoller`

LAN events ride inside `_merge_arp_into_state`:

```
# Existing per-host loop
for ip, mac, _iface in triples:
    mac_lc = mac.lower()
    existing = self._state.get(mac_lc)
    if existing is None and not (mac_lc == iface_mac_lc or ip == router_ip):
        # new host → emit LANHostSeenEvent
        self._pending_events.append(LANHostSeenEvent(...))
    elif existing is not None and existing.ip != ip:
        # DHCP rotation
        self._pending_events.append(LANHostDHCPRotationEvent(
            previous_ip=existing.ip, new_ip=ip, ...,
        ))
    ...

# After the loop, a sweep over _state to detect long-silent hosts
for mac_lc, dev in list(self._state.items()):
    if dev.last_reachable_at is None:
        continue
    age = (now - dev.last_reachable_at).total_seconds()
    if age > _HOST_LEFT_TIMEOUT_S and mac_lc not in seen_macs:
        self._pending_events.append(LANHostLeftEvent(...))
        del self._state[mac_lc]
```

`_pending_events` is consumed by `_do_sweep_and_emit` and yielded
on the same queue as the snapshot.

## D3. JSONL serialization — uniform schema

All seven new events follow the existing convention:

```json
{"type": "ble_device_seen", "ts": "2026-05-20T18:42:01.234+08:00",
 "identifier": "...", "name": "Magic Keyboard",
 "vendor": "Apple, Inc.", "rssi_dbm": -55,
 "service_categories": ["HID"]}
```

`None` fields are omitted (matches what `event_to_jsonl` does for
the existing events). Tuples serialize as JSON arrays.

## D4. EventRing capacity

The existing ring is capped at 500 entries by default. With seven
new event types firing on busy networks, the ring will roll faster.
Mitigation: leave the cap as-is for v1; reading the JSONL log is
the supported way to inspect history beyond the in-memory ring.
The EventsScreen modal renders the ring; users wanting full
history reach for `diting analyze` against the JSONL.

## D5. EventsScreen filter cycle — eight buckets

The current filter cycle has five buckets: `all`, `roam`, `rf_stir`,
`latency` (folds latency_spike + loss_burst), `link_state`. Keys
`0`–`4` correspond.

We extend to eight: add `ble`, `bonjour`, `lan` at the end. Keys
`5`–`7` cover them. The hidden bindings table updates accordingly.

Rendering format per event type:

```
[ROAM]      previous bssid → new bssid · SSID: <name>
[STIR]      bssid · σ <db> dB · <confidence> · SSID: <name>
[LATENCY]   <target> <rtt> ms · <loss>%
[LOSS]      <target> <loss>% · <n> lost
[LINK]      <state>
[BLE]       device joined: <vendor> · <name>     ← new
[BLE]       device left: <vendor> · <name> · <duration>     ← new
[BJ]        service joined: <category> · <host>     ← new
[BJ]        service left: <category> · <host> · <duration>     ← new
[LAN]       host joined: <vendor> · <name|ip>     ← new
[LAN]       host left: <vendor> · <name|ip> · <duration>     ← new
[LAN]       <vendor> · <name|ip> moved <prev_ip> → <new_ip>     ← new (DHCP)
```

`[BJ]` (Bonjour) is the new prefix; `[BLE]` and `[LAN]` reuse the
panel-naming convention.

## D6. Test surface

`tests/test_events.py` additions:

- `test_ble_seen_event_round_trips_to_jsonl`
- `test_ble_left_event_round_trips_to_jsonl`
- `test_bonjour_seen_event_round_trips_to_jsonl`
- `test_bonjour_left_event_round_trips_to_jsonl`
- `test_lan_seen_event_round_trips_to_jsonl`
- `test_lan_left_event_round_trips_to_jsonl`
- `test_lan_dhcp_rotation_event_round_trips_to_jsonl`
- `test_new_event_fields_omit_none_in_jsonl`

`tests/test_ble.py` additions:

- `test_ble_poller_emits_seen_event_on_first_observation`
- `test_ble_poller_emits_left_event_on_ttl_expiry`
- `test_ble_poller_does_not_re_emit_seen_for_known_device`

`tests/test_mdns.py` additions:

- `test_bonjour_poller_emits_seen_event_on_add_service`
- `test_bonjour_poller_emits_left_event_on_remove_service`
- `test_bonjour_poller_emits_left_event_on_ttl_eviction`

`tests/test_lan.py` additions:

- `test_lan_poller_emits_seen_event_on_first_observation`
- `test_lan_poller_skips_seen_event_for_self_and_gateway`
- `test_lan_poller_emits_dhcp_rotation_event_on_ip_change`
- `test_lan_poller_emits_left_event_after_timeout`

`tests/test_tui_helpers.py` additions:

- `test_events_panel_renders_ble_device_seen_line`
- `test_events_panel_renders_bonjour_service_left_line`
- `test_events_panel_renders_lan_dhcp_rotation_line`
- `test_events_screen_filter_cycle_includes_ble_bonjour_lan`

`scripts/tui_snapshot.py` additions:

- Extend `_open_events_modal` synthetic seed to inject one of each
  new event type so the modal regression captures the rendering.

## D7. Surface impact

- `src/diting/events.py` — 7 new dataclasses, +~80 LoC
- `src/diting/event_log.py` — 7 new `emit_*` methods + the JSONL
  schema branches in `event_to_jsonl`, +~120 LoC
- `src/diting/ble.py` — `BLEPoller` yields transition events;
  +~40 LoC inside the existing snapshot loop
- `src/diting/mdns.py` — `BonjourPoller` yields transition events;
  +~50 LoC inside the existing add/remove/ttl paths
- `src/diting/lan.py` — `LANInventoryPoller` collects transition
  events into a pending list; new `_HOST_LEFT_TIMEOUT_S` constant;
  +~80 LoC in the merge path
- `src/diting/tui.py` — `_consume_*_events` async loops dispatch
  the new event types into EventsPanel + EventLogger + EventRing;
  EventsScreen filter cycle extends to eight buckets; EventsPanel
  formats the new types. ~100 LoC across.
- `src/diting/i18n.py` — labels for the new EventsPanel rendering
- Tests across `tests/test_events.py`, `test_ble.py`, `test_mdns.py`,
  `test_lan.py`, `test_tui_helpers.py` (~400 LoC total)

No new third-party dependency.
