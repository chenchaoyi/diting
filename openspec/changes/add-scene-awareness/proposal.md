# add-scene-awareness

## Why

Different physical environments make the same BLE / Wi-Fi
signal feed mean very different things:

- A home apartment with ~10 BLE devices and a single AP — every
  new identifier is a meaningful event. Anomalies dominate the
  signal.
- A corp office floor with 50+ BLE devices and 100+ BSSIDs —
  continuous churn from Apple Continuity RPA rotation, frequent
  enterprise roams; noise dominates the baseline.
- A cafe / train / plane — highest cardinality of unique
  identifiers from passers-by; almost everything is noise.

Today diting applies one set of defaults regardless. The
2026-05-21 audit + the 5.6 h capture motivating the BLE
presence gate (#111) both surfaced the same root cause: the
"right" thresholds depend on where the user is. Hard-coding
one default favours one environment at the expense of others.

In parallel, when `diting analyze --for-llm` hands a JSONL log
to ChatGPT / Claude, the LLM has no idea whether the dense BLE
churn it sees is "anomalous" (home) or "expected baseline"
(office). The same data tells different stories under different
priors. Without that context the LLM either misreads office
churn as an incident or misses real home-network novelty.

## What changes

Introduce a **scene** concept: four named environments that
each carry a set of default knobs and self-describe their
expected baseline. The user picks one per session; diting
threads the selection through the BLE poller and writes it
into the JSONL session header, so downstream tools — both the
analyzer and the LLM bundle — know what kind of environment
the data came from.

Scope of this PR (Phase 1 + Phase 4 per the user-confirmed
plan):

- **New capability** `scenes` defining the four scene names
  (`home` / `office` / `public` / `audit`), the resolution
  precedence (CLI flag > env var > default `home`), and the
  semantic of each scene (what kind of environment it
  describes).
- **`--scene SCENE` CLI flag + `DITING_SCENE` env var** —
  global, matches the existing `DITING_LANG` precedence
  pattern.
- **Scene → `ble_presence_gate_s` default mapping** (the only
  knob varied in this PR): `home=5s` (preserves today's
  default), `office=15s`, `public=30s`, `audit=0s`.
  Explicit `--ble-presence-gate D` continues to override the
  scene-derived default — narrowest wins.
- **Title-bar chip** in the TUI showing the active scene
  alongside the existing scan-interval indicator.
- **`session_meta` JSONL event** written as the FIRST line of
  every session log. Carries `scene`, `scene_source`
  (`cli|env|default`), `diting_version`, `ssid`, `gateway_ip`,
  `hostname`. Per-event lines unchanged — no per-event byte
  cost.
- **`diting analyze` reads `session_meta`** and surfaces the
  scene in the report header; cross-session aggregations note
  scene mixing if multiple JSONLs carry different scenes.
- **`diting analyze --for-llm` injects scene context** into
  the prompt template's opening paragraph, telling the LLM
  what baseline to expect ("dense enterprise env — baseline
  churn expected — look for departures from the baseline, not
  the baseline itself").

Explicitly **out of scope** (deferred to follow-up changes):

- `~/.config/diting/scenes.yaml` per-network persistence (P2).
- Auto-detect heuristic on first launch (P2).
- "new network detected — classified as …" banner (P2).
- Other knobs going scene-aware (roam_alert threshold,
  bonjour category filter, lan inventory cadence, event
  throttle) (P3).
- Basics modal "Scenes" section (P2).

## Impact

- **Default user experience unchanged** — `home` is the
  default scene and its `ble_presence_gate_s = 5.0` matches
  v1.5.0's default. A user who upgrades and runs `diting`
  without flags gets identical behaviour.
- **Office users get an obvious lever** — `diting --scene
  office` triples the presence gate (5 s → 15 s), absorbing
  more of the Continuity RPA churn that the bare presence
  gate alone doesn't fully suppress.
- **Audit users get the explicit zero-knob mode** — `--scene
  audit` removes the gate entirely. Easier to discover than
  remembering `--ble-presence-gate 0`.
- **JSONL becomes self-describing** — every `diting-*.jsonl`
  carries its session's scene in line 1. Existing readers
  (the analyzer, downstream `jq` pipelines) tolerate unknown
  event types (verified during A1 design); the new
  `session_meta` line degrades to "an unknown event we
  skipped".
- **LLM bundle prompts improve** — adding 2-3 sentences of
  scene context is high-leverage for LLM interpretation
  quality. Same JSONL + different scene context = different
  (and more accurate) conclusions.
- **No schema bump.** `session_meta` is just another event
  type in the existing event-log schema.
- **No new dependency.** No `~/.config/` writes (yaml
  persistence is P2). No new CLI subcommand.

## Affected code

- New: `src/diting/scene.py` — module-level scene state
  (mirrors `i18n.py`'s pattern), constants, resolution
  helpers, `scene_defaults(scene)` returning the per-scene
  knob map.
- `src/diting/cli.py` — `--scene` arg parser, env-var
  fallback, threads scene into `_run_tui` / `_run_monitor`,
  help text update.
- `src/diting/events.py` — new `SessionMetaEvent` dataclass.
- `src/diting/event_log.py` — `EventLogger` writes
  `session_meta` as first line on open.
- `src/diting/tui.py` — `DitingApp` accepts `scene`, threads
  to `BLEPoller` for gate default, renders title-bar chip.
- `src/diting/ble.py` — `BLEPoller.__init__` accepts a
  scene-derived `presence_gate_s` default (no shape change —
  callers compute the value from scene and pass it through;
  `--ble-presence-gate D` remains the override).
- `src/diting/analyze.py` — reader pulls `session_meta` from
  JSONL line 1, surfaces in report header; `--for-llm`
  prompt template injects scene context paragraph.
- `src/diting/i18n.py` — four scene name translations
  (`家` / `公司` / `公共` / `排查`), help-text update.

## Affected specs

- New: `openspec/specs/scenes/spec.md` — scene catalog,
  resolution precedence, knob mapping
- MODIFIED:
  - `cli/spec.md` — `--scene` flag
  - `event-log/spec.md` — `session_meta` event type
  - `analyze/spec.md` — `session_meta` consumption, LLM prompt
    context
  - `bluetooth-scanning/spec.md` — `presence_gate_s` default
    sourced from scene
  - `tui-shell/spec.md` — title-bar scene chip
