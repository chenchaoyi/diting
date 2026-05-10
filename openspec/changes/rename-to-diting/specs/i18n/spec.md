## MODIFIED Requirements

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
