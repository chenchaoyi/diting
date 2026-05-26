## Why

The events modal under v1.7.x still shows ~40 anonymous BLE seen/left rows in a ~90-second window in a normal office environment, even when the user is sitting still and nothing physically changed. The root cause is that **diting already knows** one physical device is rotating through multiple privacy-rotated identifiers — `src/diting/ble.py:1295` (`merge_for_display`) does that clustering for the live BLE panel, which is why the user sees `(merged 4)` badges on rows in the list view. But the BLE transition emitter in `BLEPoller` fires `BLEDeviceSeenEvent` and `BLEDeviceLeftEvent` per **identifier**, not per **cluster**. Each Apple Continuity / Microsoft CDP rotation produces a fresh identifier → graduates through the presence-gate → fires one `seen`. Then the previous identifier ages out → fires one `left`. For a single iPhone in range for an hour, that's 4-12 seens + 4-12 lefts.

The user's stated scenario: sitting at a desk, only their own phone present, the office is quiet. They expect a near-silent events modal. They get a flood — because each of their phone's identifier rotations is treated as "a new device appeared". This is not noise about behaviour the user cares about; it's noise about a privacy mechanism inside the BLE protocol.

The fix that doesn't introduce a new heuristic: apply `merge_for_display`'s existing fingerprint to the transition emitter. A new identifier that fits an existing cluster doesn't fire `seen` — it joins the cluster as a continuation. A cluster's `left` only fires when its LAST identifier ages out.

## What Changes

### Cluster index inside `BLEPoller`

A `_clusters` dict on `BLEPoller` maps `cluster_id → _BLECluster` where `_BLECluster` carries:

- `members: set[str]` — every identifier currently or historically in this cluster
- `active_members: set[str]` — identifiers still in `_devices` (not TTL-evicted)
- `representative_id: str` — the first identifier that founded the cluster; used as the JSONL event's `identifier` field
- `first_seen: datetime` — set on cluster creation; preserved across rotations
- `fingerprint: (vendor_id, name, rssi_bucket_anchor, service_uuid_signature)` — cached for fast cluster-lookup when a new identifier arrives

A parallel `_identifier_to_cluster: dict[str, str]` reverse index lets `_devices` operations look up cluster membership in O(1).

### Cluster fingerprint matches `merge_for_display` exactly

A new identifier joins an existing cluster iff:

1. `vendor_id` is identical (exact match, including both being `None`),
2. `name` is identical (exact match, including both being `None`),
3. `rssi_smooth` is within `±10 dB` of the cluster's anchor (the EMA-smoothed RSSI of the strongest member), and
4. `service_uuid` Jaccard overlap ≥ 0.5 against the cluster's union of service UUIDs.

The 10 dB / 0.5 thresholds are not new — they're the same numbers `merge_for_display` uses today. Reusing the function keeps the live-panel and the events modal *agreeing* on what counts as "the same device", which is the property the user actually cares about.

`merge_for_display` already refuses to cluster devices where both `vendor_id` and `name` are None (line 1315). The transition merger inherits that rule: fully-anonymous (vendor_id=None, name=None) identifiers each get their own one-member cluster, fire individually, and look exactly like today. This is rare in practice (Apple/Microsoft always set vendor_id), and the user can debug them separately if they care.

### Emission semantics

**On a new identifier graduating PENDING → PRESENT** (the existing presence-gate flow):

- Look up `_assign_to_cluster(identifier_state)`:
  - If it joins an existing cluster: record `cluster.members.add(identifier)` and `cluster.active_members.add(identifier)`; **emit nothing** (the cluster's existing `BLEDeviceSeenEvent` already covered the user-visible "device showed up" moment).
  - If it does not match any existing cluster: create a new cluster with `representative_id = this_identifier`, `first_seen = state.first_seen`, fingerprint cached; emit `BLEDeviceSeenEvent` with `identifier = representative_id` as today.

**On TTL eviction of an identifier**:

- Update `cluster.active_members.discard(identifier)`.
- If `cluster.active_members` is now empty (every rotation in this cluster has left): emit `BLEDeviceLeftEvent` with `identifier = representative_id`, `seen_for_seconds` measured from `cluster.first_seen` (not the evicted identifier's `first_seen`).
- Otherwise: emit nothing.

The existing presence-gate stays **in front of** the merger. An identifier that never graduates (gate-failing flit, evicted before its gate window matures) never claims cluster membership — same as today.

### JSONL log

Payload schema unchanged. `BLEDeviceSeenEvent` / `BLEDeviceLeftEvent` keep their existing fields. The `identifier` field now carries the cluster's representative ID (which is the first-graduated identifier of the cluster, byte-identical to what pre-change emitted for that cluster's first member). External consumers see fewer events, not different events. No new fields, no new event types.

### Env override

`DITING_BLE_EVENT_MERGER=0` disables the cluster collapse entirely. Every identifier graduation fires its own `seen`; every TTL eviction fires its own `left` (the pre-change behaviour). Unset / `1` / anything-not-zero enables the merger (the default).

This is for users doing security audits / debugging BLE behaviour who explicitly want the per-identifier firehose. We expect <1% of users to set this — but the escape hatch is one line of `BLEPoller.__init__`.

### Live BLE panel — no change

`merge_for_display` already runs on every snapshot of the BLE panel. The `(merged N)` badge already collapses rotations visually. This change touches the *emission* path, not the *render* path. Users see the same BLE panel they see today.

## Capabilities

### New Capabilities

(none — all changes land in existing capabilities.)

### Modified Capabilities

- `bluetooth-scanning`: new requirement that `BLEPoller` SHALL maintain a cluster index keyed on the same fingerprint as `merge_for_display`, and SHALL emit `BLEDeviceSeenEvent` / `BLEDeviceLeftEvent` at most once per cluster lifetime rather than per identifier.
- `events`: new requirement clarifying that BLE transition events represent **physical-device clusters**, not raw advertised identifiers — same payload shape, same field semantics, fewer events per real-world device.

## Impact

- **Code**: `src/diting/ble.py` (~80 lines) — `_BLECluster` dataclass, `_assign_to_cluster` helper, transition-event hooks at the PENDING→PRESENT graduation site (line ~1659) and the TTL-eviction site rewired through the cluster index. Reuses `merge_for_display`'s existing fingerprint computation (no new constants).
- **Tests**: `tests/test_ble.py` gains 6 cases — two rotations of one physical device fire one seen + one left; two physically-distinct devices with different RSSI fire two seens; merger respects presence-gate (gate-failing flit never claims a cluster); `DITING_BLE_EVENT_MERGER=0` restores per-identifier semantics; cluster departure timing (partial expiration ≠ left event); RSSI-collision false-positive (acceptable, documented).
- **TESTING.md** + **docs/zh/TESTING.md**: new row under the `bluetooth-scanning` capability table.
- **Snapshot regression** (`scripts/tui_snapshot.py`): unaffected — the live BLE panel already used `merge_for_display`; the only renderable that changes is the events modal, which has no synthetic regression fixture pinned today.
- **Dependencies**: none.
- **JSONL schema**: unchanged. `diting analyze` reads fewer events but each event carries the same field set as before.
- **Permissions / privacy**: none — the merger is a pure-Python clustering pass over data the BLE poller already has.
- **Spec deltas**: `bluetooth-scanning`, `events`.

## Out of scope

- Changing the `(merged N)` badge in the live BLE panel. It already works via `merge_for_display`; this change extends the same logic to the event emitter, nothing more.
- Exposing cluster IDs in the JSONL. Downstream consumers don't need them yet; if a future use case emerges (e.g. `diting analyze` correlating rotations across sessions) we can add a `cluster_id` field then.
- Perfect device identification via BLE bonding / IRK resolution. The Bluetooth privacy spec specifically prevents this without pairing. The fingerprint heuristic is the right level of effort for the threat model: lossy aggregation that handles the common case (one user's iPhone in range = one event) and accepts edge-case collisions (two same-vendor devices in the same RSSI bucket merge — rare, and the user can crank `DITING_BLE_EVENT_MERGER=0` to debug).
- Suppressing anonymous BLE events at the modal layer (the "Layer 2" idea from earlier discussion). Doing Layer 1 first lets us measure how much noise remains before deciding if Layer 2 is needed.
