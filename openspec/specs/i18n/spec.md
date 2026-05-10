# i18n Specification

## Purpose

Defines wifiscope's bilingual (EN / ZH) UI invariants — how strings
flow through `t()`, why every column-aligned widget uses
`pad_cells` / `fit_cells` instead of `str.ljust`, how the language
gets resolved at startup, and the locale-stable-keys-vs-translated-
values split between user-facing UI and machine-readable JSONL.

## Requirements

### Requirement: The active language SHALL be resolved exactly once per process
`resolve_lang(cli_override, env)` SHALL run at process start and
SHALL pick the first hit from this order:

1. `--lang en|zh` CLI flag
2. `WIFISCOPE_LANG=en|zh` environment variable
3. System locale (`LC_ALL` / `LC_MESSAGES` / `LANG`) starting with
   `zh_*` → `zh`
4. English fallback

The result SHALL be set via `set_lang(...)` exactly once, before any
TUI widget is constructed. Mid-session language switch is NOT
supported — CJK character widths affect column-aligned layouts and
re-laying-out the whole TUI mid-session is more risk than value.

#### Scenario: User on a Chinese macOS without explicit env / flag
- **WHEN** they run `wifiscope` with `LANG=zh_CN.UTF-8`
- **THEN** the UI renders in Chinese; `t()` looks up against the ZH catalog

#### Scenario: User overrides via flag
- **WHEN** they run `wifiscope --lang en` on a Chinese system
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
`bssid`, `state`, etc.) even when `WIFISCOPE_LANG=zh`. User-supplied
strings (SSID, AP location names from aps.yaml) SHALL pass through
unchanged with `ensure_ascii=False`. This way log analysis scripts
are robust to language toggle and a Chinese SSID like `咖啡馆`
survives readable.

#### Scenario: ZH user, Chinese SSID, JSONL log
- **WHEN** `WIFISCOPE_LANG=zh wifiscope --log /tmp/wifi.jsonl` is running, roam from `咖啡馆` to `Office`
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
