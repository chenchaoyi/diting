# enrich-temporal-analysis — design

## Context

`analyze.analyze()` builds a `Report` then runs `_run_heuristics`. Temporal
buckets (`aggregate_hour_of_day`, `aggregate_day_of_week_x_hour`) already exist
but are gated behind `enable_cross_session = (len(paths) > 1) or (since is not
None)` — a single long log gets none. Insights use the dataclass `Insight`
(`severity` / `title` / `detail` / `todo`); each heuristic is a small
self-contained block appended in priority order. The repo rule: any BLE
device-identity work keys on the stable familiarity ladder, never the rotating
`identifier` (verified on the real log: stable key → 79 devices, identifier →
2224 useless).

## Goals / Non-Goals

**Goals:** surface the daily rhythm, the transient-vs-resident population, and
cross-signal coincidences that a long passive capture contains; steer the LLM
to the same lenses; keep everything pure / testable / scene-aware.

**Non-Goals:** no wire-format change; no live-TUI engine change; no
per-network temporal split or occupancy sparkline (future).

## Decisions

- **Broaden the temporal gate to a long span.** `enable_cross_session` also
  fires when `span = max(ts) - min(ts) >= _LONG_SPAN` (threshold ~ 2 h). The
  span is already known before the gate (`timestamps` is built in the event
  loop). Rationale: a single 13 h log is exactly a long-timeline run; the
  user's case must light up without forcing `--since`. Short per-session
  inspections stay lean (no temporal block), preserving the legacy report.
- **Pure aggregations on `Report`, heuristics read them.** New fields:
  `ble_dwell` (p50/p90 + transient/lingering/resident counts), `ble_population`
  (distinct stable-key count + hours-present histogram), `hourly_rhythm`
  (per-category peak/quiet hour + top-3-hour share), `co_peaks` (hours where
  ≥2 categories peak). Each has a pure `aggregate_*` function unit-tested in
  isolation. Mirrors the existing aggregate_* pattern.
- **Stable-key for population.** A `_ble_stable_key(event_dict)` helper mirrors
  `familiarity.familiarity_key`'s BLE ladder (manufacturer_hex non-Apple →
  service_data_id → vendor_id/name → vendor-group → None) but reads a JSONL row.
  Factor the ladder so the two definitions can't drift (shared constant set /
  thin wrapper). Sightings with no stable key are counted as "unkeyable" and
  excluded from the device count, surfaced honestly.
- **Concentration measure = top-3-hour share.** Simple, explainable, robust on
  sparse hours: `sum(top 3 hourly counts) / total`. ≥ ~0.6 → "concentrated";
  else "spread". Avoids overfitting (no entropy/Gini jargon in user copy).
- **Off-hours is scene-gated.** Office → expected-quiet = overnight (00–06);
  home → expected-quiet = workday (10–17). Activity share in the expected-quiet
  band above a threshold → a noteworthy insight, because off-baseline timing is
  what matters (the scene prior is already in `report.scenes`).
- **Co-peak hypothesis framing, not causation.** When loss/latency/stir peaks
  share an hour with the BLE-arrival peak, emit a `note` insight that states
  the coincidence + a hypothesis (airtime contention as people arrive) + a
  concrete next capture window — never asserts cause (matches the existing
  "latency spikes coincide with stir" honesty).
- **Both surfaces.** A compact terminal "Temporal & population" block (ASCII,
  gated like the cross-session block) AND the LLM prompt lenses + the rhythm
  one-liner in the scene paragraph. Terminal stays scannable; the LLM bundle
  carries the explicit question list.

## Risks / Trade-offs

- [Long-span gate changes existing single-file output] → only for logs ≥ ~2 h;
  short logs unchanged. Pin with a test at the boundary.
- [Stable-key drift from familiarity_key] → share the ladder; a test asserts
  the analyze key matches familiarity_key on the same inputs.
- [Insight overload] → keep each heuristic's trigger threshold meaningful
  (concentration ≥ 0.6, off-hours share ≥ a floor, dwell n ≥ a floor) so a
  flat/boring log doesn't sprout noise; declared-order priority keeps the most
  actionable first.
- [Hour-of-day uses the event's own tz offset] → keep the existing convention
  (`ts.hour` from the encoded offset, not `.astimezone()`), so "what hour of
  the user's day" is stable regardless of where `analyze` runs.
