# i18n — delta

## MODIFIED Requirements

### Requirement: Column-aligned widgets SHALL use `pad_cells` / `fit_cells`, NEVER `str.ljust`
Widgets that align tabular columns SHALL pad / truncate with
`pad_cells(text, target)` and `fit_cells(text, target)` from
`i18n.py`, NEVER `str.ljust(target)` / `str` slicing — those count
codepoints, not cells, and CJK glyphs occupy two terminal cells per
single Python `str` codepoint, which produces visibly broken
alignment in ZH.

`fit_cells` SHALL accept an `ellipsis=True` keyword: when the text
overflows the target, it truncates one cell short and appends `…` so the
truncation is visible instead of reading like a real (shorter) value
(`Device Information` → `Device Informati…`, never `Device Informati`).
The output stays exactly `target` cells and never splits a wide glyph.
Columns that render free-form names or service labels (BLE name /
services, mDNS name / services, vendor cells) SHALL use the ellipsis form.

#### Scenario: ZH "now" label in a 6-cell column
- **WHEN** code aligns the "last seen" column with `pad_cells(t("now"), 6)` and ZH `"now"` is `"刚刚"` (4 cells)
- **THEN** the cell renders `刚刚  ` (2 trailing spaces) — total 6 cells, columns align
- **AND** `str.ljust(6)` would have produced 4 trailing spaces (codepoint count) → 8 cells, column breaks

#### Scenario: Overflowing label truncates visibly
- **WHEN** `fit_cells("Device Information", 16, ellipsis=True)` renders a services cell
- **THEN** the cell reads `Device Informat…` — exactly 16 cells with a visible truncation mark

#### Scenario: Fitting text gains no ellipsis
- **WHEN** the text already fits within the target
- **THEN** the output is identical to the non-ellipsis form (padded, no `…`)
