## Why

`diting analyze <log.jsonl>` today reads ONE file, runs ~6
single-session heuristics, and prints a per-session report. That
answers "what happened during this session" but not "where does the
pain cluster across weeks of sessions" — the question users
actually asked for when they pinged the long-timeline thread.

Now that A1 (#101) shipped the seven new BLE / Bonjour / LAN
transition event types, the JSONL has the shape needed for richer
multi-session aggregation: not just "I roamed three times" but
"every Tuesday 14-15:00 something kicks the network around".

This proposal scopes A2 of the long-timeline-analysis effort:
multi-file input + five cross-session aggregations rendered in
plain ASCII. Track B (LLM-bridge export) consumes A2's aggregates
in a later proposal.

## What Changes

### `analyze` (existing capability)

- **MODIFIED:** `diting analyze` SHALL accept multiple JSONL inputs
  via a glob (shell-expanded) and an optional `--since N` time
  filter. The CLI signature becomes
  `diting analyze [paths...] [--since DURATION]` where `paths` is
  one or more file paths or glob patterns and `--since` accepts
  the common humane forms `30d` / `7d` / `24h` / `90m` / `15m`.
  When the user passes a single path with no glob and no
  `--since`, the existing per-session behaviour SHALL be
  preserved unchanged.
- **MODIFIED:** the report's opening "span / counts / connection
  timeline" SHALL grow a "files merged" line when input contains
  more than one JSONL. Connection timeline SHALL segment per file
  (each file's start → end is one timeline block) so per-session
  context is not smeared.
- **ADDED:** new aggregator `aggregate_hour_of_day(events) ->
  dict[int, dict[str, int]]` returning the per-hour event counts
  bucketed by event type. The corresponding renderer SHALL draw a
  24-bar ASCII chart (one row per hour) labelled with the event
  count, plus a per-type breakdown line.
- **ADDED:** new aggregator `aggregate_day_of_week_x_hour(events)
  -> list[list[int]]` (7×24 grid). Renderer SHALL draw a 7×24
  ASCII heatmap using Unicode block characters (`▁ ▂ ▃ ▄ ▅ ▆ ▇ █`)
  to encode density per cell. Heaviest cell normalised to `█`,
  empty cells to a single space.
- **ADDED:** new aggregator `aggregate_per_network(events,
  inventory) -> list[NetworkAggregate]` that groups events by
  associated SSID + AP cluster (using the existing
  `NetworkInventory.resolve` + `cluster_label` machinery) and
  ranks them by event volume. Renderer SHALL show top-N (default
  10) with counts per event type as a small inline column block.
- **ADDED:** new aggregator `aggregate_daily_trend(events) ->
  list[DailyCount]` returning per-day total + 7-day rolling
  average. Renderer SHALL draw a sparkline per event-type family
  (wifi / link / ble / bonjour / lan) so a "things got worse on
  2026-04-15" pattern jumps out.
- **ADDED:** new "Top contributors" ranked list — top BSSIDs by
  cumulative `roam` + `rf_stir` count, top BLE identifiers by
  number of `ble_device_seen` events (a sign of either a busy /
  high-churn environment or a privacy-rotating device), top LAN
  hosts by DHCP-rotation count.
- **ADDED:** the report SHALL include a "Scope" header line
  surfacing: total input files, time span observed (earliest →
  latest event), and the active `--since` filter (or `none`).
- **ADDED:** `Report` SHALL gain optional fields (default-empty)
  carrying the new aggregations so test harnesses can inspect
  them without re-parsing the rendered text. Existing
  per-session fields stay unchanged so single-file callers see
  no diff.

## Out of Scope

The following are documented elsewhere or arrive with Track B:

- LLM-bridge `--for-llm` flag, prompt/report bundle, anonymizer.
  Separate change proposal.
- Matplotlib-based PNG charts. ASCII only — keeps the dep set
  zero-extra.
- Web UI / browser launcher.
- Streaming / live-update mode. `diting analyze` is batch-only.

## Migration / Defaults

Single-file `diting analyze path.jsonl` calls keep their
pre-existing terminal output verbatim (the new aggregations are
appended below the per-session report ONLY when the input spans
multiple sessions or a non-empty `--since` window). One-file users
see no diff; the new value is unlocked by passing globs or
`--since`.

The new event types from A1 (`ble_device_seen` etc.) are
recognised by every aggregator — they participate in `hour_of_day`
and the new "Top contributors" block. The existing single-session
heuristics ignore them (they're cross-session signals; firing one
per BLE adv on a per-session basis would just spam the report).

JSONL files written by older diting builds (pre-A1) are fully
supported — aggregators tolerate missing-event-type fields and
just don't surface what isn't there.
