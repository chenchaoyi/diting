# Tasks

## 1. Test plan (tests-first)
- [x] 1.1 `tests/TESTING.md` (EN) — add a `threats` section + the `insights`
  critical-severity row + the `anomaly-watchdog` critical-notify update BEFORE tests.
- [x] 1.2 `docs/zh/TESTING.md` — mirror.

## 2. Critical severity plumbing
- [x] 2.1 `salience.py` — `insight` branch: `critical`→`high` (alongside `warn`).
- [x] 2.2 `_watchdog.py` — `maybe_notify` insight gate accepts `critical`.
- [x] 2.3 `tui.py` `_format_insight_event` — `critical` → `[THREAT]` bold red row.
- [x] 2.4 `insights.py` `format_insight_summary` + `i18n.py` (EN↔ZH) — threat
  one-liners (`evil_twin`, `deauth_storm`, `follows_you`) + `[THREAT]` label.

## 3. Threat engine
- [x] 3.1 `src/diting/threats.py` — `ThreatEngine` (`observe` into bounded state,
  ignores `insight`, never raises; `collect(now)` with per-(code,target)
  cooldown emitting `critical` `InsightEvent`s). Imports `_parse_ts`.
- [x] 3.2 Detectors: `evil_twin` (same-SSID vendor change, queued in observe);
  `deauth_storm` (tight-window disassoc burst); `follows_you` (unfamiliar BLE
  across ≥2 `network_change` epochs).

## 4. TUI wiring
- [x] 4.1 Construct the threat engine; register as a logger observer; drain it in
  the existing collect timer alongside the insight engine (ring + emit + notify).

## 5. Tests
- [x] 5.1 Engine: evil_twin fires on vendor change / not on first vendor / not
  same vendor; deauth_storm tight burst vs slow; follows_you across epochs vs
  habitual; cooldown; malformed ignored; clock injected. (`tests/test_threats.py`)
- [x] 5.2 Salience: `critical`→`high`. Watchdog: `critical` notifies.
- [x] 5.3 TUI: a `critical` insight renders a `[THREAT]` row; threat engine wired
  + drains into the ring.

## 6. Gates
- [x] 6.1 `uv run pytest`, snapshot regression, `openspec validate --specs --strict`,
  `openspec validate add-threat-detections --strict`.
