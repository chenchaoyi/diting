# simplify-llm-bundle

## Why

`analyze --for-llm` writes a two-file bundle (`report.md` + `prompt.txt`),
so the user's workflow is: copy `prompt.txt`, drag-drop `report.md`, then
paste — three actions across two artifacts. That's too much friction for
"hand this to an LLM". It also hard-codes only `claude.ai` / `chat.openai.com`
in the guidance, which reads as an endorsement of two providers and omits
DeepSeek, Gemini, and the rest.

## What Changes

- **One self-contained file, not two.** `--for-llm` writes a single
  `diting-analysis-for-llm.md` — the analyst prompt followed by the full
  report inline — so the LLM gets instructions + data in one paste / one
  attach. The two-file `report.md` + `prompt.txt` split is removed.
- **Clipboard by default.** `--for-llm` copies that combined content to the
  macOS clipboard automatically (no new flag) — the workflow becomes *run →
  ⌘V into any AI chat*. The file is still written as an archive.
- **Provider-neutral guidance.** The post-write copy points at *any* capable
  AI chat and lists a few with URLs (Claude, ChatGPT, DeepSeek, Gemini, Kimi)
  framed as examples, not the only options.

## Capabilities

### Modified Capabilities

- `analyze`: `--for-llm` SHALL write a single combined Markdown file and copy
  it to the clipboard by default; the guidance SHALL be provider-neutral.

## Out of scope

- A `--copy` flag (clipboard is the default, not opt-in).
- Non-macOS clipboard backends (diting is macOS-only; degrade gracefully if
  `pbcopy` is unavailable).

## Impact

- `src/diting/cli.py` — `_run_analyze` `--for-llm` block (single file +
  clipboard + guidance); `-o` now names the output file or directory.
- `src/diting/analyze.py` — a combined-document builder (prompt + report).
- `src/diting/i18n.py` — EN + ZH for the new single-file guidance.
- `tests/` — the two-file tests become single-file; a clipboard test; the
  i18n audit guard already enforces ZH parity. `tests/TESTING.md` + ZH first.
- `README.md` + `docs/zh/README.md` — the analyze / for-llm sections.
