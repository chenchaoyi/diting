## MODIFIED Requirements

### Requirement: The report SHALL open with span / counts / connection timeline
Every report SHALL begin with: a `Scope` header line surfacing the file count, time-span observed (earliest → latest event), and active `--since` filter (or `none`); total event count by type; time span (first event → last event in human-readable duration); and a connection timeline derived from the `connection_update` log-only stream. The timeline SHALL show each contiguous "associated to BSSID X for Y minutes" segment.

When the input spans multiple JSONL files, the connection timeline SHALL render per-file (each file's start → end is one timeline block). The `Scope` line SHALL surface the file count.

When the input is a single file AND no `--since` filter is set, the report SHALL preserve the existing per-session layout verbatim — the new cross-session aggregations are appended below the per-session report only when the user is genuinely doing a multi-session view (multiple files OR `--since`).

#### Scenario: 4-hour single-session report
- **WHEN** the user runs `diting analyze single-session.jsonl` (one file, no `--since`)
- **THEN** the report renders the existing per-session layout (span / counts / timeline / heuristic insights) with no cross-session aggregations appended; a `Scope` line shows `Scope: 1 file · <span> · --since none`

#### Scenario: Multi-file long-timeline report
- **WHEN** the user runs `diting analyze 'diting-*.jsonl'` (shell expands to 5 files spanning 32 days)
- **THEN** the report opens with `Scope: 5 files · 2026-04-19 → 2026-05-20 (32 days) · --since none`; per-file timelines render; cross-session aggregations render below

## ADDED Requirements

### Requirement: `diting analyze` SHALL accept multiple JSONL paths and an optional `--since DURATION` filter
The CLI signature for the analyze subcommand SHALL accept one OR MORE path arguments (positional, `nargs="+"`) and an optional `--since DURATION` flag. Shell glob expansion is the only path-matching mechanism (the tool does not glob-match itself).

`--since DURATION` SHALL parse the common humane forms via a shared regex: `<integer><unit>` where unit is one of `s` / `m` / `h` / `d`. Examples: `30d`, `7d`, `1d`, `12h`, `90m`, `15m`, `60s`. The filter applies AFTER `parse_jsonl` and BEFORE any aggregator, so every downstream view sees the same filtered list.

The tool SHALL fail with a clear error message when (a) no paths resolve to readable files, OR (b) `--since` is not parseable.

#### Scenario: Glob expands to multiple files
- **WHEN** the user runs `diting analyze 'diting-*.jsonl'` with three matching files in the working directory
- **THEN** the tool reads all three, merges their events into one in-memory list (preserving timestamps), and runs every aggregator over the combined stream

#### Scenario: `--since 7d` filters by recency
- **WHEN** the user runs `diting analyze 'logs/*.jsonl' --since 7d` and the matched files span the last 30 days
- **THEN** the aggregations cover only the most recent 7 days of events; the `Scope` line reflects the filtered span and surfaces `--since 7d`

#### Scenario: Unparseable `--since` rejected
- **WHEN** the user runs `diting analyze foo.jsonl --since "last Tuesday"`
- **THEN** the CLI exits non-zero with a clear error pointing at the allowed `<integer><unit>` form

#### Scenario: No files resolve
- **WHEN** the user runs `diting analyze 'no-match-*.jsonl'` and the glob expands to zero files
- **THEN** the CLI exits non-zero with a "no matching files" message; no empty / misleading report is rendered

### Requirement: An hour-of-day aggregator SHALL bucket every event into one of 24 hourly slots
`aggregate_hour_of_day(events)` SHALL return `dict[int, dict[str, int]]` keyed by hour (0..23). Each hour's value is a Counter-like mapping from event-type name to count. The renderer SHALL draw a 24-bar ASCII chart (one row per hour) with a per-hour total + the most-common event type for that hour as a parenthesised hint.

#### Scenario: Lunch-time LAN churn surfaces
- **WHEN** the analyzer sees 47 events at 12:00 (38 of which are `lan_host_seen`)
- **THEN** the rendered hour-of-day chart shows hour 12 with a bar proportional to 47 plus the hint `(most: lan_host_seen)`

### Requirement: A day-of-week × hour heatmap aggregator SHALL produce a 7×24 grid
`aggregate_day_of_week_x_hour(events)` SHALL return a list of 7 lists, each of 24 integers (Mon..Sun × 0..23, cell value = total event count). The renderer SHALL draw the grid using Unicode block characters `▁▂▃▄▅▆▇█` mapped to 8 density bins normalised to the heaviest cell. Empty cells SHALL render as a single space so the eye picks out the dense regions.

#### Scenario: "Tuesday afternoon is the worst"
- **WHEN** the heatmap's Tuesday-15:00 cell holds the highest count in the grid
- **THEN** that cell renders as `█`; lighter Tuesday-9:00 cells render as `▂` or `▃`; an empty Sunday-3:00 cell renders as a single space

### Requirement: A per-network aggregator SHALL group events by associated BSSID and rank by volume
`aggregate_per_network(events, inventory)` SHALL group every event by the BSSID the user was associated to AT EVENT TIME — derived by scanning the `connection_update` rows alongside the events stream and picking the most recent `associated <bssid>` line preceding each event. Events whose connection context cannot be resolved SHALL be attributed to a synthetic `(unknown network)` bucket and reported separately. The returned list SHALL be sorted by total event count, descending, with the renderer surfacing the top 10 by default.

#### Scenario: Office AP dominates the ranking
- **WHEN** the user spent 80% of session time on `Meituan` AP and the events are evenly distributed
- **THEN** the per-network rank surfaces `Meituan (5G)` first with ~80% of the total event count

#### Scenario: Orphan events surface separately
- **WHEN** an event has no preceding `connection_update` in the JSONL (older log file written before connection-update was added)
- **THEN** the event is bucketed under `(unknown network)`, NOT silently dropped or mis-attributed to a default

### Requirement: A daily-trend aggregator SHALL produce per-day counts with a 7-day rolling average
`aggregate_daily_trend(events)` SHALL return a list of `(date, total_count, rolling_7d_avg)` triples ordered by date ascending. The rolling 7-day average is a simple windowed mean over the last 7 daily totals (right-edge alignment; days within the first 6 of the window use the available days only).

The renderer SHALL emit one ASCII sparkline PER event-type family (`wifi` = roam + rf_stir; `link` = latency_spike + loss_burst + link_state; `ble`; `bonjour`; `lan`). Each sparkline uses the Unicode block characters described in the day×hour aggregator.

#### Scenario: Things got worse after a firmware update
- **WHEN** the daily-roam count is `~3` per day for 21 days, then jumps to `~12` per day for the next 11 days
- **THEN** the `wifi` sparkline visually steps up at the transition; the rolling-7d-avg series climbs from `3` toward `12` over the window after the step

### Requirement: A top-contributors ranking SHALL surface the three biggest pain sources
The report SHALL include a `Top contributors` section with three sub-rankings, each top-10:

1. **BSSIDs by `roam` + `rf_stir` count.** Resolves to AP name via the inventory when possible; falls back to the cluster label (or raw BSSID with first-octet wildcard) when unresolved.
2. **BLE identifiers by `ble_device_seen` count.** Labelled with resolved name + vendor when available. High counts include both stable always-present devices AND fast-rotating privacy MACs — the renderer does NOT try to distinguish; it surfaces both as informative signals.
3. **LAN hosts by `lan_host_dhcp_rotation` count.** Labelled with vendor + bonjour name + IP. Picks up DHCP-misbehaving devices.

Each sub-ranking SHALL surface a single tabular block with three columns: identity, count, optional context.

#### Scenario: One AP is responsible for half the wifi pain
- **WHEN** out of 314 combined roam + rf_stir events, 215 are at AP `Meituan/AP-7`
- **THEN** the BSSID sub-ranking lists `Meituan/AP-7  (?af:5e:9d)` first with `215`

#### Scenario: A privacy-rotating BLE device dominates
- **WHEN** a privacy-rotating device fires 142 distinct `ble_device_seen` events across the timeline window
- **THEN** the BLE sub-ranking surfaces it with `142` even though those are 142 different identifiers (each one fires its own seen event once per session)

### Requirement: Cross-session aggregations SHALL be append-only — they SHALL NOT change the per-session report shape for single-file callers
When the user runs `diting analyze single-session.jsonl` with no `--since` filter, the report's bytes SHALL be identical to the pre-A2 behaviour for that input (modulo the new `Scope` header line). Every cross-session aggregation block (hour-of-day chart, day×hour heatmap, per-network ranking, daily trend, top contributors) SHALL be appended below the per-session report ONLY when the input spans multiple files OR `--since` is set.

#### Scenario: Single-file no-since input keeps the legacy layout
- **WHEN** the user runs `diting analyze old-session.jsonl` (no `--since`, one file)
- **THEN** the rendered report contains the existing span / counts / timeline / insights / "what to do next" sections but NOT the hour-of-day / day×hour / per-network / daily-trend / top-contributors blocks
