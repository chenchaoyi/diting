## ADDED Requirements

### Requirement: EventsScreen SHALL collapse consecutive duplicate BLE-seen rows under a `×N` group
The EventsScreen modal renderer SHALL group runs of consecutive `BLEDeviceSeenEvent` entries whose `(vendor, name_label)` tuple is identical into a single rendered row with a `×N` suffix, where `N` is the count of folded rows. Grouping SHALL apply ONLY to the EventsScreen modal render path; the underlying `EventRing` ordering, the `BLEDeviceSeenEvent` data class, and the JSONL log on disk SHALL be unchanged.

Source-side dedup on `BLEDeviceSeenEvent` is correct per `identifier` — one event per privacy-rotated UUID. Apple Continuity and Microsoft CDP rotate identifiers continuously, so a single physical device (Find-My beacon, MS CDP advertiser, Huami fitness band) emits a fresh `BLEDeviceSeenEvent` on every rotation. Over a ~90-second capture in a dense office, the events modal becomes a flood of `device seen: Apple, Inc. · (anonymous)` / `Microsoft · (anonymous)` lines that drown out the events the user actually wants to see (roam, link drop, DHCP rotation, LAN host arrival).

The EventsScreen modal renderer SHALL group runs of consecutive `BLEDeviceSeenEvent` entries whose `(vendor, name_or_anonymous_label)` tuple is identical into a single rendered row with a `×N` suffix appended after the existing summary text, where `N` is the count of folded rows including the first. The timestamp displayed SHALL be the timestamp of the FIRST event in the run (earliest); a `→ HH:MM:SS` continuation marker SHALL be appended to indicate the most-recent timestamp in the run when `N ≥ 2`.

Grouping SHALL be strictly *consecutive* — any non-`BLEDeviceSeenEvent` row, OR any `BLEDeviceSeenEvent` with a different `(vendor, name_or_anonymous_label)` tuple, SHALL terminate the run. The relative ordering of heterogeneous events is preserved. No row order is rearranged to maximise grouping.

The `name_or_anonymous_label` SHALL be:
- the literal string `(anonymous)` when the event's stored device name field is `None` or empty
- the rendered `(rotating ID)` placeholder when the device name would have been substituted in the BLE list per the `bluetooth-scanning` rotating-identifier guard
- the verbatim name otherwise

Grouping SHALL apply ONLY to the EventsScreen modal render path. The underlying `EventRing` ordering, the `BLEDeviceSeenEvent` data class, and the JSONL log on disk SHALL be unchanged. Reads of the JSONL log by `diting analyze` and external consumers see every individual event as before.

Filter buckets (the `0`-`7` filter cycle defined in the prior EventsScreen requirement) SHALL apply BEFORE grouping. Switching to the `[1] roam` bucket suppresses BLE events entirely and shows no `×N` grouping for non-BLE rows. Switching back to `[5] ble` reapplies grouping over the BLE-only filtered list.

#### Scenario: Three consecutive identical Apple-anonymous BLE-seen events
- **WHEN** the modal renders an `EventRing` whose tail contains three `BLEDeviceSeenEvent`s with `(vendor="Apple, Inc.", name=None)` at `18:10:33`, `18:10:34`, `18:10:36`, followed by an unrelated `roam` event
- **THEN** the modal renders one line `18:10:33  [BLE]  device seen: Apple, Inc.  ·  (anonymous)  ×3  → 18:10:36` followed by the `[ROAM]` line in its original position

#### Scenario: Two BLE-seen events for different vendors do not fold
- **WHEN** the ring has `(Apple, Inc., None)` at `18:10:33` then `(Microsoft, None)` at `18:10:34`
- **THEN** both rows render separately with no `×N` suffix on either

#### Scenario: Non-BLE event breaks the run
- **WHEN** the ring has three identical `(Apple, Inc., None)` BLE-seen rows interleaved as `seen, seen, roam, seen`
- **THEN** the first two BLE rows render as one folded `×2` row, the `roam` renders as its own row, and the trailing BLE row renders as a standalone (no `×N`) row

#### Scenario: Rotating-ID name folds with itself
- **WHEN** the ring has two BLE-seen events with `(vendor="Apple, Inc.", name="NZ1NhvIw3H5T5cSy3kULrJ")` followed by a third with `(vendor="Apple, Inc.", name="Mc7g8sUZpL0eX2qY4Wt1Pq")` (different rotating ID per identifier)
- **THEN** both rows render under a single `(rotating ID) ×3` group, because the rendered label is `(rotating ID)` for all three — the substitution happens before equality comparison

#### Scenario: JSONL log is untouched
- **WHEN** ten identical `(Apple, Inc., None)` BLE-seen events fire over five seconds and the user is logging with `--log /tmp/diting.jsonl`
- **THEN** `/tmp/diting.jsonl` contains ten distinct `ble_device_seen` lines, one per event, each with its own timestamp — grouping is modal-only

#### Scenario: Filter to roam, then back to BLE
- **WHEN** the user presses `1` (roam filter), then `5` (BLE filter) with the same underlying ring
- **THEN** the roam filter renders only roam rows with no folding; switching to BLE recomputes folding from scratch over only the BLE rows
