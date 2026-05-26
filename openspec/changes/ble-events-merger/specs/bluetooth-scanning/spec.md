## ADDED Requirements

### Requirement: `BLEPoller` SHALL emit transition events keyed on rotated-identifier clusters, not raw identifiers
`BLEPoller` SHALL maintain a per-session cluster index that groups privacy-rotated identifiers belonging to the same physical device. The cluster fingerprint SHALL be byte-identical to the heuristic `merge_for_display` already uses for the live BLE panel: `(vendor_id, name)` exact match (including both being `None`), RSSI smoothed value within `±10 dB` of the cluster's anchor, and Jaccard overlap on service UUIDs ≥ 0.5. Identifiers where both `vendor_id` and `name` are `None` SHALL NOT participate in clustering — same exception `merge_for_display` documents — and SHALL each get a single-member cluster.

`BLEPoller` SHALL emit `BLEDeviceSeenEvent` at most once per cluster lifetime: when the cluster is created on the first identifier's graduation through the existing presence-gate flow. Subsequent identifiers that join the cluster as rotation continuations SHALL NOT trigger a fresh seen event. The `BLEDeviceSeenEvent.identifier` field SHALL carry the cluster's representative identifier (the first identifier that founded the cluster).

`BLEPoller` SHALL emit `BLEDeviceLeftEvent` exactly once per cluster: when the LAST identifier in the cluster's active-member set is TTL-evicted. The `BLEDeviceLeftEvent.identifier` SHALL carry the same representative identifier as the cluster's seen event; the `seen_for_seconds` field SHALL measure from the cluster's `first_seen` (the first graduation), not the most-recently-evicted identifier's first observation. Partial cluster departure (one identifier evicts while others remain in `_devices`) SHALL be silent internal bookkeeping.

The presence-gate flow (the existing `presence_gate_s` window for anonymous-first-observation identifiers) SHALL remain in front of the cluster merger. An identifier evicted before its presence gate matures SHALL NOT claim cluster membership — same no-event semantics as today.

`BLEPoller.__init__` SHALL accept `enable_cluster_merger: bool = True`. When False, the cluster index is bypassed: every identifier graduation creates a single-member cluster and fires its own `seen`; every TTL eviction fires its own `left`. The constructor parameter resolves once at construction.

The environment variable `DITING_BLE_EVENT_MERGER=0` SHALL set `enable_cluster_merger=False`; any other value (including unset) SHALL leave the default `True`. Mid-session env changes are not supported.

The cluster index and `merge_for_display` SHALL read the matching thresholds (`_RSSI_WINDOW_DB`, `_JACCARD_THRESHOLD`) from shared module-level constants in `src/diting/ble.py`. The two code paths SHALL NOT independently encode the numeric thresholds.

#### Scenario: One physical iPhone rotating four identifiers fires one seen + one left
- **WHEN** a single iPhone is in range for an hour, rotating its Continuity identifier 4 times (4 successive PENDING→PRESENT graduations through the presence gate, each subsequent identifier's RSSI within ±10 dB of the cluster anchor, vendor_id=76 / name=None throughout, service UUIDs overlapping ≥ 0.5)
- **THEN** the events stream contains exactly one `BLEDeviceSeenEvent` (fired when the first identifier graduated) and, after the last identifier TTL-evicts, exactly one `BLEDeviceLeftEvent` with `seen_for_seconds` ≈ 3600

#### Scenario: Two physically-distinct iPhones at different RSSI buckets fire two seens
- **WHEN** two iPhones in the same room read at -50 dBm and -75 dBm respectively (more than 10 dB apart in EMA-smoothed RSSI)
- **THEN** they create two separate clusters; each fires its own `BLEDeviceSeenEvent` with distinct representative identifiers; their `BLEDeviceLeftEvent`s remain distinct when each device departs

#### Scenario: Presence-gate-failing flit does not claim a cluster
- **WHEN** an anonymous BLE identifier is observed once with vendor_id=76, name=None, but is TTL-evicted before the scene's `presence_gate_s` window matures
- **THEN** the identifier is silently dropped from `_devices`; no cluster is created; no `BLEDeviceSeenEvent` or `BLEDeviceLeftEvent` fires; the cluster index has no entry for this identifier

#### Scenario: `DITING_BLE_EVENT_MERGER=0` restores per-identifier semantics
- **WHEN** the user starts diting with `DITING_BLE_EVENT_MERGER=0` and a single iPhone rotates through 4 identifiers in one session
- **THEN** 4 `BLEDeviceSeenEvent`s and 4 `BLEDeviceLeftEvent`s fire; the cluster index is bypassed even though `merge_for_display` continues to fold the BLE panel's `(merged 4)` badge

#### Scenario: Partial cluster departure is silent
- **WHEN** a cluster contains 3 active identifiers and one of them is TTL-evicted while the other 2 remain in `_devices`
- **THEN** no `BLEDeviceLeftEvent` fires; the cluster's `active_members` set drops to 2; the cluster's `first_seen` is unchanged; the representative identifier may or may not be the one that just evicted (the eviction does not rotate the representative)

#### Scenario: Cluster representative survives later identifiers
- **WHEN** the cluster's first identifier (the representative) is TTL-evicted while a subsequently-joined rotation remains active
- **THEN** the cluster persists with its remaining members; the cluster's stored `representative_id` is unchanged; when the cluster eventually fires its `BLEDeviceLeftEvent`, the `identifier` field still carries the original representative ID (this is the same identifier that the `BLEDeviceSeenEvent` named, so external consumers correlating seen↔left by identifier still match)

#### Scenario: Fully-anonymous identifier (vendor_id=None, name=None) gets its own cluster
- **WHEN** a BLE device with `vendor_id=None` and `name=None` graduates through the presence gate
- **THEN** the cluster index does NOT bucket it with other identifiers (matching `merge_for_display`'s unmergeable exception); a single-member cluster is created and a `BLEDeviceSeenEvent` fires; when the identifier TTL-evicts the cluster fires its own `BLEDeviceLeftEvent`

#### Scenario: Cluster lifetime ends; identifier returns later
- **WHEN** an iPhone leaves the user's range entirely (all members TTL-evict; cluster is destroyed; a `BLEDeviceLeftEvent` fires), then re-enters range 20 minutes later with a fresh identifier
- **THEN** the new identifier does NOT find a matching cluster (the previous cluster was destroyed); a new cluster is created; a fresh `BLEDeviceSeenEvent` fires — the device's return is a real event worth surfacing

#### Scenario: Both code paths read the same threshold constants
- **WHEN** a future contributor lowers `_RSSI_WINDOW_DB` from 10 to 6 to tune the merger
- **THEN** both `merge_for_display` (BLE panel) and the transition cluster index (`BLEPoller._assign_to_cluster`) pick up the new threshold automatically; the unit test pinning them to a shared constant prevents divergence
