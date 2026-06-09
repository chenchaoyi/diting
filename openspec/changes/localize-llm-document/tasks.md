# localize-llm-document — tasks

## 1. Test plan first

- [x] 1.1 TESTING.md row (EN) — zh document is Chinese (prompt + headers +
      glossary), "respond in Chinese" present, tokens verbatim, EN unchanged
- [x] 1.2 Mirror in docs/zh/TESTING.md
- [x] 1.3 Tests: `build_llm_prompt` zh; `render_markdown` zh headers/glossary;
      tokens verbatim; EN path unchanged

## 2. Implement

- [x] 2.1 `build_llm_prompt` lang-branch: full ZH template + "respond in Chinese"
- [x] 2.2 `render_markdown` headers / table headers via `t()` (+ ZH catalog)
- [x] 2.3 glossary + anonymization appendix lang-branch (EN/ZH)
- [x] 2.4 localize `scene_summary` / `scene_llm_context_paragraph` / duration
      helper strings that feed the document (where still English)

## 3. Docs

- [x] 3.1 README.md + docs/zh/README.md — note the document follows `--lang`

## 4. Verify

- [x] 4.1 `uv run pytest` (incl. the i18n audit guard)
- [x] 4.2 run `--lang zh --for-llm` → prompt + report Chinese, tokens verbatim
- [x] 4.3 `tui_snapshot --mode regression`
- [x] 4.4 `openspec validate --specs --strict` + the change
