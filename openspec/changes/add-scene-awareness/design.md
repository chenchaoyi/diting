# design — add-scene-awareness

## Scene catalog (this PR locks in four)

| Scene | Description | Baseline expectation | LLM prior |
|---|---|---|---|
| `home` | apartment / own Wi-Fi, ≤ ~15 BLE, single AP. Default. | sparse RF; signal ≫ noise. Anomalies matter. | "small known network — novelty matters" |
| `office` | corp floor, enterprise Wi-Fi, dense BLE + many BSSIDs | noise ≫ signal. Continuous churn is the baseline. | "dense enterprise env — baseline churn expected" |
| `public` | cafe / train / plane / public Wi-Fi | noise ≫≫ signal. Almost everything is passers-by. | "hostile shared Wi-Fi — cardinality is noise" |
| `audit` | actively investigating: forensics / security / device debug | record everything; no filtering | "raw capture — no filtering applied" |

Why exactly four:

- `home` and `office` are the most common two (the user's
  primary use case spans both).
- `public` is a recognisable third with materially different
  baselines.
- `audit` is the explicit "give me everything" mode, far more
  discoverable than `--ble-presence-gate 0`.
- A fifth (`mobile` / hotspot) was considered and rejected for
  P1 — it's similar enough to `home` that the user can use
  `--scene home` and tune later. Easy to add in a follow-up
  without a breaking change.

## Scene → knob mapping (P1 scope)

The only knob this PR varies per scene is `ble_presence_gate_s`:

| Scene | `ble_presence_gate_s` | Why |
|---|---|---|
| `home` (default) | **5.0 s** | Identical to v1.5.0 default. No behavioural break for users who upgrade and don't pass `--scene`. |
| `office` | **15.0 s** | Three-times the home gate. Absorbs more of the Continuity RPA churn that 5 s alone doesn't fully suppress in the user's captured environment. |
| `public` | **30.0 s** | Most aggressive — public Wi-Fi is mostly noise; even legitimate "walk-by" signals are throwaway. |
| `audit` | **0.0 s** | Disables the gate. Equivalent to passing `--ble-presence-gate 0`. |

Other knobs (`roam_notify_threshold`, `bonjour_categories_visible`, `lan_inventory_default`, `event_throttle`) are **out of scope** for this PR — they're documented in `scene_defaults()` as future fields but not yet read by any consumer. Adding them in P3 will be code-only changes (no spec break) because the dispatch is centralised through `scene_defaults()`.

## Resolution precedence

Mirrors the existing `DITING_LANG` model exactly:

```
1. CLI flag:       --scene SCENE                 # current session
2. Env var:        DITING_SCENE=SCENE            # persistent shell setting
3. Default:        home                          # baseline for new users
```

`--ble-presence-gate D` is **independent** of `--scene` and
takes precedence: a user who passes `--scene office
--ble-presence-gate 5s` gets a 5 s gate, scene-driven 15 s
notwithstanding. Narrowest knob always wins. The use case:
"I'm in the office but want home-grade sensitivity for the
next 30 min while I investigate this one thing." `--scene
audit` covers most of these, but explicit gate-override is
useful for fine tuning.

## `scenes.yaml` deferred (Phase 2)

Per-network persistence (the `~/.config/diting/scenes.yaml`
file mapping SSIDs to scene names) is intentionally NOT in
this PR. The reasoning:

- Phase 1 is "make the feature exist". Phase 2 is "make it
  ergonomic over time".
- Yaml persistence requires a new config-loading subsystem,
  a path-resolution layer (where do we put it?), and a
  schema versioning approach. All worth doing, but not the
  highest-leverage piece.
- The user can already set `DITING_SCENE=office` in their
  shell rc, which is 80 % of "persistent per-machine
  preference". Per-network granularity is a step beyond.
- Once we know the four scenes work as designed in real use,
  P2 can codify the file format with confidence.

## `session_meta` event placement

Written exactly **once per session**, as the first JSONL
line. Format:

```json
{
  "type": "session_meta",
  "ts": "2026-05-22T13:00:00+08:00",
  "scene": "office",
  "scene_source": "cli",
  "diting_version": "1.6.0",
  "ssid": "Meituan",
  "gateway_ip": "11.10.128.1",
  "hostname": "ccy-mbp"
}
```

Why first line, not header / sidecar:

- Stays in the same JSONL stream — no second file, no parse
  branching downstream.
- `jq 'select(.type=="session_meta")'` works as expected.
- Analyzer reading multiple JSONLs cleanly groups
  `session_meta` events by their `ts` proximity to per-event
  `ts` values.
- Old `diting` builds reading new JSONL skip the unknown
  type gracefully (verified during A1 design — analyzer
  tolerates unknown event types).

Fields chosen for high LLM-utility:

- `scene` + `scene_source` — the load-bearing context.
- `ssid` + `gateway_ip` — lets the LLM correlate sessions
  across the same network even without scene matching.
- `diting_version` — so a future LLM-side analysis tool can
  branch on schema-bump differences.
- `hostname` — anonymizer-aware (the existing `--anonymize`
  flag will map this to `HOST_1` if engaged).

Fields explicitly NOT included to keep PII surface low:

- BSSID of the connected AP (could doxx physical location;
  `aps.yaml`-named users can opt in via a future change).
- User account name.
- MAC of the Mac running diting.

## LLM prompt context injection

`diting analyze --for-llm` already writes a 5-section
analyst prompt. The new addition is a **scene-context
paragraph** prepended to the prompt's role section:

```
[Scene context]
These sessions were captured in `office` mode (Meituan
enterprise Wi-Fi, observed BSSID count ~80, observed BLE
device count ~50). Baseline expectation: continuous BLE churn
from Apple Continuity RPA rotation; roams every 5-15 min due
to AP density; LAN inventory disabled by scene default.
**Look for departures from this baseline, not the baseline
itself.**
```

For multi-session input where scenes differ, the paragraph
acknowledges the mix:

```
[Scene context]
Three of the four input sessions were captured in `home`
mode; one was `office`. Treat the office session's BLE
density as expected baseline; the home sessions' identifier
counts above ~30 are notable.
```

Both forms are generated from the per-scene `llm_prior`
string in `scene_defaults()`, with the observed counts
backfilled from the session_meta's environment fields when
present.

## Why scene state is a module-level global (not per-poller)

Following the `i18n.py` pattern. `_scene` is set once at
process startup by the CLI, read everywhere via
`get_scene()`. Avoids threading the scene through every
constructor signature and matches how language is handled
today. Tests use `set_scene()` to force a scene for
deterministic behaviour.

The scene-driven `presence_gate_s` is computed once in
`cli.py` (from `get_scene()` + `--ble-presence-gate`
override) and passed to `BLEPoller` as a concrete float —
the poller itself doesn't import the scene module. Keeps
the poller's signature unchanged from #111.

## What this design does NOT commit to

- **A `--scene auto` value with heuristic detection.** Phase
  2. Today `auto` is not a valid scene name.
- **Scene-specific event types.** All scenes emit the same
  event vocabulary; only thresholds and the scene-meta
  context differ.
- **Mutable scene during a session.** Scene is set once at
  startup and stays for the session. Switching mid-session
  would require re-emitting `session_meta` and re-tuning
  active pollers — too much complexity for too little win.
- **Hiding events from the TUI based on scene.** Even at
  `--scene public`, events that fire still render in the
  events panel; the gate only controls whether they fire.
  Display filtering belongs to the EventsScreen filter
  cycle (1/2/3/4/5/6/7/0), not the scene.
