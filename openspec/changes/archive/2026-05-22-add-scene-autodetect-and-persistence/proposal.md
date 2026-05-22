# add-scene-autodetect-and-persistence

## Why

P1 (#114) shipped scene awareness — four scenes, a CLI flag, env var, and a `home` default. The user's immediate reaction on running it inside a corp office: "I'm clearly in an office (many same-name APs, enterprise auth), why does diting still show `[家]`?" That's the P1 contract working as designed (default = home; user opts in to `--scene office`) but it's not the experience the user wants.

P2 closes the gap with two pieces that work together:

1. **`scenes.yaml` per-network persistence** — same idea as `aps.yaml`, but for scene assignment. The user labels each network once (`Meituan → office`, `HomeNet → home`); subsequent launches read the file and skip auto-detect entirely.
2. **Auto-detect heuristic** — when neither `--scene` nor env var nor `scenes.yaml` decides the question, diting inspects the active Wi-Fi connection synchronously at startup and classifies the environment. Today the classifier looks at the connected AP's security mode (WPA2-Enterprise / WPA3-Enterprise → `office`) and the visible-BSSID density from the most recent scan (≥30 BSSIDs → `office`). Everything else falls to `home`.

## What changes

- **New module `src/diting/scenes_config.py`** — loads `./scenes.yaml`, looks up by SSID (primary) or by gateway MAC (fallback when an SSID is reused across many networks, e.g. `eduroam`).
- **Heuristic in `src/diting/scene.py`** — new `classify_environment(security, visible_bssid_count, ssid)` returns a scene name + a one-line human-readable reason. Pure function; testable.
- **CLI startup change** — `main()` resolves scene in this expanded precedence:
  1. `--scene SCENE` CLI flag
  2. `DITING_SCENE` env var
  3. **`scenes.yaml` lookup by SSID / gateway MAC** (new)
  4. **Auto-detect heuristic** (new) — runs a sync `MacOSWiFiBackend().get_connection()` before launching the TUI; classifies from the connection's security mode + (when CoreWLAN has a recent cached scan) visible BSSID count
  5. Default `home`
- **Banner** — when scene was set by auto-detect or by `scenes.yaml`, a one-line stderr note before the TUI starts explains the choice (`auto-detected scene: office (WPA2 Enterprise + 71 BSSIDs visible)` or `pinned scene: office (matched scenes.yaml for "Meituan")`). One-time per session; not noisy mid-run.
- **`scene_source` field gets two new values: `yaml` and `auto`** — alongside the existing `cli` / `env` / `default`. JSONL `session_meta` records the source so downstream consumers (analyzer report, LLM prompt) know whether the user explicitly chose the scene or diting guessed.
- **`scenes.example.yaml`** — top-level template, git-ignored sibling `scenes.yaml` (mirror of the `aps.yaml` / `aps.example.yaml` pair).
- **Basics modal section "Scenes"** — explains the four scenes, current scene, source of the classification. Press `b` to read it.

## Impact

- **Default user experience flips from "always home unless told otherwise" → "diting figures it out".** Users on enterprise Wi-Fi will see `[office]` automatically on first launch. The banner explains why.
- **Repeat launches on the same network become silent** — once the user pins the network in `scenes.yaml` (or accepts the auto-detect via `diting` running once on that network), the next launch reads the yaml and skips both heuristic and banner.
- **No fast-path startup cost when an explicit `--scene` or env var is set** — the auto-detect path only runs when no higher-priority source decides. The sync `get_connection()` call costs ~50 ms on a connected machine; on disconnected machines it returns None quickly and the heuristic falls to `home`.
- **No external network calls.** The classifier looks at local CoreWLAN state and the in-process scan cache; it does NOT phone home, ping the gateway, or probe captive portals.
- **JSONL consumers** — analyzer's "Scene:" header line already handles arbitrary sources via `scene_summary`; the new `yaml` / `auto` sources surface as `office (auto)` / `office (yaml)` with no schema change required. Pre-P2 logs stay readable.
- **Privacy / PII surface unchanged.** `scenes.yaml` lives in the user's working directory, git-ignored by default; gateway MAC and SSID are already in JSONL `session_meta`.

## Affected code

- New: `src/diting/scenes_config.py` (yaml loader, lookup by SSID / gateway MAC)
- New: `scenes.example.yaml` (template)
- `src/diting/scene.py` — `SOURCE_YAML`, `SOURCE_AUTO` constants; `classify_environment(...)` heuristic
- `src/diting/cli.py` — extended startup resolution (sync `get_connection()` + heuristic + banner before `_run_tui`)
- `src/diting/tui.py` — basics modal gains a "Scenes" section (EN + ZH)
- `src/diting/i18n.py` — banner strings + basics-modal section EN + ZH
- `.gitignore` — add `scenes.yaml`

## Out of scope

- **`public` auto-classification** beyond very simple cases. Captive-portal detection is hard without active probing (HTTP redirect sniffing) and we don't want to phone home. P3 territory or never.
- **Mid-session scene reclassification.** Scene is set once at startup. Roaming from `office` Wi-Fi to a `home` Wi-Fi during a single session does NOT flip the active scene. The next launch picks up the new network.
- **Other scene-aware knobs** (roam_alert, bonjour_categories, lan_inventory, event_throttle). Still P3.
