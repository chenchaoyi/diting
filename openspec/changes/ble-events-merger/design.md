## Context

`BLEPoller` (in `src/diting/ble.py`) tracks per-identifier state in `_devices: dict[str, BLEDevice]`. Each `BLEDevice` represents one advertised identifier — for Apple Continuity / Microsoft CDP advertisers, this rotates every 5-15 minutes by design. The poller has two sets of bookkeeping for transition events:

- `_seen_identifiers: set[str]` — per-session set, prevents double-firing `BLEDeviceSeenEvent` for the same identifier across snapshot ticks.
- `_pending_seen: dict[str, datetime]` — first-observation timestamps for identifiers in PENDING (anonymous-first-observation, awaiting the presence-gate window before graduating).

When an identifier graduates PENDING → PRESENT (gate matures or first observation carries a name), `_pending_transitions.append(BLEDeviceSeenEvent(...))` fires. When TTL evicts an identifier that previously graduated, `_pending_transitions.append(BLEDeviceLeftEvent(...))` fires.

`merge_for_display(devices, *, rssi_window_db=10)` (line 1295) folds rotated identifiers in the live BLE panel:

- Bucket by `(vendor_id, name)` — exact match, including None.
- Within each bucket, cluster by RSSI: sort by smoothed RSSI descending, anchor at the strongest, pull in anything within `±10 dB`.
- Devices where both `vendor_id` and `name` are None are not bucketed — flagged as `unmergeable` and rendered individually.

The badge `(merged N)` in the BLE panel comes from `_fold_cluster()` summing `ad_count` across the cluster and tracking `merged_count`.

The gap this change closes: the transition emitter doesn't consult any of this. It fires per-identifier, so the events modal sees N "device appeared" events when one physical device rotates through N identifiers.

## Goals / Non-Goals

**Goals:**

- A single physical device that rotates through N identifiers SHALL produce one `BLEDeviceSeenEvent` and one `BLEDeviceLeftEvent` across the cluster's session.
- The clustering heuristic SHALL be byte-identical to `merge_for_display` — same fingerprint, same thresholds, same `(vendor_id=None AND name=None)` exception. The user expects the events modal to agree with the live panel's `(merged N)` badges.
- The presence-gate SHALL stay in front of the merger. A gate-failing flit never claims cluster membership.
- The JSONL log SHALL produce fewer events with **identical payload shape** to today — same field set, same types, same `identifier` value (the cluster's representative). External consumers downgrade gracefully.
- One env-var escape hatch (`DITING_BLE_EVENT_MERGER=0`) restores pre-change semantics for users doing security audits or per-identifier debugging.

**Non-Goals:**

- Reworking `merge_for_display` itself. The heuristic is good enough for the BLE panel and good enough for the events modal.
- Changing the live BLE panel rendering. It already merges; this change is about the event stream.
- Exposing cluster identity in the JSONL. `cluster_id` field is premature — no consumer needs it yet.
- Perfect physical-device identification. BLE privacy specifically prevents it; the heuristic is acceptable lossy aggregation.
- Layer 2 (default-hide anonymous BLE events in the modal). Out of scope for this change — measure Layer 1's impact first.

## Decisions

### Cluster state lives inside `BLEPoller`, not as a standalone module

`_BLECluster` is a private dataclass in `ble.py` next to `BLEPoller`. Two reasons:

1. The cluster state is only meaningful in the context of the poller's existing PENDING / PRESENT machinery. Hoisting it to its own module would require exposing the poller's internal identifier-state-transition hooks publicly.
2. The fingerprint computation reuses `merge_for_display`'s logic. Same file, same constants, no risk of one place's `rssi_window_db` drifting from the other.

### Fingerprint matching reuses `merge_for_display`'s rules verbatim

`_assign_to_cluster(state)`:

```python
def _assign_to_cluster(self, state: BLEDevice) -> str | None:
    """Return the existing cluster_id this identifier joins, or None
    if no existing cluster matches and a fresh one should be created.

    Refuses to cluster identifiers where both vendor_id AND name are
    None — same exception merge_for_display already documents.
    """
    if state.vendor_id is None and state.name is None:
        return None  # unmergeable; gets its own one-member cluster
    state_rssi = self._effective_rssi(state)
    state_services = set(state.services)
    for cluster_id, cluster in self._clusters.items():
        if cluster.vendor_id != state.vendor_id: continue
        if cluster.name != state.name: continue
        if abs(state_rssi - cluster.anchor_rssi) > 10: continue
        # Jaccard overlap on service UUIDs — protects against two
        # devices that happen to share (vendor, name, RSSI bucket)
        # but advertise different service stacks (rare but possible).
        if cluster.service_uuids or state_services:
            union = cluster.service_uuids | state_services
            inter = cluster.service_uuids & state_services
            if len(union) > 0 and (len(inter) / len(union)) < 0.5:
                continue
        return cluster_id
    return None
```

The 0.5 Jaccard threshold and the 10 dB window are taken from `merge_for_display`'s existing implementation — see `tests/test_ble.py::test_merge_folds_same_vendor_and_name_within_rssi_window` for the current pinning.

### Cluster `representative_id` is the first graduated identifier

The cluster's `seen` event uses `identifier = cluster.representative_id`, which is the first identifier that founded the cluster. This is the same semantic `merge_for_display` already exposes via `_fold_cluster`'s "strongest-RSSI entry serves as the representative" — except for events, we use first-by-time rather than first-by-RSSI, because the `seen` event has already fired by the time later identifiers join and we can't go back and revise it.

For the user this is invisible. For `diting analyze` it means the `ble_device_seen` JSONL line carries an identifier that's valid (corresponds to a real per-host UUID the BLE poller saw) and stable across the cluster's life.

### TTL departure: cluster lives until last member leaves

When an identifier is TTL-evicted from `_devices`, the poller calls `_handle_identifier_departure(identifier)`. The function:

1. Looks up `cluster_id = self._identifier_to_cluster.get(identifier)`. None means the identifier never graduated (gate-failed flit) — return.
2. `cluster.active_members.discard(identifier)`.
3. If `cluster.active_members` is empty: append a `BLEDeviceLeftEvent` to `_pending_transitions` with `identifier = cluster.representative_id`, `seen_for_seconds = (now - cluster.first_seen).total_seconds()`, then delete the cluster from `_clusters` and from `_identifier_to_cluster` for every member.
4. Otherwise: silent. The cluster is still represented by remaining active members.

This is the "one left per cluster" guarantee, symmetric to "one seen per cluster" on the entry side.

### When the merger collides (two real devices, same fingerprint)

Edge case: two physically distinct devices share `(vendor_id, name, RSSI bucket, service UUID set)`. Example: two MacBooks on the same desk, both advertising the same Apple Continuity beacon, both reading ~-50 dBm to the user.

The merger will collapse them into one cluster. The events modal shows one `seen` instead of two. The live BLE panel ALREADY shows them merged via `merge_for_display` — so the events modal just agrees with the live view.

Trade-off accepted: in a "sitting still in office" environment the collision rate is low (different devices read at different RSSI), and when it happens the live panel shows the same merge. Users who need per-identifier visibility set `DITING_BLE_EVENT_MERGER=0`.

### `DITING_BLE_EVENT_MERGER=0` resolution

Resolved once in `BLEPoller.__init__` into `self._enable_cluster_merger: bool`. When False, `_assign_to_cluster` is bypassed — every identifier graduation creates a one-member cluster and fires `seen`; every TTL eviction fires `left`. The cluster index still exists (the bookkeeping is cheap) but it never folds.

We resolve once at construction, not per-event, because mid-session env changes don't make sense and the test cases want determinism.

### Performance

Cluster lookup is linear in the number of clusters. For a busy office that's ~20-50 clusters at steady state. Each lookup is a dict scan with cheap field comparisons. At BLE poll cadence (~2 s), the work is negligible vs the BLE backend's own overhead.

If a future user reports >500 clusters in a real environment (e.g. a major airport), we'd add a `(vendor_id, name) → list[cluster_id]` index to amortize the bucket lookup. Not needed for v1 of this change.

## Risks / Trade-offs

[Risk] **Two physically distinct devices share the fingerprint and get merged.** → Mitigation: same trade-off the live BLE panel already accepts; `DITING_BLE_EVENT_MERGER=0` escape hatch for security audits. Users complaining can also temporarily set the env var in a session to see per-identifier detail.

[Risk] **`merge_for_display`'s thresholds change and the event merger gets out of sync.** → Mitigation: both code paths import the SAME constants (`_RSSI_WINDOW_DB = 10`, `_JACCARD_THRESHOLD = 0.5`) — extracting them as module-level constants is part of the implementation. A `tests/test_ble.py` invariant pins that both code paths read from the same source.

[Risk] **JSONL consumers (downstream `diting analyze` or third-party scripts) might depend on the per-identifier event firehose.** → Mitigation: `diting analyze` only reads `type / ts / vendor / name / identifier / rssi` and aggregates upward; fewer events with the same shape means analyze runs faster. No public consumer of the JSONL has been reported that requires per-identifier granularity. The escape hatch covers users who do.

[Risk] **User's iPhone walks out of range and back in: should that fire two `seen` events or one?** → Mitigation: the cluster gets deleted when all its identifiers TTL-evict. On the phone's return, new identifiers don't find a matching cluster (the old one is gone), so a fresh cluster is created and `seen` fires. This is the desired behaviour — the user wants to know "the phone came back".

[Risk] **A user's phone in a moving car with sharp RSSI swings repeatedly creates new clusters because RSSI drifts outside the 10 dB window.** → Mitigation: `rssi_smooth` is the EMA-smoothed value, which dampens single-packet jitter. Sharp swings caused by physical motion ARE legitimate state changes worth knowing about. Accept the slight over-firing in mobile cases — the design's primary target is stationary indoor use where RSSI is stable.

[Risk] **The implementation's cluster fingerprint diverges from `merge_for_display`'s actual behaviour because the spec describes the heuristic in prose while the test suite pins specific cases.** → Mitigation: extract the matching logic into a shared `_fingerprint_matches(a, b, *, rssi_window_db, jaccard_threshold) -> bool` function called from BOTH `merge_for_display` and `_assign_to_cluster`. Single source of truth at the code level, not just at the spec level.

## Migration Plan

No migration. The change is a behaviour shift in `BLEPoller.events()` output — consumers (the events modal, the JSONL log writer) automatically see fewer events with the same payload shape. The shift takes effect for any session started under the new code; ongoing sessions across an upgrade don't exist (diting is a foreground CLI, not a daemon).

Rollback: revert the change OR set `DITING_BLE_EVENT_MERGER=0` to disable at runtime without code change.

## Open Questions

- Should the cluster lifetime be capped (e.g. "after 1 hour of continuous presence, force a fresh `seen` event so analyze sees something")? **Defer**: today nothing demands periodic re-confirmation events; downstream consumers want fewer events not more. Add later if a real use case appears.
- Should the JSONL gain a `merged_count` field on `ble_device_seen` analogous to the BLE list panel's `(merged N)` badge? **Defer**: shape parity with pre-change keeps `diting analyze` working unchanged. Adding the field is cheap if a future user wants to attribute "this seen represents N rotation cycles".
- Should `DITING_BLE_EVENT_MERGER` be a CLI flag too (`--ble-event-merger=0`)? **Defer**: env-only matches the precedent set by `DITING_BLE_PRESENCE_GATE`. Add CLI flag if it becomes a hot-debug toggle.
