# enrich-temporal-analysis

## Why

`diting analyze` on a 13-hour overnight office log (4442 events) produced only
two insights — loss bursts and a generic note. The user's feedback: the
insights are too thin, there is **no temporal analysis** (are BLE arrivals
clustered in certain hours? how do signal patterns differ over time? what does
it mean?), and that guidance should also steer the `--for-llm` prompt.

The machinery is half-built: `analyze.py` already computes `hour_of_day` /
`day_of_week_x_hour` buckets, but (a) only when the caller passes multiple files
OR `--since` — so a single long-running log like the user's gets nothing — and
(b) nothing turns the buckets into insights, and the LLM prompt doesn't steer
toward temporal/correlation reasoning. The bundled heuristics today are
health-only (loss / latency / roam / disassoc / stir).

## What Changes

- **Enable temporal analysis on a long single log.** The cross-session gate
  also fires when the observed span is long (≥ a documented threshold), not
  only on multi-file / `--since` — a 13 h log IS a long-timeline run.
- **Temporal-rhythm insights** from the hourly buckets: per-category peak /
  quiet hours and a top-3-hour concentration read; the busiest single window;
  and a scene-aware off-hours-activity flag (office overnight, home workday).
- **Population & dwell insights** keyed on the STABLE familiarity ladder
  (never the rotating BLE `identifier`): distinct-physical-device count with a
  resident-vs-passer-by split, a dwell distribution (transient / lingering /
  resident, p50 / p90) from `ble_device_left.seen_for_seconds`, and a
  familiarity-composition recurrence read.
- **Cross-signal coincidence**: when two categories peak in the same hour(s)
  (e.g. loss bursts ∧ the BLE-arrival ramp), an insight with a hypothesis frame
  and a concrete follow-up capture window.
- **LLM prompt lenses**: a "Temporal & population lenses" block in
  `build_llm_prompt`, and the observed peak/quiet summary in the scene-context
  paragraph, so the LLM reasons about rhythm, recurrence (stable identity, not
  rotating MACs), dwell, coincidence, off-hours anomalies, and what each
  pattern implies.
- A compact "Temporal & population" block in the terminal report surfaces the
  same aggregates (gated on a meaningful span, like the existing cross-session
  block).

## Capabilities

### Modified Capabilities

- `analyze`: the bundled-heuristics requirement gains the temporal / population
  / coincidence heuristics; the temporal-enable condition is broadened to a
  long span; the `--for-llm` prompt requirement gains the temporal lenses.

## Out of scope

- Vendor-mix-over-time, a rendered concurrent-occupancy sparkline, and a
  per-network temporal split (future).
- Any change to the JSONL wire format or the live TUI insight engine
  (`insights.py` / `threats.py`) — this is offline `analyze` only.

## Impact

- `src/diting/analyze.py` — new pure aggregations on `Report`, new named
  heuristics, broadened temporal gate, renderer block, LLM prompt + scene
  paragraph.
- `src/diting/familiarity.py` — reuse / share the stable-key ladder for the
  population aggregation (JSONL-row-shaped variant).
- `src/diting/i18n.py` — EN keys + ZH values for every new string.
- `tests/test_analyze.py` + `tests/TESTING.md` + `docs/zh/TESTING.md`.
