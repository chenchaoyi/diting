## MODIFIED Requirements

### Requirement: `BLEPoller` SHALL emit transition events when devices enter and leave its tracked state
`BLEPoller` SHALL emit `BLEDeviceSeenEvent` the first time a device's `identifier` (the rotation-folded stable id) appears in its tracked state map. `BLEPoller` SHALL emit `BLEDeviceLeftEvent` when a tracked device's `last_seen` falls more than the existing TTL behind the latest snapshot AND the device is then removed from state.

No debounce SHALL be applied — every first-seen identifier generates exactly one `BLEDeviceSeenEvent`, even for short-lived ghost MACs that disappear after a single advertisement. Subsequent observations of the same identifier in the same session SHALL NOT re-fire `BLEDeviceSeenEvent`.

After a `BLEDeviceLeftEvent` has fired for a given identifier within a session, the poller SHALL emit no further transition events for that identifier in the same session — neither another `BLEDeviceLeftEvent` if the identifier flaps back into `_devices` and is evicted again, nor a fresh `BLEDeviceSeenEvent` if a new advertisement re-introduces it. The identifier is terminal-departed for the rest of the session.

The `BLEPoller.events()` async iterator's union return type SHALL include `BLEDeviceSeenEvent` and `BLEDeviceLeftEvent` alongside the existing `BLEScanUpdate`.

#### Scenario: First advertisement from a new MAC fires seen
- **WHEN** an advertisement parses into a BLEDevice whose `identifier` is not in `_state`
- **THEN** `BLEDeviceSeenEvent` is yielded; on the next observation of the same identifier no further seen event is emitted

#### Scenario: TTL eviction fires left
- **WHEN** a tracked device's `last_seen` exceeds the BLE TTL relative to the latest snapshot's `now`
- **THEN** `BLEDeviceLeftEvent` is yielded with `seen_for_seconds = last_seen - first_seen`; the entry is removed from `_state`

#### Scenario: Repeated TTL eviction of the same identifier is silent
- **WHEN** an identifier has already emitted a `BLEDeviceLeftEvent` in this session AND a subsequent advertisement re-populates `_devices[ident]` AND TTL later evicts it again
- **THEN** no additional `BLEDeviceLeftEvent` is emitted; no `BLEDeviceSeenEvent` is emitted on the re-appearance either

#### Scenario: Connected peripheral does NOT fire spurious seen events
- **WHEN** a connected peripheral is already tracked AND a subsequent connected-snapshot tick re-asserts its presence
- **THEN** no additional `BLEDeviceSeenEvent` is emitted
