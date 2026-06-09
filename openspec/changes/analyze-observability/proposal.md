# analyze-observability

## Why

`capture-context` + `capture-sampling` enriched the JSONL with a monitoring
manifest, steady-state link quality, periodic `link_sample`s, and
`scan_summary`s — but `analyze` doesn't read any of it yet. This change turns
that data into the three report sections an AI actually needs, so a quiet
static capture stops being "I can't say anything" and becomes "stable WPA2 link
at −50 dBm / 44 dB SNR on 5 GHz/80 MHz over 13 h; latency probed and clean;
38 neighbors, 9 co-channel; environment static."

## What Changes

- **Monitoring coverage & negative-space.** analyze reads `session_meta.monitors`
  + `permissions` and, for each *active* monitor with zero events, states what
  the silence means ("latency probed, 0 spikes → stable"; "rf_stir active, 0
  events → static"; "single BSSID → no roam"). Un-monitored signals are marked
  "not observed," not "nothing there."
- **Connection quality.** From the `link_state.quality` snapshot + the
  `link_sample` distribution: RSSI p50 / min / max, SNR p50, and the steady
  channel / band / PHY / security.
- **Neighbors / interference.** From `scan_summary`: neighbor count + co-channel
  count vs the current channel.
- All three are rendered in the terminal report, the Markdown / LLM document
  (EN + ZH, following `--lang`), the analyst prompt (so the model uses the
  negative-space), and `--json`. Older logs without the fields degrade
  gracefully — the sections are omitted.

## Capabilities

### Modified Capabilities

- `analyze`: the report SHALL synthesize monitoring-coverage / negative-space,
  connection-quality, and neighbor/interference sections from the capture
  observability fields, in the terminal report, the LLM document, and `--json`.

## Impact

- `src/diting/analyze.py` — parse `monitors`/`permissions`/`quality`/
  `link_sample`/`scan_summary`; new `CoverageSummary` / `ConnectionQualitySummary`
  / `NeighborSummary`; `Report` fields; `render` + `render_markdown` (EN + ZH);
  `build_llm_prompt`; `report_to_dict`.
- `src/diting/i18n.py` — ZH for the new section headers / labels.
- `tests/` + `tests/TESTING.md` (EN + ZH) + `README.md` / `docs/zh/README.md`.
