## ADDED Requirements

### Requirement: i18n catalogs SHALL provide EN ↔ ZH parity for the at-launch census summary strings
The `src/diting/i18n.py` catalogs SHALL provide ZH translations for every new EN key the at-launch census summary row introduces, preserving each `{placeholder}` from the EN source per the existing placeholder-preservation rule. The strings are short and factual; their ZH renderings keep the same meaning and a compact width.

| EN key | ZH value (normative) |
|---|---|
| `"session start"` | `"会话开始"` |
| `"{n} devices already present"` | `"已在场 {n} 个设备"` |
| `"  ×{n}"` | `"  ×{n}"` (reused if already present; vendor-count suffix stays language-neutral) |
| `" · …"` | `" · …"` (overflow marker, language-neutral) |
| `"enter to expand"` | `"回车展开"` |
| `"enter to collapse"` | `"回车收起"` |

The acronym-preservation rule already in this capability covers any product/brand vendor names (`Apple, Inc.`, `Microsoft`) that appear in the breakdown — vendor strings are data, not catalog keys, and pass through unchanged.

#### Scenario: ZH user sees the census summary in Chinese
- **WHEN** the user runs `DITING_LANG=zh diting`, the startup census folds 20 devices, and the user opens `EventsScreen`
- **THEN** the summary row renders `会话开始 · 已在场 20 个设备 (Apple, Inc. ×8 · Microsoft ×5 · …)` with the expand hint `回车展开`

#### Scenario: Placeholder count is preserved across locales
- **WHEN** the ZH value for `"{n} devices already present"` is resolved with `n=20`
- **THEN** the rendered string contains `20` exactly once — the `{n}` placeholder is preserved, not dropped or duplicated

#### Scenario: Missing ZH translation falls back to EN
- **WHEN** a census-summary key is absent from the ZH catalog mid-development
- **THEN** the key falls back to its EN source per the existing `t()` fallback contract; the summary row still renders, with that fragment in English
