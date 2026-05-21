## 1. Test plan (test-first)

- [ ] 1.1 `tests/TESTING.md` (EN) — under `### analyze`, add rows for: multi-file glob input, `--since` parsing + filter, `Scope` header line, hour-of-day aggregator + render, day×hour heatmap, per-network grouping + orphan-event bucket, daily trend + rolling avg, top-contributors three-sub-ranking, single-file-no-since preserves legacy layout (regression guard).
- [ ] 1.2 `docs/zh/TESTING.md` — mirror.

## 2. CLI plumbing

- [ ] 2.1 `src/diting/cli.py::_register_analyze` — change `path` to `paths` (`nargs="+"`); add `--since DURATION` argparse argument with a custom `type=` function `parse_since(value)` that accepts the `<int><unit>` regex form and returns a `timedelta`.
- [ ] 2.2 `src/diting/cli.py::_cmd_analyze` — read all paths (no glob — shell does it), concatenate event lists in timestamp order, apply `--since` filter, route into `analyze.analyze(events, source_paths=[...])`.

## 3. Aggregators (`analyze`)

- [ ] 3.1 `src/diting/analyze.py::aggregate_hour_of_day(events) -> dict[int, Counter]` — 24 buckets keyed by event.timestamp.hour; Counter inside keys event types.
- [ ] 3.2 `src/diting/analyze.py::aggregate_day_of_week_x_hour(events) -> list[list[int]]` — 7 lists of 24 ints, indexed by `datetime.weekday()` (Mon=0) and hour.
- [ ] 3.3 `src/diting/analyze.py::aggregate_per_network(events, inv) -> list[NetworkAggregate]` — walks connection_update history; assigns each event to the most recent associated BSSID; events without a context land in `(unknown network)`.
- [ ] 3.4 `src/diting/analyze.py::aggregate_daily_trend(events) -> list[DailyCount]` — per-day totals + 7-day rolling avg.
- [ ] 3.5 `src/diting/analyze.py::aggregate_top_contributors(events, inv) -> TopContributors` — three sub-ranks: BSSIDs by roam+stir count, BLE identifiers by seen count, LAN hosts by dhcp_rotation count. Each top-10 by default.

## 4. Renderers

- [ ] 4.1 `src/diting/analyze.py::_render_scope_header` — single line surfacing files + span + active --since.
- [ ] 4.2 `src/diting/analyze.py::_render_hour_of_day` — 24-row ASCII bar chart.
- [ ] 4.3 `src/diting/analyze.py::_render_day_x_hour_heatmap` — 7×24 ASCII heatmap using Unicode block characters.
- [ ] 4.4 `src/diting/analyze.py::_render_per_network` — top-10 ranked list with per-type column block.
- [ ] 4.5 `src/diting/analyze.py::_render_daily_trend` — per-family sparkline.
- [ ] 4.6 `src/diting/analyze.py::_render_top_contributors` — three sub-ranking tables.
- [ ] 4.7 `src/diting/analyze.py::render` — gate the cross-session blocks on `len(source_paths) > 1 OR since is not None`.

## 5. Tests

- [ ] 5.1 `tests/test_analyze.py` — additions per design D7.
- [ ] 5.2 `tests/test_cli.py` — `--since` flag + multi-path threading.

## 6. CI gates

- [ ] 6.1 `uv run pytest`
- [ ] 6.2 `uv run python scripts/tui_snapshot.py --mode regression`
- [ ] 6.3 `openspec validate --specs --strict`
- [ ] 6.4 `openspec validate long-timeline-analyze --strict`
