## 1. Test plan (test-first)

- [x] 1.1 `tests/TESTING.md` (EN) — under `### analyze`, add rows for: `--for-llm` writes `report.md` + `prompt.txt`; report's glossary section; prompt's five required sections; `--anonymize` replaces SSIDs / BSSIDs / RFC1918 IPs / hostnames / BLE identifiers / MACs with stable handles; public IPs preserved; vendor / category passthrough; terminal-only mapping; report doesn't leak the mapping.
- [x] 1.2 `docs/zh/TESTING.md` — mirror.

## 2. Anonymizer

- [x] 2.1 `src/diting/analyze.py::Anonymizer` — a small class with `map(kind, value) -> handle` returning stable first-seen handles. Internal dicts keyed by kind. `mapping()` returns the flat dict for the terminal printout.
- [x] 2.2 `src/diting/analyze.py::_is_rfc1918(ip)` — small helper returning True for `10.0.0.0/8` / `172.16.0.0/12` / `192.168.0.0/16`.

## 3. Markdown report renderer

- [x] 3.1 `src/diting/analyze.py::render_markdown(report, *, anonymizer=None) -> str` — produces the Markdown report.
- [x] 3.2 Glossary block included unconditionally (LLM benefits from it whether or not the run is anonymized).
- [x] 3.3 Heatmap / hour-of-day / daily-trend rendered inside ` ```text ` fenced blocks.
- [x] 3.4 Per-network ranking + top-contributors rendered as Markdown tables.
- [x] 3.5 Anonymization-appendix placeholder when anonymizer is non-None.

## 4. Prompt-template generator

- [x] 4.1 `src/diting/analyze.py::build_llm_prompt(report) -> str` — substitutes `<span>` / `<files>` and returns the prompt body.

## 5. CLI plumbing

- [x] 5.1 `src/diting/cli.py::_run_analyze` — add `--for-llm [outdir]` and `--anonymize` flags (latter no value).
- [x] 5.2 On `--for-llm`, create outdir if absent, write `report.md` + `prompt.txt`, print byte sizes + four-step guidance.
- [x] 5.3 On `--anonymize`, print the mapping `handle ↔ original` to stdout after the bundle writes; the report's anonymization section stays a placeholder.
- [x] 5.4 When `--anonymize` is OFF, print the one-line nudge about the flag's existence.

## 6. Tests

- [x] 6.1 `tests/test_analyze.py` — anonymizer + render-markdown + prompt-template tests per design D7.
- [x] 6.2 `tests/test_cli.py` — `--for-llm` + `--anonymize` flag plumbing.

## 7. Docs

- [x] 7.1 `docs/explainers/llm-bridge.md` (new) — short user-facing doc on the workflow.
- [x] 7.2 `docs/zh/explainers/llm-bridge.md` — mirror.

## 8. CI gates

- [x] 8.1 `uv run pytest`
- [x] 8.2 `uv run python scripts/tui_snapshot.py --mode regression`
- [x] 8.3 `openspec validate --specs --strict`
- [x] 8.4 `openspec validate llm-bridge-export --strict`
