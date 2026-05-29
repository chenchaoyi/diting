## MODIFIED Requirements

### Requirement: `BLEPoller` SHALL emit transition events when devices enter and leave its tracked state
`BLEPoller` SHALL emit `BLEDeviceSeenEvent` when a device's `identifier` graduates from PENDING to PRESENT in its tracked state map. Graduation happens via one of two paths:

- **Bypass path** — the identifier's first observation carries a non-null `name` OR the identifier comes from the `_connected` snapshot. Graduates to PRESENT on the same tick, `BLEDeviceSeenEvent` fires with the original `first_seen` timestamp.
- **Gated path** — the identifier's first observation is anonymous (no helper-given `name`, only `vendor` + RSSI). The identifier enters PENDING with a stored `first_seen` timestamp. On each subsequent tick, the poller checks whether `(now - first_seen) >= presence_gate_s`. When that elapses AND the identifier is still in `_devices`, the identifier graduates to PRESENT and `BLEDeviceSeenEvent` fires with `timestamp = first_seen` (NOT the wall-clock graduation time).

`presence_gate_s` is configurable via `BLEPoller(presence_gate_s=...)`. The default `presence_gate_s` for any given session SHALL be sourced from the active scene: `scene_defaults(get_scene())["ble_presence_gate_s"]`. With the four canonical scenes that resolves to `home=5.0`, `office=15.0`, `public=30.0`, `audit=0.0`. The `home` value (5.0) matches the pre-scene v1.5.0 default — upgrading users who do not pass `--scene` see no behaviour change.

`--ble-presence-gate D` on the CLI SHALL override the scene-derived default — the explicit flag is narrower-scoped and always wins. A value of `0.0` (whether from `--scene audit` or from `--ble-presence-gate 0`) restores the pre-gate "every first-seen identifier fires seen on its first observation" behaviour, including for anonymous adverts; in that case PENDING is bypassed entirely.

Every emitted `BLEDeviceSeenEvent` and `BLEDeviceLeftEvent` SHALL carry `device_type` and `device_class` copied from the cluster representative's `BLEDevice.type` / `BLEDevice.device_class` (the same `BLEDevice` whose `name` / `vendor` already populate the event). When the merger is disabled and events fall back to per-identifier semantics, the values come from that identifier's own `BLEDevice`.

`BLEPoller` SHALL record a session start time at construction and SHALL set `BLEDeviceSeenEvent.at_launch = True` on every advertising-device seen emitted while `(now - started_at) < _LAUNCH_WARMUP_S` (a module-level constant, default 12.0 s); after the window closes `at_launch` SHALL be `False` for all subsequent seens for the rest of the session. Seens sourced from the `_connected` peripheral snapshot SHALL always carry `at_launch = False` regardless of timing — a bonded peripheral present at start is high-signal, never census. `at_launch` SHALL NOT affect graduation, gating, the cluster merger, or `BLEDeviceLeftEvent`; it is purely an annotation for the render layer.

`BLEPoller` SHALL emit `BLEDeviceLeftEvent` when a PRESENT device's `last_seen` falls more than the existing TTL behind the latest snapshot AND the device is then removed from state.

If a PENDING identifier is evicted from `_devices` (TTL elapses) before its presence-gate matures, the poller SHALL emit NO transition events for it — no seen, no left. The identifier returns to INIT silently; a future re-appearance from the same identifier opens a fresh PENDING window.

Subsequent observations of the same identifier in the same session SHALL NOT re-fire `BLEDeviceSeenEvent`.

After a `BLEDeviceLeftEvent` has fired for a given identifier within a session, the poller SHALL emit no further transition events for that identifier in the same session — neither another `BLEDeviceLeftEvent` if the identifier flaps back into `_devices` and is evicted again, nor a fresh `BLEDeviceSeenEvent` if a new advertisement re-introduces it. The identifier is terminal-departed for the rest of the session.

The `BLEPoller.events()` async iterator's union return type SHALL include `BLEDeviceSeenEvent` and `BLEDeviceLeftEvent` alongside the existing `BLEScanUpdate`.

#### Scenario: Named first advert bypasses the presence gate
- **WHEN** an advertisement parses into a BLEDevice with `name = "Magic Keyboard"`, `vendor = "Apple, Inc."`, `identifier` not in `_state`
- **THEN** `BLEDeviceSeenEvent` is yielded on the same `_detect_transitions` tick; the identifier moves directly to PRESENT without entering PENDING

#### Scenario: Seen carries the device's decoded type and class
- **WHEN** a graduating advertisement's `BLEDevice` has `type="Find My target"`, `device_class="iPhone"`
- **THEN** the emitted `BLEDeviceSeenEvent` carries `device_type="Find My target"` and `device_class="iPhone"`

#### Scenario: Seen inside the warmup window is tagged at_launch
- **WHEN** the poller is constructed at t=0 and an advertising device graduates at t=4.0 (with `_LAUNCH_WARMUP_S = 12.0`)
- **THEN** the emitted `BLEDeviceSeenEvent` carries `at_launch=True`

#### Scenario: Seen after the warmup window is not at_launch
- **WHEN** the poller is constructed at t=0 and an advertising device first appears and graduates at t=30.0
- **THEN** the emitted `BLEDeviceSeenEvent` carries `at_launch=False`

#### Scenario: Connected peripheral present at launch is not at_launch
- **WHEN** a connected peripheral is in the `_connected` snapshot at t=2.0 (inside the warmup window)
- **THEN** its `BLEDeviceSeenEvent` carries `at_launch=False` — connected peripherals are never folded into the census

#### Scenario: Anonymous first advert below the gate is silent
- **WHEN** an anonymous advertisement (no `name`, only `vendor`) populates `_devices[ident]` at t=0 with default `presence_gate_s = 5.0`, AND the identifier ages out via TTL at t=4
- **THEN** no `BLEDeviceSeenEvent` is yielded; no `BLEDeviceLeftEvent` is yielded; the identifier leaves `_pending_seen` silently

#### Scenario: Anonymous first advert graduates after the gate elapses
- **WHEN** an anonymous advertisement populates `_devices[ident]` at t=0 with `first_seen = t=0` and `presence_gate_s = 5.0`, AND the device is still in `_devices` at t=5.1 (subsequent adverts kept `last_seen` recent)
- **THEN** `BLEDeviceSeenEvent` is yielded with `timestamp = t=0` (the original first_seen, NOT wall-clock at graduation); the identifier moves from PENDING to PRESENT

#### Scenario: `presence_gate_s = 0` restores no-debounce
- **WHEN** `BLEPoller(presence_gate_s=0.0)` is constructed AND an anonymous advertisement populates `_devices[ident]` for the first time
- **THEN** `BLEDeviceSeenEvent` is yielded on the same tick, with no PENDING state entered

#### Scenario: Scene `office` sources a 15 s gate
- **WHEN** `diting --scene office` is launched with no explicit `--ble-presence-gate`
- **THEN** `BLEPoller.presence_gate_s == 15.0` for the session

#### Scenario: `--ble-presence-gate` overrides scene
- **WHEN** `diting --scene office --ble-presence-gate 5s` is launched
- **THEN** `BLEPoller.presence_gate_s == 5.0` for the session; the scene name remains `office` for session_meta / LLM context

#### Scenario: TTL eviction fires left
- **WHEN** a tracked device's `last_seen` exceeds the BLE TTL relative to the latest snapshot's `now` AND the identifier had previously graduated to PRESENT
- **THEN** `BLEDeviceLeftEvent` is yielded with `seen_for_seconds = last_seen - first_seen`; the entry is removed from `_state`

#### Scenario: Repeated TTL eviction of the same identifier is silent
- **WHEN** an identifier has already emitted a `BLEDeviceLeftEvent` in this session AND a subsequent advertisement re-populates `_devices[ident]` AND TTL later evicts it again
- **THEN** no additional `BLEDeviceLeftEvent` is emitted; no `BLEDeviceSeenEvent` is emitted on the re-appearance either

#### Scenario: Connected peripheral does NOT fire spurious seen events
- **WHEN** a connected peripheral is already tracked AND a subsequent connected-snapshot tick re-asserts its presence
- **THEN** no additional `BLEDeviceSeenEvent` is emitted
