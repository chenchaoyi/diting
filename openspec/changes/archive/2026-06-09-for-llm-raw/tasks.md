# for-llm-raw — tasks

## 1. Test plan first

- [x] 1.1 TESTING.md rows (EN) — --raw references original (no rewrite),
      implies --for-llm, prompt mentions raw; --raw --anonymize writes scrubbed
- [x] 1.2 Mirror in docs/zh/TESTING.md
- [x] 1.3 Tests: --raw no rewrite + guidance path + prompt line; --raw implies
      --for-llm; --raw --anonymize writes scrubbed jsonl w/ matching handles +
      public IP verbatim

## 2. Implement

- [x] 2.1 `--raw` parse in `_run_analyze` (implies for_llm)
- [x] 2.2 `build_llm_prompt` / `build_llm_document` gain `raw_attached` flag +
      the raw instruction (EN + ZH)
- [x] 2.3 non-anonymize `--raw`: reference input path(s) in guidance
- [x] 2.4 `analyze.scrub_event(ev, anonymizer)` + write
      `diting-raw-anonymized-<ts>.jsonl` under `--raw --anonymize`
- [x] 2.5 guidance lists files to attach (EN + ZH); usage + `analyze --help`

## 3. Docs

- [x] 3.1 README.md + docs/zh/README.md — `--raw` in the for-llm section

## 4. Verify

- [x] 4.1 `uv run pytest` (incl. i18n audit guard)
- [x] 4.2 run `--for-llm --raw` (+ `--anonymize`) end-to-end
- [x] 4.3 `tui_snapshot --mode regression`
- [x] 4.4 `openspec validate --specs --strict` + the change
