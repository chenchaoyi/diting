# analyze-observability — tasks

## 1. Test plan first

- [x] 1.1 TESTING.md rows (EN) — coverage/negative-space, connection-quality,
      neighbors sections; back-compat omission; --json keys
- [x] 1.2 Mirror in docs/zh/TESTING.md
- [x] 1.3 Tests: coverage negative-space ("monitored & quiet" vs "not
      observed"); quality RSSI distribution; neighbors; --json shape; zh render

## 2. Implement

- [x] 2.1 `CoverageSummary` / `ConnectionQualitySummary` / `NeighborSummary`
      dataclasses + `Report` fields (appended, defaulted)
- [x] 2.2 `analyze()` parses monitors/permissions/quality/link_sample/scan_summary
      → builds the three summaries (signal_events count map for negative-space)
- [x] 2.3 `render` + `render_markdown` — three sections, EN + ZH (gated on present)
- [x] 2.4 `build_llm_prompt` references the coverage section
- [x] 2.5 `report_to_dict` — coverage / connection_quality / neighbors
- [x] 2.6 i18n ZH for the new headers / labels

## 3. Docs

- [x] 3.1 README.md + docs/zh/README.md — mention the new sections

## 4. Verify

- [x] 4.1 `uv run pytest` (incl. i18n audit guard + analyze baseline)
- [x] 4.2 analyze a log with the new fields → three sections present (EN + zh);
      older log → omitted
- [x] 4.3 `tui_snapshot --mode regression`
- [x] 4.4 `openspec validate --specs --strict` + the change
