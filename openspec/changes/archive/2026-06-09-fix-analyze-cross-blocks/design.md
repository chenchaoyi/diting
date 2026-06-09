# fix-analyze-cross-blocks — design

## Context

The cross-session render blocks (`_render_hour_of_day`, `_render_day_x_hour`,
`_render_per_network`, `_render_daily_trend`, `_render_top_contributors`)
already wrap their headers in `t()` but have no ZH catalog entries, so they
fall through to English — invisible until `enrich-temporal-analysis` surfaced
them on the single-long-log path. `aggregate_top_contributors` keys its BLE
ranking on `ev["identifier"]` (the rotating BLE address), so a device seen
under many rotated ids becomes many "1 seen" rows. `_ble_stable_key` already
exists (mirrors `familiarity.familiarity_key`) and is used by the population
aggregate.

## Decisions

- **Add ZH for the cross-block headers; wrap the two stray literals.** The
  headers are already `t()` calls — they just need catalog values. The
  literal `events` (`_render_per_network`) and `total` (`_render_daily_trend`)
  get wrapped in `t()`. Weekday abbreviations (`Mon`…`Sun`) translate to
  `周一`…`周日`. Headers are section/annotation lines, so the small CJK
  width shift versus the ASCII column rules below them is acceptable (all rows
  shift consistently); the data rows stay English (vendor strings, hex).
- **Top-contributors BLE keys on `_ble_stable_key`, not `identifier`.** A
  device seen N times under N rotated addresses ranks as one entry with count
  N — the meaningful ranking, consistent with the population aggregate and the
  [[feedback_no_name_based_classification]] / stable-key principle already in
  the temporal spec. Unkeyable sightings (no manufacturer/name/vendor) are
  skipped rather than ranked as spurious ones. The column header reads
  "BLE device" (it ranks devices now, not identifiers).
- **Clarify the top-level usage one-liner.** `--for-llm  -o DIR` →
  `--for-llm [-o DIR]`: the brackets bind `-o DIR` to `--for-llm` and mark it
  optional. The per-subcommand `diting analyze --help` (added in
  agent-friendly-cli) already carries the full explanation + examples, and the
  subcommands header already points there. This is help-copy only — no spec
  requirement, no behaviour change.

## Risks / Trade-offs

- [CJK width breaks heatmap alignment] → the day×hour grid is a density
  heatmap, not a data table; weekday labels shift all rows equally, so they
  stay aligned with each other. Acceptable for a glanceable chart.
- [Top-contributors ranking changes shape] → the old per-identifier output was
  unusable (all ones); the new per-device ranking is strictly more useful. The
  existing test updates to assert the stable-key behaviour.
