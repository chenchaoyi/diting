## 1. Test plan (test-first, per CLAUDE.md hard rule)

- [x] 1.1 Add a "Cluster-keyed BLE transition events" row to `tests/TESTING.md` under the `bluetooth-scanning` capability table — pin the cluster fingerprint reuse, the one-seen / one-left per cluster lifetime, the presence-gate ordering, the env override, and the partial-departure-is-silent invariant.
- [x] 1.2 Mirror into `docs/zh/TESTING.md`.

## 2. Extract shared cluster-fingerprint constants

- [x] 2.1 In `src/diting/ble.py`, define module-level constants `_RSSI_WINDOW_DB: int = 10` and `_JACCARD_THRESHOLD: float = 0.5` next to `merge_for_display`. Replace the literal `10` in `merge_for_display`'s `rssi_window_db` default parameter with the constant.
- [x] 2.2 Define a shared helper `_fingerprint_matches(a_state, cluster_anchor_rssi, cluster_services, *, rssi_window_db=_RSSI_WINDOW_DB, jaccard_threshold=_JACCARD_THRESHOLD) -> bool` that encodes the matching logic. The function checks: same `vendor_id`, same `name`, `|state_rssi - anchor_rssi| <= rssi_window_db`, and Jaccard overlap on service UUIDs ≥ jaccard_threshold. Refuses to match when both vendor_id and name are None (returns False).
- [x] 2.3 Wire `_fingerprint_matches` into `merge_for_display`'s cluster-pull loop so the live BLE panel and the transition emitter share one source of truth. Verify `tests/test_ble.py::test_merge_folds_same_vendor_and_name_within_rssi_window` still passes.

## 3. `_BLECluster` dataclass + cluster index in `BLEPoller`

- [x] 3.1 Add `@dataclass class _BLECluster` near `BLEPoller`:
  - `cluster_id: str` (generated; UUID4 or counter)
  - `representative_id: str` (the first graduated identifier)
  - `vendor_id: int | None`, `name: str | None` (cached fingerprint key)
  - `anchor_rssi: int` (the EMA-smoothed RSSI of the strongest member)
  - `service_uuids: set[str]` (union of all members' service UUIDs)
  - `members: set[str]` (every identifier that has ever joined)
  - `active_members: set[str]` (identifiers still in `_devices`)
  - `first_seen: datetime`
- [x] 3.2 Add `BLEPoller._clusters: dict[str, _BLECluster]` and `BLEPoller._identifier_to_cluster: dict[str, str]` reverse index. Initialize in `__init__`.
- [x] 3.3 Add `BLEPoller._enable_cluster_merger: bool = True`. Read `DITING_BLE_EVENT_MERGER=0` from env in `__init__` (or accept as a kwarg overriding env for testing).

## 4. `_assign_to_cluster` + emission-hook rewires

- [x] 4.1 Add `BLEPoller._assign_to_cluster(state: BLEDevice) -> str | None` that walks `_clusters.values()`, returns the matching cluster's `cluster_id`, or `None` if no match. Refuses to match when `vendor_id is None AND name is None` (returns None — caller will create a single-member cluster).
- [x] 4.2 At the PENDING→PRESENT graduation site in `BLEPoller` (~line 1659), wrap the `BLEDeviceSeenEvent` emission:
  - If `_enable_cluster_merger` is False: behave as today (emit per identifier).
  - Else: call `_assign_to_cluster(state)`. If returns `cluster_id`: append identifier to that cluster's members + active_members, **do not emit**. If returns None: create a fresh `_BLECluster` with `representative_id = this_identifier`, append to `_clusters` and `_identifier_to_cluster`, **emit `BLEDeviceSeenEvent`** as today.
- [x] 4.3 At the TTL-eviction site, refactor existing logic into `_handle_identifier_departure(identifier)`:
  - Look up `cluster_id = _identifier_to_cluster.get(identifier)`. None → no-op (gate-failed flit or pre-cluster identifier).
  - `cluster.active_members.discard(identifier)`.
  - If `cluster.active_members` is empty: emit `BLEDeviceLeftEvent(identifier=cluster.representative_id, seen_for_seconds=now - cluster.first_seen, …)`; delete `_clusters[cluster_id]`; delete every member from `_identifier_to_cluster`.
  - Else: no event; leave the cluster intact.
- [x] 4.4 Update the `_departed_identifiers` set semantics to track on a per-cluster basis (so re-entering identifiers don't claim a destroyed cluster; the cluster's destruction is the gate). Documented in a comment block at the cluster index.

## 5. Tests

- [x] 5.1 `tests/test_ble.py::test_cluster_one_iphone_rotating_four_identifiers_fires_one_seen_one_left` — drive `BLEPoller` through 4 successive identifier graduations with matching fingerprint; assert exactly 1 seen + (after evictions) 1 left in `_pending_transitions`; assert the `identifier` field on both events is the FIRST identifier of the rotation.
- [x] 5.2 `tests/test_ble.py::test_cluster_two_devices_at_different_rssi_buckets_fire_separately` — two synthetic `BLEDevice` graduations 15 dB apart in EMA RSSI; assert two clusters created; two seen events; on departure two left events; identifiers are distinct.
- [x] 5.3 `tests/test_ble.py::test_cluster_presence_gate_failing_flit_does_not_claim_cluster` — anonymous identifier observed once, evicted before gate window matures; assert no cluster created in `_clusters`; no `BLEDeviceSeenEvent` or `BLEDeviceLeftEvent` fired; `_identifier_to_cluster` empty.
- [x] 5.4 `tests/test_ble.py::test_cluster_disabled_via_env_restores_per_identifier_semantics` — construct `BLEPoller(enable_cluster_merger=False)`; same 4-rotation scenario as 5.1; assert 4 seen events + 4 left events fire.
- [x] 5.5 `tests/test_ble.py::test_cluster_partial_departure_silent` — cluster with 3 active identifiers; evict one; assert no `BLEDeviceLeftEvent` fires; cluster persists in `_clusters` with 2 active members; representative_id unchanged.
- [x] 5.6 `tests/test_ble.py::test_cluster_lifetime_ends_then_device_returns_fires_fresh_seen` — cluster's last identifier evicts, fires left, cluster destroyed; later a new identifier arrives matching the destroyed cluster's fingerprint; assert a NEW cluster is created and a fresh seen event fires.
- [x] 5.7 `tests/test_ble.py::test_cluster_fully_anonymous_devices_each_get_own_cluster` — two BLE identifiers both with `vendor_id=None AND name=None`, similar RSSI; assert two single-member clusters created (no merge), two seen events.
- [x] 5.8 `tests/test_ble.py::test_cluster_fingerprint_constants_shared_with_merge_for_display` — invariant test: assert `_RSSI_WINDOW_DB` and `_JACCARD_THRESHOLD` are module-level constants in `diting.ble`; assert `merge_for_display`'s default `rssi_window_db` reads from the constant.
- [x] 5.9 `tests/test_ble.py::test_cluster_representative_id_survives_when_first_member_evicts` — cluster with 3 members; the original representative evicts while others remain; cluster's stored `representative_id` is unchanged; when the last member eventually evicts, the `BLEDeviceLeftEvent.identifier` still names the original representative.

## 6. Env-var resolution + integration

- [x] 6.1 In `src/diting/ble.py`, resolve `DITING_BLE_EVENT_MERGER` from env in `BLEPoller.__init__` if no `enable_cluster_merger` kwarg was passed. Accept `0` / `false` / `no` (case-insensitive) as disable; anything else (including unset) keeps default `True`.
- [x] 6.2 In `src/diting/cli.py`, no wiring needed — the env var is read by `BLEPoller` directly, same pattern as the existing `DITING_BLE_PRESENCE_GATE` (which is also CLI-flag-overrideable; we don't add a CLI flag here per the open question in design.md).

## 7. CI gates

- [x] 7.1 `uv run pytest` — green
- [x] 7.2 `uv run python scripts/tui_snapshot.py --mode regression` — unaffected (the BLE panel renders via `merge_for_display` which already merged; the events modal has no synthetic regression fixture)
- [x] 7.3 `openspec validate --specs --strict` — green
- [x] 7.4 `openspec validate ble-events-merger --strict` — green

## 8. Manual visual check

- [ ] 8.1 Sit still at a desk in a quiet office, run `uv run diting` with `--log /tmp/diting-merger.jsonl`. Watch the events modal for ~5 minutes; confirm anonymous BLE event count is dramatically reduced vs the pre-change session captured in the original screenshot.
- [ ] 8.2 Run the same session with `DITING_BLE_EVENT_MERGER=0 uv run diting --log /tmp/diting-firehose.jsonl`. Confirm the events modal floods (pre-change behaviour preserved as escape hatch).
- [ ] 8.3 `jq '.type=="ble_device_seen"' < /tmp/diting-merger.jsonl | wc -l` and same for the firehose log. Confirm the merger log has dramatically fewer lines (10:1 ratio or better in a busy office).
- [ ] 8.4 In the BLE panel during the merger session, confirm the `(merged N)` badges still appear correctly (this is `merge_for_display`'s domain, unaffected by the change but worth eyeballing for consistency).
- [ ] 8.5 Walk out of the office with the laptop running. When clusters TTL-evict, confirm one `device left` event per physical device fires (not one per rotation cycle).

## 9. Wrap-up

- [x] 9.1 EN ↔ ZH parity check on the new TESTING entries.
- [ ] 9.2 Commit and push the branch `feat/ble-events-merger`.
- [ ] 9.3 Open the PR using the repo template.
