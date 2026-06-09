# localize-llm-document — design

## Decisions

- **Prompt: lang-branch, not `t()`-per-sentence.** `build_llm_prompt` is one
  cohesive instruction paragraph with interpolations. Wrapping each sentence in
  `t()` would be brittle. Instead it branches on `i18n.get_lang()` and returns a
  full EN or ZH template (with `{span}` / `{files}` / scene paragraph
  substituted). The ZH template ends with an explicit "用中文输出你的分析"
  (respond in Chinese) line — this is the lever that yields a Chinese answer
  even where the report data is technical.
- **Report Markdown: `t()` the short headers, lang-branch the glossary.**
  `render_markdown`'s section headers (`## Total events by type`, table column
  headers, `## Glossary`, etc.) go through `t()` with ZH catalog entries — short,
  reusable, and the i18n audit guard enforces parity. The glossary is one large
  prose block, so it lang-branches like the prompt. The Anonymization appendix
  prose lang-branches too.
- **Technical tokens stay verbatim.** Event-type names (`ble_device_seen`,
  `rf_stir`, `roam`), BSSIDs, vendor strings, and JSONL field names are NOT
  translated — they're identifiers the glossary maps, and the consuming model
  needs them to line up with the data rows. Only the surrounding prose / headers
  localize.
- **Insights already localized.** `report.insights[*].title/detail/todo` are
  generated through `t()` at analysis time, so `render_markdown` rendering them
  verbatim already yields Chinese under `zh`. No change there.
- **Scope of "follows --lang".** This is the human-facing LLM document, so it
  follows `--lang` like the terminal report. It is distinct from `--json`
  (machine-facing, keys stay English).

## Risks / Trade-offs

- [Bilingual templates can drift] → the prompt + glossary are bounded blocks
  with a single EN/ZH branch each, and a test asserts the zh document is Chinese
  + carries the "respond in Chinese" line, so drift surfaces in CI.
- [Mixed Chinese prose + English tokens reads oddly] → intentional and correct:
  the tokens are the data's vocabulary; translating them would break the
  glossary mapping and the model's ability to cite specific events.
