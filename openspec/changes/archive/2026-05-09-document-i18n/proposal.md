# Document the `i18n` capability

## Why

The bilingual UI carries several non-obvious invariants that future
contributors keep tripping over:

- Column-aligned widgets break in ZH if you use `str.ljust` instead
  of `pad_cells` (CJK glyph cell-width). This bug landed twice
  before the convention got pinned.
- JSONL log keys must stay English even with `WIFISCOPE_LANG=zh`,
  because users build shell pipelines on `jq '.type=="roam"'` and
  those would silently match nothing if keys translated.
- Acronyms (SSID / BSSID / RSSI / etc.) intentionally stay
  unchanged in the ZH catalog — translating them is a footgun even
  though it looks correct. Documented in the catalog comments but
  not as a contract.

Backfill turns these into spec contracts so a future translation
PR can't quietly violate them.

## What Changes

- Introduce capability `i18n`.
- No code changes — backfill from `src/wifiscope/i18n.py`.

## Capabilities

### New Capabilities
- `i18n`: language resolution order, `t()` lookup contract,
  pad_cells / fit_cells column-alignment invariant, English
  JSONL keys vs translated UI strings split, acronym non-translation
  rule, placeholder parity rule.

### Modified Capabilities
None.

## Impact

- Affected code: none (documentation-only)
- Affected specs: creates `openspec/specs/i18n/spec.md`
- Cross-cuts with: every UI capability — `wifi-scanning`,
  `bluetooth-scanning`, `ble-detail-modal`, `tui-shell`,
  `event-log` all rely on these invariants
- Future impact: any change to language resolution order or
  acronym translation policy MUST file a MODIFIED Requirement
