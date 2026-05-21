# Design

A2 of the long-timeline analysis effort. Builds on the richer
event vocabulary A1 (#101) added, surfaces patterns across many
JSONL files at once.

## D1. Input model: globs + `--since`

`diting analyze path1.jsonl path2.jsonl ...` accepts multiple
paths. Shell handles glob expansion (`*.jsonl` → 5 paths) so
diting doesn't need to do glob matching itself; the CLI just
receives a list. When zero paths resolve, the tool fails loudly
with a clear "no matching files" error rather than silently
emitting an empty report.

`--since DURATION` filters events to those whose timestamp is
within the last DURATION before "now":

- `30d`, `7d`, `1d`, `12h`, `90m`, `15m`, `60s` — all parse via
  one shared regex (`(\d+)([smhd])$`).
- `--since` applies AFTER parsing the JSONL but BEFORE aggregation,
  so all aggregators see the same filtered event list.

The existing single-file no-`--since` path is preserved
verbatim — analyze.py's `parse_jsonl(path)` is still callable and
returns the same shape.

## D2. Why aggregate per event type

Single per-hour total like "47 events at 14:00" is less actionable
than "47 events at 14:00, of which 38 are `lan_host_seen` —
something is churning the LAN at lunch". So each aggregator
bucket carries a Counter keyed by event-type name; the renderer
shows totals AND the dominant contributor.

For the day-of-week × hour heatmap, the cell value is the
TOTAL count (not per-type) to keep the rendering tractable. Type
breakdown is available via the hour-of-day aggregator if the user
wants to drill in.

## D3. Per-network grouping

Events that carry a BSSID (`roam`, `rf_stir`, `link_state`) are
grouped by their *new_bssid* (or `bssid` when present). Events
that don't carry a BSSID directly (`latency_spike`, `loss_burst`,
`ble_device_*`, `bonjour_service_*`, `lan_host_*`) are attributed
to the network the user was associated to at event time — derived
by walking the `connection_update` rows alongside the events
stream and picking the most recent `associated <bssid>` line
preceding each event.

When the connection-update history is incomplete (older JSONL files
or sessions that started disassociated), the event is attributed to
the synthetic bucket `(unknown network)` — appears separately so
the user can see how much pain is unattributed.

## D4. Daily-trend sparkline

ASCII sparkline using Unicode block characters `▁▂▃▄▅▆▇█` mapped
to 8 bins of (count / max_count). Empty days render as a space.

Per-day buckets are computed from the event timestamp's local-TZ
date (timezone-aware via the existing `_parse_ts` path). 7-day
rolling average is a simple windowed mean over the daily counts —
no centred-window stats; just the last 7 days at each point.

Sparkline per event-type family:

```
roam       ▁▂▁▃▁▂▁ ▁▂▁▃▄▅ ▇ █ █  (33-day window)
rf_stir    ▁▁▁▁▁▁▁ ▁▁▁▁▁▁ ▁ ▂ ▂
latency    ▂▃▂▃▄▅▃ ▂▂▂▃▄▅ ▆ █ █  (latency_spike + loss_burst folded)
ble        ▁▁▂▃▄▅▇ █▇▆▅▄▃ ▂ ▁ ▁
bonjour    ▁▁▁▁▁▁▂ ▂▂▂▂▂▂ ▂ ▂ ▂
lan        ▁▂▃▃▃▄▄ ▄▅▅▆▆▆ ▇ ▇ ▇
```

## D5. Top-contributors ranking

Three sub-ranks, each top-10:

- **BSSIDs by roam+stir count**: the AP that's causing the most
  Wi-Fi pain. Resolves to AP name via inventory.
- **BLE identifiers by `ble_device_seen` count**: high-count
  identifiers are either always-present devices (Magic Keyboard
  in the user's office) OR privacy-rotating devices firing a
  fresh identifier per ad. The renderer doesn't try to
  distinguish — both are useful signals — and labels each with
  the resolved vendor/name when available.
- **LAN hosts by DHCP-rotation count**: hosts whose IP changes
  most often. Either misbehaving DHCP leases or roaming devices.

## D6. Rendering layout

```
Scope: 12 files · 2026-04-19 → 2026-05-20 (32 days) · --since none

Events by hour-of-day                  total: 2,341
  00 ░                                      8
  01                                        0
  ...
  09 ██░░                                  47    (most: lan_host_seen)
  10 ████░░░                                89    (most: ble_device_seen)
  ...

Day × hour heatmap (density)
  Mon  ▁▁▁▁▁▁▁▁▁▁▂▃▂▃▃▃▂▁▁▁▁▁▁▁
  Tue  ▁▁▁▁▁▁▁▁▁▁▂▃▃▄▄▅▃▂▁▁▁▁▁▁
  Wed  ▁▁▁▁▁▁▁▁▁▁▂▃▃▃▃▃▂▁▁▁▁▁▁▁
  Thu  ▁▁▁▁▁▁▁▁▁▁▂▃▃▄▃▃▂▁▁▁▁▁▁▁
  Fri  ▁▁▁▁▁▁▁▁▁▁▂▃▃▃▃▃▂▁▁▁▁▁▁▁
  Sat  ▁▁▁▁▁▁▁▁▁▁▂▃▃▃▃▂▂▁▁▁▁▁▁▁
  Sun  ▁▁▁▁▁▁▁▁▁▁▂▃▃▃▃▂▂▁▁▁▁▁▁▁
       0   6   12  18  23

Top networks by event volume                 (top 10)
  Meituan (5G)            842 events   roam 287 · stir 12 · latency 84 · ble 412 · lan 47
  home-5G                 503 events   ...
  ...

Daily trend (32-day window, with 7-day rolling avg)
  roam       ▁▂▁▃▁▂▁▁▂▁▃▄▅▇████▇▆▅▄▃▂▁▁▁▁▁▁▁▁▁
  ...

Top contributors
  AP                                 roam+stir
    Meituan/AP-7  (?af:5e:9d)              215
    home-5G/AP-1  (50:c7:bf:11:22:33)      47
    ...
  BLE identifier                     seen events
    Magic Keyboard (Apple, Inc.)            142
    AirPods Pro (Apple, Inc.)               89
    ...
  LAN host                           dhcp rotations
    Apple, Inc. · ccy-MBP24-M4-Office       12
    ...
```

## D7. Test surface

`tests/test_analyze.py` additions:

- `test_aggregate_hour_of_day_buckets_events_into_24_slots`
- `test_aggregate_hour_of_day_carries_type_breakdown`
- `test_aggregate_day_of_week_x_hour_returns_7x24_grid`
- `test_aggregate_per_network_groups_by_associated_bssid`
- `test_aggregate_per_network_attributes_orphan_events_to_unknown`
- `test_aggregate_daily_trend_yields_per_day_counts`
- `test_aggregate_daily_trend_includes_rolling_avg`
- `test_top_contributors_ranks_bssids_by_roam_plus_stir`
- `test_top_contributors_ranks_ble_identifiers_by_seen_count`
- `test_top_contributors_ranks_lan_hosts_by_dhcp_rotation_count`
- `test_since_filter_parses_30d_24h_15m_etc`
- `test_since_filter_rejects_invalid_format`
- `test_glob_expansion_via_multiple_paths_aggregates_into_single_report`
- `test_single_file_no_since_preserves_existing_layout`

`tests/test_cli.py` additions:

- `test_analyze_multi_path_args_thread_through`
- `test_analyze_since_flag_threads_through`

## D8. Surface impact

- `src/diting/analyze.py` — new aggregator functions (~250 LoC),
  new renderers (~200 LoC), extended `Report` dataclass.
- `src/diting/cli.py` — `--since` argparse flag; `paths` becomes
  `nargs="+"`.
- `tests/test_analyze.py` — additions (~300 LoC).
- `tests/test_cli.py` — small additions.

No new third-party dependency.
