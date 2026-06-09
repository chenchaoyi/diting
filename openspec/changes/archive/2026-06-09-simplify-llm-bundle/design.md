# simplify-llm-bundle — design

## Decisions

- **Single file `diting-analysis-for-llm.md`.** Self-explanatory name (it's
  diting's analysis, prepared for an LLM) — not `bundle.md`. Content is the
  analyst prompt, a `---` rule, then the full Markdown report (the same
  `render_markdown` output, glossary and all). One paste gives the LLM both
  the instructions and the data. The old `report.md` + `prompt.txt` pair is
  dropped — a combined doc is what removes the copy/drag/paste dance.
- **`-o` names the output location, file or directory.** Default
  `./diting-analysis-for-llm-<ISO-timestamp>.md` in cwd. If `-o` ends in
  `.md`, it's the exact output file; otherwise it's a directory the file lands
  inside (with the default name). An `-o` that exists as a non-`.md` *file*
  is a usage error (exit 2), as before. No timestamped *directory* anymore —
  one file, optionally timestamped.
- **Clipboard by default via `pbcopy`.** A `_copy_to_clipboard(text) -> bool`
  helper shells out to `pbcopy`; on success the guidance says "copied to
  clipboard". It is injectable so tests don't touch the real clipboard, and
  failure (no `pbcopy`, non-macOS) degrades silently — the file is still the
  fallback. The clipboard gets the *anonymized* content when `--anonymize` is
  set; the handle↔original mapping is still printed to the terminal only,
  never copied — so clipboard-by-default never leaks the mapping.
- **Provider-neutral guidance.** "paste into any AI chat (it has the prompt +
  the data)" followed by a short example list with URLs. Brand URLs stay
  verbatim; surrounding prose follows `--lang`. The `--anonymize` nudge and
  the mapping print are unchanged.
- **`--json` unaffected.** `--for-llm --json` still emits the report JSON to
  stdout; the clipboard copy + file write + guidance go to stderr/side-effects
  (an agent run shouldn't hijack the human's clipboard — skip the copy when
  `--json` is set).

## Risks / Trade-offs

- [Clipboard-by-default surprises the user] → it's announced ("✓ copied to
  clipboard") and is exactly what was requested; the written file is the
  durable artifact.
- [Dropping report.md/prompt.txt breaks a script] → this is a deliberate UX
  simplification; the combined file carries everything, and the spec scenarios
  update to the single file. The README documents the new name.
- [pbcopy missing in CI] → the helper is injectable and failure is silent, so
  tests assert on the helper call, not the real clipboard.
