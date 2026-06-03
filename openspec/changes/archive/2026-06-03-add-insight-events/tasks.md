# Tasks

## 1. Test plan (tests-first)
- [x] 1.1 `tests/TESTING.md` (EN) — add an `insights` section + the `events`
  insight-type row + the `anomaly-watchdog` insight-notify row BEFORE tests.
- [x] 1.2 `docs/zh/TESTING.md` — mirror.

## 2. Insight event + salience
- [x] 2.1 `events.py` — `InsightEvent(timestamp, code, severity, detail=None)`
  frozen dataclass.
- [x] 2.2 `event_log.py` — `emit_insight(event)` (None-omitted detail flattened);
  multi-observer support (`add_observer`/`remove_observer`; `set_observer` keeps
  its single back-compat slot).
- [x] 2.3 `salience.py` — `insight` branch: `warn`→high, `note`→notable,
  `info`→low.

## 3. Insight engine
- [x] 3.1 `src/diting/insights.py` — `InsightEngine` (`observe(payload)` into
  bounded rolling windows, ignores `insight` type, never raises;
  `collect(now)->list[InsightEvent]` with per-code cooldown) +
  `format_insight_summary(code, detail)` localised via `t()`.
- [x] 3.2 Detectors: `new_device_cluster` (2b); `repeated_disassociates`,
  `loss_observed`, `latency_without_loss`, `band_steering` (2c). `log()` /
  comment the deferred offline-only heuristics.

## 4. Notify
- [x] 4.1 `_watchdog.py` — `maybe_notify` accepts `insight` (gate severity ∈
  {note, warn}); `notify_message` returns the insight summary.

## 5. TUI wiring + surfacing
- [x] 5.1 Construct the engine; register it as a logger observer; periodic
  `collect` timer → ring.push + `emit_insight` + panel.append_event + notify.
- [x] 5.2 `_event_format_line` gains an `InsightEvent` branch →
  `_format_insight_event` (`[INSIGHT]` row from the summary); modal shows it
  under `all`.

## 6. Tests
- [x] 6.1 Engine: cluster fires on N first_time arrivals; habitual doesn't
  cluster; cooldown fires once/window; each 2c detector triggers; malformed
  ignored; clock injected. (`tests/test_insights.py`)
- [x] 6.2 Logger: `emit_insight` JSONL shape (code/severity/detail; omit empty);
  salience stamped via severity; multi-observer fan-out.
- [x] 6.3 Companion: `insight` not push-worthy (desktop-local).
- [x] 6.4 Watchdog: warn/note insight notifies, info does not, per-code debounce.
- [x] 6.5 TUI smoke: an insight in the ring renders an `[INSIGHT]` row.

## 7. Gates
- [x] 7.1 `uv run pytest`, snapshot regression, `openspec validate --specs --strict`,
  `openspec validate add-insight-events --strict`.
