# for-llm-raw

## Why

The `--for-llm` briefing is a deliberate distillation (stable-identity
population, dwell percentiles, rhythm) — great input for "interpret this", but
lossy: per-event timestamps, exact RSSI sequences, the precise order of events
at a moment of interest are gone. For a forensic / deep-dive ("what exactly
happened at 03:14?", "trace this one device"), the raw event log matters and
the briefing can't answer.

## What Changes

- **`--for-llm --raw`** tells the user to *also* hand the raw JSONL to the AI.
  It references the **existing input log file(s) directly** — no rewrite, no
  duplication — and the post-write guidance lists their paths: "drag the
  briefing + this log into your AI chat." The big file is attached, not pasted
  (the briefing still goes to the clipboard).
- **The prompt adapts.** When `--raw` is set the analyst prompt gains a line
  telling the model a raw JSONL log is attached — use it to verify the summary
  and investigate specifics, but trust the briefing's stable-identity figures
  for population (raw ids over-count).
- **`--raw --anonymize`** is the *only* case that writes a file: the original
  has real identifiers, so diting writes a scrubbed `diting-raw-anonymized-
  <ts>.jsonl` (same handles as the briefing) and references that instead.

## Capabilities

### Modified Capabilities

- `analyze`: `--for-llm` SHALL accept `--raw` to also surface the raw event log
  for the AI, referencing the original file(s) unless `--anonymize` requires a
  scrubbed copy.

## Out of scope

- Embedding raw excerpts into the briefing (considered; the user chose
  attach-the-original-file).
- Changing the default (raw stays opt-in; the clipboard briefing is unchanged).

## Impact

- `src/diting/cli.py` — `--raw` parsing; `--for-llm` block references the input
  path(s) / writes a scrubbed copy under `--anonymize`; guidance lists files.
- `src/diting/analyze.py` — `build_llm_document` / `build_llm_prompt` gain a
  `raw_attached` flag; a raw-JSONL scrubber for `--anonymize`.
- `src/diting/i18n.py` — ZH for the raw guidance + prompt line.
- `tests/` + `tests/TESTING.md` (EN + ZH) + `README.md` / `docs/zh/README.md`.
