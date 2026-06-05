# tui-shell — delta

## ADDED Requirements

### Requirement: Event rows SHALL render display-alias vendor names
BLE event rows (seen / left, strip and modal) SHALL render the resolved
vendor through the same display-alias map the BLE list and the census fold
use, so one device never shows two names across surfaces (list `Huami` vs
event `Anhui Huami Information Technology Co., Ltd.`). Vendors without an
alias pass through unchanged; the `(anonymous)` / `(unknown)` fallbacks are
unaffected.

#### Scenario: Aliased vendor in an event row
- **WHEN** a BLE seen event carries vendor `Anhui Huami Information Technology Co., Ltd.`
- **THEN** the rendered row reads `Huami  ·  <label>` — same vendor text as the BLE list row for that device

#### Scenario: Unaliased vendor passes through
- **WHEN** a BLE seen event carries a vendor with no alias entry
- **THEN** the rendered row shows the vendor string unchanged

### Requirement: The events modal SHALL order rows newest-first by event timestamp
The EventsScreen modal SHALL order its rows by event timestamp (newest
first, stable for equal timestamps) rather than raw ring order. Rationale:
presence-gated anonymous BLE adverts deliberately carry their first-observed
timestamp but emit at gate-clear while named devices emit instantly, so
emission order interleaves timestamps and the modal reads as disorder. The
JSONL log and the bottom strip keep emission order — the first-seen
timestamp semantics documented in the BLE poller are unchanged.

#### Scenario: Gated and instant events interleave
- **WHEN** the ring holds (in emission order) events stamped 18:54:09, 18:54:15, 18:54:09, 18:54:18
- **THEN** the modal renders them 18:54:18, 18:54:15, 18:54:09, 18:54:09 — monotonically non-increasing

#### Scenario: Filtering still applies before grouping
- **WHEN** a filter bucket is active
- **THEN** the timestamp ordering applies within the filtered set and the duplicate-grouping / census folding operate on the ordered rows
