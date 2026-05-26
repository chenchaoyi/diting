## ADDED Requirements

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
