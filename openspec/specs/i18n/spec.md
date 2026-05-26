# i18n Specification

## Purpose

Defines diting's bilingual (EN / ZH) UI invariants — how strings
flow through `t()`, why every column-aligned widget uses
`pad_cells` / `fit_cells` instead of `str.ljust`, how the language
gets resolved at startup, and the locale-stable-keys-vs-translated-
values split between user-facing UI and machine-readable JSONL.
## Requirements
### Requirement: The active language SHALL be resolved exactly once per process
`resolve_lang(cli_override, env)` SHALL run at process start and
SHALL pick the first hit from this order:

1. `--lang en|zh` CLI flag
2. `DITING_LANG=en|zh` environment variable
3. System locale (`LC_ALL` / `LC_MESSAGES` / `LANG`) starting with
   `zh_*` → `zh`
4. English fallback

The result SHALL be set via `set_lang(...)` exactly once, before any
TUI widget is constructed. Mid-session language switch is NOT
supported — CJK character widths affect column-aligned layouts and
re-laying-out the whole TUI mid-session is more risk than value.

#### Scenario: User on a Chinese macOS without explicit env / flag
- **WHEN** they run `diting` with `LANG=zh_CN.UTF-8`
- **THEN** the UI renders in Chinese; `t()` looks up against the ZH catalog

#### Scenario: User overrides via flag
- **WHEN** they run `diting --lang en` on a Chinese system
- **THEN** the UI renders in English regardless of `LANG`

### Requirement: User-facing strings SHALL go through `t()`, NOT be hardcoded
Every string the user sees in the TUI SHALL be passed through the
`t(en, **kwargs) -> str` helper. The English source string is itself
the catalog key; the ZH catalog (`_ZH` dict in `i18n.py`) maps the
EN key to its translation. A missing key SHALL fall back to the EN
source so the UI never goes blank if translation lags code.

#### Scenario: New string added to a panel
- **WHEN** a contributor adds `Static(t("Some new label"))` and forgets the ZH translation
- **THEN** ZH users see "Some new label" (English fallback) — the UI keeps working, the missing translation is a polish item not a regression

#### Scenario: String with placeholder
- **WHEN** code calls `t("{n} BSSIDs", n=42)` and the ZH catalog has `{n} 个 BSSID`
- **THEN** ZH renders `42 个 BSSID`, EN renders `42 BSSIDs`

### Requirement: Column-aligned widgets SHALL use `pad_cells` / `fit_cells`, NEVER `str.ljust`
Widgets that align tabular columns SHALL pad / truncate with
`pad_cells(text, target)` and `fit_cells(text, target)` from
`i18n.py`, NEVER `str.ljust(target)` / `str` slicing — those count
codepoints, not cells, and CJK glyphs occupy two terminal cells per
single Python `str` codepoint, which produces visibly broken
alignment in ZH.

#### Scenario: ZH "now" label in a 6-cell column
- **WHEN** code aligns the "last seen" column with `pad_cells(t("now"), 6)` and ZH `"now"` is `"刚刚"` (4 cells)
- **THEN** the cell renders `刚刚  ` (2 trailing spaces) — total 6 cells, columns align
- **AND** `str.ljust(6)` would have produced 4 trailing spaces (codepoint count) → 8 cells, column breaks

### Requirement: JSONL log keys SHALL stay English regardless of UI language
The `event-log` JSONL writer SHALL emit English JSON keys (`type`,
`bssid`, `state`, etc.) even when `DITING_LANG=zh`. User-supplied
strings (SSID, AP location names from aps.yaml) SHALL pass through
unchanged with `ensure_ascii=False`. This way log analysis scripts
are robust to language toggle and a Chinese SSID like `咖啡馆`
survives readable.

#### Scenario: ZH user, Chinese SSID, JSONL log
- **WHEN** `DITING_LANG=zh diting --log /tmp/wifi.jsonl` is running, roam from `咖啡馆` to `Office`
- **THEN** the log line is `{"type":"roam","previous_ssid":"咖啡馆","new_ssid":"Office", ...}` — English keys, raw-UTF8 user values

### Requirement: Acronyms SHALL stay English in the ZH catalog
The following acronyms SHALL appear as English in the ZH catalog,
NOT translated: SSID, BSSID, RSSI, dBm, SNR, WPA2, OPEN, ENT, PHY,
MCS, NSS, Tx, Max. Translating them creates needless column-width
growth and reads less naturally to Chinese network engineers
(documented at the top of `_ZH` in `i18n.py`).

#### Scenario: ZH catalog entry for a column header
- **WHEN** the EN catalog has key `"BSSID"`
- **THEN** the ZH value is `"BSSID"` (unchanged), NOT a Chinese transliteration

### Requirement: Catalog entries SHALL preserve every `{placeholder}` from the EN source
Every key in the ZH catalog with `{placeholder}` syntax SHALL keep
the same placeholder name in the ZH value. `t()` does
`.format(**kwargs)` AFTER lookup, so a renamed or omitted placeholder
in the ZH side raises `KeyError` at render time. Tests cover the
catalog parity.

#### Scenario: EN key with `{n}` placeholder
- **WHEN** EN is `"{n} BSSIDs"` and ZH is `"{n} 个 BSSID"`
- **THEN** both render correctly with `t("{n} BSSIDs", n=42)`; if ZH had `"{count} 个 BSSID"` it would crash on the next render

### Requirement: i18n catalogs SHALL provide EN ↔ ZH parity for all new LAN-identification surface strings
For every new English string introduced by the `expand-lan-identification` change, the ZH catalog in `src/diting/i18n.py` SHALL ship a corresponding Chinese translation. The strings include, at minimum:

| EN key | ZH value (illustrative) |
|---|---|
| `class` (column header) | `分类` |
| `[new]` (chip) | `[新]` |
| `[probing]` (subtitle chip) | `[探测中]` |
| `Active discovery` (modal section header) | `主动探测` |
| `NBNS` (modal label) | `NBNS` |
| `UPnP server` (modal label) | `UPnP 标识` |
| `Friendly name` (modal label) | `友好名称` |
| `Model` (modal label) | `型号` |
| `TTL` (modal label) | `TTL` |
| `Class:` (modal label, identity section) | `分类：` |
| `Vendor (IEEE)` (modal continuation label) | `厂商（IEEE 注册名）` |
| `(not probed)` (modal placeholder) | `（未主动探测）` |
| `phone` (class value) | `手机` |
| `tablet` (class value) | `平板` |
| `laptop` (class value) | `笔记本` |
| `desktop` (class value) | `台式机` |
| `tv` (class value) | `电视` |
| `camera` (class value) | `摄像头` |
| `smart-home` (class value) | `智能家居` |
| `printer` (class value) | `打印机` |
| `nas` (class value) | `NAS` |
| `gaming` (class value) | `游戏机` |
| `speaker` (class value) | `音箱` |
| `router` (class value) | `路由器` |
| `Model:` (modal label, identity section) | `型号：` |
| `Active LAN probing` (modal title) | `LAN 主动探测` |
| `Scene:` (modal label) | `场景：` |
| `Network:` (modal label) | `网络：` |
| `(disassociated)` (modal value) | `（未连接 Wi-Fi）` |
| `One-shot probe. Re-confirm next time.` | `单次探测。下次还需重新确认。` |
| `esc cancel` (modal footer) | `esc 取消` |
| `wait 2s` (modal footer cooldown) | `等待 2 秒` |
| `y probe now` (modal footer) | `y 立即探测` |

The user-facing consequences paragraph in the probe consent modal SHALL be a single key whose ZH translation conveys the same three risk points (other guests' devices receive probes; IDS may flag; captive portal may rate-limit).

The class-value strings (`phone`, `laptop`, etc.) SHALL be passed through `t()` at the call site so the row + modal both pick up ZH translations when `DITING_LANG=zh`.

#### Scenario: ZH user sees translated chip
- **WHEN** `DITING_LANG=zh` is set and a LAN row was first seen 2 hours ago
- **THEN** the row line starts with `[新]` (not `[new]`)

#### Scenario: ZH user opens probe consent modal
- **WHEN** `DITING_LANG=zh` is set and the user presses `P` in public scene
- **THEN** the modal title reads `LAN 主动探测`; the body uses the ZH strings; the footer reads `[esc 取消]   [等待 2 秒]` during cooldown and `[esc 取消]   [y 立即探测]` after

#### Scenario: ZH user sees translated device class
- **WHEN** `DITING_LANG=zh` is set and a host's `device_class="tv"`
- **THEN** the LAN row's class column renders `电视`; the detail modal's `分类：` row renders `电视`

#### Scenario: EN user sees raw English labels
- **WHEN** `DITING_LANG=en` (default) and a host has `device_class="tv"`
- **THEN** the LAN row's class column renders `tv`; the detail modal renders `Class: tv`


### Requirement: ZH catalog SHALL close the copy gaps surfaced by the 2026-05-25 ZH-locale `/tui-audit` pass
The ZH catalog in `src/diting/i18n.py` SHALL provide a translation for the public-scene LAN-probe help-modal line, SHALL stop self-mapping the Bonjour `service` sort token, SHALL translate the `Noise / SNR` glossary heading, SHALL preserve the leading space on the bare `" ago"` time-ago key, SHALL stop translating Apple Continuity protocol names (Apple Companion, Apple Nearby Info) with culturally-misleading Chinese ("配对" / "邻近"), and SHALL render the BLE detail Activity ad-interval hint with idiomatic value-last word order.

Concretely, the following catalog rows are normative for the 1.7.2 release:

| EN key | ZH value (normative) | Failure mode without the fix |
|---|---|---|
| `"LAN view, public scene only: open consent modal for a one-shot active probe (NBNS / SSDP / mDNS) — see below"` | `"LAN 视图（仅公共场景）：打开一次性主动探测（NBNS / SSDP / mDNS）的同意弹窗 —— 详见下方"` | Help modal mid-section reads raw English in the ZH UI |
| `"service"` (Bonjour sort-mode token) | `"服务"` | Bonjour panel renders `排序：service` |
| `"Noise / SNR"` (basics-modal section heading) | `"Noise / 信噪比"` | Glossary section heading sits in English while every peer is translated |
| `" ago"` (bare time-ago key) | `" 前"` (leading-space preserved) | `8s前` (no space) collides with `5s 前扫描` (space) on the same screen |
| `"Apple Companion"` (Bonjour service category) | `"Apple Companion"` (brand verbatim, NOT `Apple 配对`) | `配对` reads as Bluetooth pairing in Chinese — wrong mental model for Continuity handoff |
| `"Apple Nearby"` (BLE category) | `"Apple Nearby"` (brand verbatim, NOT `Apple 邻近`) | Half-translated incomplete adjective phrase |
| `"~{n} ms between ads"` (BLE detail Activity hint) | `"广告间隔约 {n} ms"` | EN word order preserved in ZH reads `(~1772 ms 两次广播间隔)` — value before noun |

The catalog SHALL NOT introduce new self-maps (where the ZH value equals the EN key) except for bare brand strings or protocol acronyms that the existing "Acronyms SHALL stay English in the ZH catalog" requirement already covers (e.g. `BSSID`, `NBNS`, `UPnP`).

#### Scenario: User runs `DITING_LANG=zh diting` and opens the help modal
- **WHEN** the help modal (`h`) renders the keybindings section
- **THEN** the shift-P / public-scene line reads in Chinese end-to-end; no raw English row leaks through

#### Scenario: User runs `DITING_LANG=zh diting` and cycles to the Bonjour panel
- **WHEN** the panel sorts by service-category
- **THEN** the border subtitle renders `附近 Bonjour 设备 (N)  ·  排序：服务` (the sort-mode token is translated)

#### Scenario: User runs `DITING_LANG=zh diting` and opens the basics modal
- **WHEN** the modal renders the `Noise / SNR` section
- **THEN** the heading reads `Noise / 信噪比`; the body underneath continues to translate fully

#### Scenario: User runs `DITING_LANG=zh diting` and reads a relative-time field
- **WHEN** the LAN diagnostics row, the LAN detail `可达` row, the BLE detail `首次见到 / 最近见到` rows, or any other site that concatenates `_format_duration_short(ago) + t(" ago")` renders
- **THEN** the value reads `8s 前` (with leading space), consistent with `"  · {n}s ago"` and `"  · scanned {n}s ago"` templates that already preserve the space

#### Scenario: User runs `DITING_LANG=zh diting` and opens the Bonjour panel against an Apple Continuity host
- **WHEN** a service categorised as `Apple Companion` appears in the top-services row OR in the Bonjour list's category column
- **THEN** the cell reads `Apple Companion` (brand string verbatim); the misleading `配对` translation SHALL NOT appear

#### Scenario: User runs `DITING_LANG=zh diting` and opens the BLE detail modal on an Apple device
- **WHEN** the Categories diagnostic row would have read `Apple Nearby` in EN
- **THEN** the ZH render also reads `Apple Nearby` (brand string verbatim); `Apple 邻近` SHALL NOT appear

#### Scenario: User runs `DITING_LANG=zh diting` and opens the BLE detail modal on an active advertiser
- **WHEN** the Activity section renders the ad-count row with ≥ 2 ads over a non-zero span
- **THEN** the parenthesised hint reads `（广告间隔约 1772 ms）` (or whatever computed value) — value last, noun first

### Requirement: ZH catalog SHALL provide translations for the three startup-splash status labels
The ZH catalog in `src/diting/i18n.py` SHALL provide translations for the three status-line labels the `startup-splash` change introduces. The labels are short, factual strings; their ZH renderings keep the same factual meaning and the same compact width.

| EN key | ZH value (normative) |
|---|---|
| `"helper located"` | `"已找到 helper"` |
| `"checking Location Services"` | `"检查 Location Services"` |
| `"checking Bluetooth"` | `"检查 Bluetooth"` |

The acronym-preservation rule already in this capability already covers `Location Services` and `Bluetooth` — both are macOS-product brand strings that stay English in the ZH catalog by existing convention; the change only translates the verb / adjective wrappers.

#### Scenario: User on a Chinese system launches `diting`
- **WHEN** the user runs `DITING_LANG=zh diting`
- **THEN** the startup splash's three status lines render as `已找到 helper`, `检查 Location Services`, `检查 Bluetooth`

#### Scenario: Missing translation falls back to EN
- **WHEN** the ZH catalog is missing one of the three keys (e.g. mid-development before translations land)
- **THEN** the missing key SHALL fall back to the EN source per the existing `t()` fallback contract; the splash still renders, just with one row in English

#### Scenario: Acronym stays English
- **WHEN** the ZH catalog renders `"checking Location Services"`
- **THEN** the literal substring `Location Services` SHALL be preserved verbatim in the ZH value — matching how `BSSID`, `NBNS`, `UPnP`, `Apple Companion` are already handled
