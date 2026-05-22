# design — add-scene-autodetect-and-persistence

## The expanded resolution precedence

```
1. CLI flag       --scene SCENE                      (highest)
2. Env var        DITING_SCENE=SCENE
3. scenes.yaml    SSID match → scene, or
                  gateway_mac match → scene
4. Heuristic      classify_environment(security, bssid_count, ssid)
5. Default        home                                (lowest)
```

The scene_source field on session_meta extends accordingly:
`cli` / `env` / `yaml` / `auto` / `default`.

## The heuristic — what it looks at

`classify_environment(security: str | None, visible_bssid_count: int, ssid: str | None)` returns `(scene: str, reason: str)`.

Rules in priority order. First match wins.

| Rule | Condition | → Scene | Reason text |
|---|---|---|---|
| 1 | `security` contains "Enterprise" (case-insensitive) — covers `WPA2 Enterprise`, `WPA3 Enterprise`, `WPA-Enterprise` | `office` | "{security} auth" |
| 2 | `visible_bssid_count >= 30` | `office` | "{N} BSSIDs visible" |
| 3 | otherwise | `home` | "no enterprise auth, sparse BSSID surface" |

Public detection is intentionally absent. Open Wi-Fi exists in homes (your neighbour's) and offices (guest network); without active probing we can't distinguish "I'm in a cafe" from "I'm in a hotel". Forcing `--scene public` is the user's call.

The threshold of 30 BSSIDs is conservative — a corp floor easily sees 60+ on 5 GHz alone; a typical apartment sees 10-20 from neighbours. 30 is the rough crossover. Configurable later if real-world data shows we need to tune; today it's a constant.

## `scenes.yaml` schema

Mirrors `aps.yaml`: a flat top-level mapping, optional file, git-ignored. `scenes.example.yaml` ships as a template.

```yaml
# scenes.yaml — diting per-network scene assignment
#
# OPTIONAL. Without this file, diting auto-detects from the active
# Wi-Fi connection's security mode + BSSID density.
#
# To pin a scene for a known network:
#   1. cp scenes.example.yaml scenes.yaml
#   2. add a `networks:` entry below
#   3. relaunch diting; the banner will read "pinned scene"

networks:
  # Match by SSID (most common). First match wins.
  - ssid: HomeNet
    scene: home
  - ssid: Meituan
    scene: office

  # Match by gateway MAC when SSID is reused across networks
  # (e.g. eduroam everywhere, or multiple homes with same name).
  # Gateway MAC takes precedence over SSID when both match.
  - gateway_mac: 14:51:7e:71:5a:1a
    scene: office
```

Loader is permissive: missing file → empty registry; malformed entries → warn on stderr + skip. Diting MUST NOT exit because the yaml is broken (matches `aps.yaml`'s philosophy).

## When the resolution happens

Resolution moves from `main()`'s pure-function call to a small startup phase **before launching the TUI / monitor**. The phase looks like:

1. Parse CLI / env.
2. If CLI or env set the scene → done, skip everything else.
3. Construct `MacOSWiFiBackend()` (cheap, no helper spawn).
4. Call `backend.get_connection()` synchronously. Returns `Connection | None` within ~50 ms.
5. If connection is `None` (no Wi-Fi) → fall straight to `home` default, source `default`.
6. Look up SSID in `scenes.yaml`. If hit → done, source `yaml`.
7. Run `classify_environment(connection.security, scan_cache_bssid_count, connection.ssid)` → scene + reason. Source `auto`.
8. Print banner (`auto-detected scene: office (WPA2 Enterprise auth)` or `pinned scene: office (matched "Meituan" in scenes.yaml)`).
9. Hand the backend object to `_run_tui` / `_run_monitor` so they don't have to re-construct.

The "scan cache" in step 7 reads from `backend.get_scan_results()` only if it returns synchronously without re-issuing a scan. If the backend has nothing cached, BSSID count is 0 and rule 2 won't fire — that's fine, rule 1 + rule 3 still classify correctly for most users.

## Banner format

EN:
```
auto-detected scene: office (WPA2 Enterprise auth)
```
or
```
pinned scene: office (matched "Meituan" in scenes.yaml)
```
or — when defaulting because no Wi-Fi:
```
scene: home (default — no Wi-Fi connection at startup)
```

ZH:
```
自动识别场景：公司（WPA2 Enterprise 认证）
锁定场景：公司（scenes.yaml 命中 "Meituan"）
场景：家（默认 —— 启动时无 Wi-Fi 连接）
```

Banner prints to stderr (so stdout-piped users don't see it interleaved with their JSONL); single line; one-time per session. Suppressible via `DITING_SCENE_QUIET=1` for users who don't want the chatter.

## Edge cases

**No Wi-Fi connection at all** → `get_connection()` returns None → scene = `home`, source = `default`, banner says so. The user later associating to Wi-Fi does NOT trigger re-classification (per the P1 contract: scene is set once at startup).

**Wi-Fi associated but no security info** → `connection.security` may be `None` for some helpers / TCC states. Rule 1 falls through. Rule 2 still checks BSSID count. Rule 3 catches the rest as `home`.

**`scenes.yaml` matches by both SSID and gateway_mac** → gateway_mac wins. Use case: multiple networks share an SSID (eduroam, guest WiFi naming collision). The MAC pins the specific network.

**`scenes.yaml` says `scene: shop`** (invalid name) → loader skips that entry with a stderr warning, falls through to next match candidate then heuristic. A broken yaml never crashes diting.

**User passes `--scene office` then re-launches with `--scene home`** → second launch's CLI flag wins. No persistence to think about — `scenes.yaml` is human-curated only; the auto-detector never writes to it.

## What this design does NOT do

- **Does not write to `scenes.yaml`.** The file is human-curated. Auto-detect runs every launch (when no other source decides). If a user wants permanence, they pin manually.
- **Does not detect captive portals.** Public Wi-Fi classification requires `--scene public` or `DITING_SCENE=public`.
- **Does not run a fresh scan on startup.** Reuses the CoreWLAN scan cache if present. Heuristic rule 2 doesn't fire when cache is empty — that's fine, rule 1 covers the most common "I'm at work" case.
- **Does not reclassify mid-session.** Scene is fixed at startup. Roaming from office Wi-Fi to home Wi-Fi during a single diting session keeps the original scene; next launch picks up the new one.
- **Does not introduce a new `--scene auto` flag.** Auto-detect is what runs by default when nothing else decides. Users who want to FORCE the heuristic to run (e.g. to reset a stale yaml hit) can comment out the yaml entry; we don't need a flag for it.
