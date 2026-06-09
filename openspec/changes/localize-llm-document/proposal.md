# localize-llm-document

## Why

Under `--lang zh` the `--for-llm` document is still English: `build_llm_prompt`
is a constant English block and `render_markdown` emits English section headers
and an English glossary. So a Chinese user pastes an English prompt + report
into their AI chat and gets an English analysis back. If you run diting in
Chinese, the analysis you hand to an AI — and the answer you get — should be
Chinese.

## What Changes

- **The analyst prompt follows `--lang`.** Under `zh`, `build_llm_prompt`
  returns a Chinese prompt that *also* explicitly asks the model to respond in
  Chinese — the lever that makes the AI's analysis Chinese even where the data
  is technical.
- **The report Markdown follows `--lang`.** `render_markdown`'s structural
  headers, table column headers, prose lines, and the glossary localize under
  `zh`. Technical tokens stay verbatim — event-type names (`ble_device_seen`),
  BSSIDs, vendor names, field names — they're identifiers the glossary defines,
  not prose.
- The per-session insights are already localized (generated through `t()`), so
  they need no change.

## Capabilities

### Modified Capabilities

- `analyze`: the `--for-llm` document (prompt + report Markdown) SHALL render in
  the active UI language.

## Out of scope

- Translating technical identifiers / event-type tokens / vendor strings.
- The `--json` output (machine-facing; keys stay locale-stable English).

## Impact

- `src/diting/analyze.py` — `build_llm_prompt` (lang-branched ZH template +
  "respond in Chinese"); `render_markdown` headers/glossary; `scene_summary` /
  `scene_llm_context_paragraph` / duration helpers that feed them.
- `src/diting/i18n.py` — ZH for the markdown headers (the audit guard enforces
  parity).
- `tests/` — a zh-document test asserting the prompt + headers are Chinese and
  the "respond in Chinese" instruction is present; `tests/TESTING.md` + ZH first.
- `README.md` + `docs/zh/README.md` — note the document follows `--lang`.
