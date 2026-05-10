## Why

The project scope has already grown well past "Wi-Fi". BLE work is
roughly a third of current capabilities, and the roadmap calls for
LAN / mDNS / sensing / tethered-iPhone coverage. The name
`wifiscope` undersells what the tool now does and will keep doing.
Picking the right name *now* — before any public launch, PyPI
release, or installed-user base — is essentially free. Picking it
later means breaking grants, links, and search results.

The new name is **谛听 (Diting)** — the Buddhist mythical creature
whose ear can hear all sounds in ten directions. It covers the
broader thesis ("listen to the signals around you that macOS
quietly perceives but doesn't show"), keeps the sensing flagship
direction in the name, and is unoccupied in the macOS / RF /
network observability namespace.

## What Changes

- **Project name** `wifiscope` → `谛听 (Diting)`
- **CLI binary**: `wifiscope` → `diting`
- **Helper bundle**: `wifiscope-helper.app` → `diting-tianer.app` (and its inner binary `wifiscope-helper` → `diting-tianer`). The helper is conceptually the *ear* of 谛听 — the privileged Swift bundle that hears the macOS-API signals the Python sandbox cannot. 天耳 (tiān'ěr, "heavenly ear") is the Buddhist supernatural power 谛听 itself possesses; naming the helper `diting-tianer` makes the architecture self-describing in one phrase: "谛听 is the brand, 天耳 is its ear."
- **Environment variable prefix**: `WIFISCOPE_*` → `DITING_*` (covers `WIFISCOPE_LANG`, `WIFISCOPE_HELPER`, `WIFISCOPE_INVENTORY`, `WIFISCOPE_GATEWAY`, `WIFISCOPE_WAN`, `WIFISCOPE_SCAN_INTERVAL`, `WIFISCOPE_LATENCY_WAN_TARGET`)
- **Python package**: `src/wifiscope/` → `src/diting/`; `pyproject.toml` package name + console-script entry point
- **Default JSONL log filename pattern**: `wifiscope-<ts>.jsonl` → `diting-<ts>.jsonl` (and the `.gitignore` pattern that hides them per session)
- **Tagline (locked)**:
    - EN: "Your Mac hears more than it tells you."
    - ZH: "你的 Mac 听见了什么，告诉你。"
- **Docs**: README, DEVELOPMENT, CHANGELOG, TESTING, workflow, HELPER (EN + ZH each); every reference to `wifiscope` in user-facing prose updates. The 15 capability specs get a pass for in-Requirement string updates.
- **GitHub repo**: `chenchaoyi/wifiscope` → `chenchaoyi/diting` (GitHub auto-redirects old URLs)
- **NOT changing** — by design, **no behaviour change**:
    - Class / module identifiers like `WiFiBackend`, `WiFiPoller`, `MacOSWiFiBackend` (these describe the *Wi-Fi capability*, not the app, and the future Linux backend would be `LinuxWiFiBackend`)
    - The 15 capability spec names themselves (`wifi-scanning`, `bluetooth-scanning`, etc.) — these describe *what wifiscope does*, not what wifiscope is called
    - Git history; commits before this change still reference `wifiscope` and stay that way. CHANGELOG records the rename point.
- **BREAKING (intentional)**: anyone with an existing helper grant has to re-grant when the bundle ID changes (cdhash anchors TCC). Acceptable: the tool isn't yet released, so the only affected user is the maintainer.

## Capabilities

### New Capabilities

None. This is a structural rename — no new behaviour is introduced.

### Modified Capabilities

The following specs cite the old name inside Requirement text or scenario commands; their Requirements need delta updates:

- `cli`: every Requirement references `wifiscope` as the binary name and `WIFISCOPE_*` as the env-var prefix; default `--log` filename pattern changes too
- `macos-helper`: bundle path (`helper/wifiscope-helper.app`), helper binary name, and example `wifiscope-helper <subcommand>` invocations all change
- `i18n`: `WIFISCOPE_LANG` env var, plus example `wifiscope --lang …` invocations in scenarios
- `event-log`: Requirement "Both `--log` and `wifiscope monitor` SHALL produce byte-identical streams" mentions the binary name explicitly
- `analyze`: scenario `the user runs wifiscope analyze /tmp/wifi.jsonl` (one Requirement)
- `ble-decoders`: scenario references `src/wifiscope/decoders/foo.py` (path)
- `bluetooth-scanning`: scenario `the user runs wifiscope in a busy office`
- `environment-monitor`: scenarios reference `wifiscope calibrate`, `~/.wifiscope/calibration.json`
- `events`: scenarios reference `wifiscope monitor`, `wifiscope --lang zh --log`
- `inventory`: scenarios reference running `wifiscope`; one Requirement body cites `src/wifiscope/data/wifi_ouis.json` (path)
- `wifi-scanning`: Requirement body cites `helper/wifiscope-helper.app`; scenario references `wifiscope launches`
- `tui-shell`: Requirement body references the App class `WifiScopeApp.compose()` — renamed to `DitingApp` because the class IS the app

The remaining 3 specs (`ble-detail-modal`, `link-health`, `roam-detection`) reference `wifiscope` only in Purpose-section narrative; those get a non-Requirement text pass as a docs task in `tasks.md`, no delta spec needed.

## Impact

- **Code**: package directory rename + import paths; `pyproject.toml`; CLI entry point; helper bundle name + bundle ID; helper build script; env-var lookups in `src/diting/i18n.py` and call sites; `.gitignore` pattern for log files; default log-filename builder
- **Docs**: 7 EN docs + 7 ZH mirrors; every i18n string mentioning `wifiscope`
- **Specs**: 4 delta specs (`cli`, `macos-helper`, `i18n`, `event-log`); the rest covered by a docs task
- **External**:
    - GitHub repo rename (auto-redirect)
    - PyPI / Homebrew formula: not yet published, zero migration cost
    - Domains: `diting.app` / `diting.tools` registration is a separate user-side action (tracked in memory, not in this change)
- **TCC / installed users**: cdhash changes → re-grant Location Services + Bluetooth. Maintainer-only impact, project not yet shipped.
- **Search / discoverability**: 谛听 has competing products in the data-security space and one iOS messaging app; logo + tagline + the macOS-RF-tool positioning carry the brand differentiation.
