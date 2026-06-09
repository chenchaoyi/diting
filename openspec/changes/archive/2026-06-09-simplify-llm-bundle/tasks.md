# simplify-llm-bundle — tasks

## 1. Test plan first

- [x] 1.1 TESTING.md rows (EN) — single combined file, clipboard default,
      provider-neutral guidance, -o file-vs-dir
- [x] 1.2 Mirror in docs/zh/TESTING.md
- [x] 1.3 Rewrite the two-file tests to single-file; add a clipboard test
      (injected helper) + a `-o file.md` test

## 2. Implement

- [x] 2.1 `analyze.build_llm_document(report, anonymizer)` = prompt + report
- [x] 2.2 `cli._copy_to_clipboard(text) -> bool` (pbcopy, injectable, silent fail)
- [x] 2.3 `_run_analyze` `--for-llm`: one file `diting-analysis-for-llm-<ts>.md`,
      `-o` file-or-dir, clipboard by default, skip copy under `--json`
- [x] 2.4 provider-neutral guidance (Claude/ChatGPT/DeepSeek/Gemini/Kimi);
      EN + ZH i18n
- [x] 2.5 usage line + `analyze --help` reflect the single file + clipboard

## 3. Docs

- [x] 3.1 README.md + docs/zh/README.md — analyze / for-llm sections

## 4. Verify

- [x] 4.1 `uv run pytest` (incl. the i18n audit guard)
- [x] 4.2 run `--for-llm` → one file, clipboard has it, guidance neutral
- [x] 4.3 `tui_snapshot --mode regression`
- [x] 4.4 `openspec validate --specs --strict` + the change
