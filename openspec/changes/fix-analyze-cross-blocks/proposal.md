# fix-analyze-cross-blocks

## Why

`enrich-temporal-analysis` started rendering the cross-session blocks
(hour-of-day chart, day×hour heatmap, per-network, daily trend, top
contributors) on a single long log — which exposed two pre-existing
defects in those blocks:

1. **They ignore `--lang zh`.** Their section headers / labels fall
   through to English even under `--lang zh` (e.g. `Events by
   hour-of-day`, `Day × hour heatmap (density)`, `Top networks by event
   volume`, `Top contributors`, the weekday names, and the literal
   `events` / `total`). A zh user now sees a wall of English mid-report.
2. **Top contributors → BLE ranks by the rotating `identifier`.** Each
   physical device appears under many rotated BLE addresses, so every
   row is "1 seen" — a useless ranking. The same rotating-id trap the
   population aggregate already avoids by keying on the stable
   familiarity ladder.

## What Changes

- The cross-session render blocks honor the active locale: every header
  / label is translatable and has a ZH value (the literal `events` /
  `total` get wrapped in `t()`; weekday abbreviations translate).
- Top-contributors BLE ranking keys on the **stable familiarity
  identity** (`_ble_stable_key`), not the rotating `identifier`, so it
  ranks real devices by total sightings; the column reads "BLE device".
  Sightings with no stable identity are skipped (not ranked as ones).
- The top-level `analyze` usage line is clarified: the cramped
  `--for-llm  -o DIR` (which reads as two unrelated flags — what dir?
  why `-o`?) becomes `--for-llm [-o DIR]` so the brackets show `-o` is
  the optional bundle directory that belongs to `--for-llm`, with the
  full story in `diting analyze --help`.

## Capabilities

### Modified Capabilities

- `analyze`: the cross-session render SHALL honor locale; top-contributors
  BLE SHALL rank by stable identity, not the rotating address.

## Impact

- `src/diting/analyze.py` — `aggregate_top_contributors` (BLE key);
  `_render_per_network` / `_render_daily_trend` (`t()`-wrap literals);
  `_render_top_contributors` header wording.
- `src/diting/i18n.py` — ZH for the cross-block headers, weekday names,
  `events` / `total`, and the contributor column headers.
- `tests/test_analyze.py` — top-contributors stable-key test; a
  cross-block-localization test; `tests/TESTING.md` + ZH first.
