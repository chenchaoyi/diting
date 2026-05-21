## Why

A2 (#103) shipped the cross-session aggregations users wanted —
hour-of-day, day×hour heatmap, per-network ranking, daily trend,
top contributors. The output is already meaningfully helpful at
the terminal.

Track B asks: how do we make those same aggregates a 30-second
input to ChatGPT or Claude so a busy user gets richer
interpretation (pattern clustering, hypothesis ranking, follow-up
investigations) without leaving their workflow?

The user explicitly chose against a built-in `--ai` mode with an
embedded API key (the maigret pattern). What they wanted instead:

- A Markdown report a user can drag into chat.openai.com or
  claude.ai
- A pre-written analyst prompt the user pastes alongside
- Clear terminal-side guidance copy so the workflow feels smooth
- An opt-in anonymizer (`--anonymize`) so a user can scrub
  SSIDs / BSSIDs / IPs / hostnames before pasting into a public
  LLM (corporate-network use)

That bundle becomes the LLM bridge. No network calls from diting,
no API key, no external dependency.

## What Changes

### `analyze`

- **MODIFIED:** `diting analyze` SHALL accept a new `--for-llm
  [outdir]` flag. When set, the CLI writes two files to `outdir`
  (default `./diting-llm-<timestamp>/`):
  - `report.md` — Markdown rendition of the same data the
    terminal report produces (Scope, per-file timelines, all
    A2 cross-session blocks, all per-session heuristic insights),
    plus a glossary block defining diting-specific terms (`stir`,
    `co_located` / `spatial_channel`, `roam` vs `band_switch`,
    `bonjour_service_seen` etc.) so the LLM doesn't have to
    guess.
  - `prompt.txt` — the analyst prompt the user pastes alongside
    the report. Five sections: role, what the data is, what to
    do (extract patterns, rank by likelihood, suggest follow-up
    investigations), output format (markdown), and a hard
    "don't speculate beyond data" guardrail.
- **MODIFIED:** the CLI's terminal output SHALL guide the user
  through the paste workflow:
  ```
  ✓ wrote diting-llm-report-<ts>.md   (NN KB)
  ✓ wrote diting-llm-prompt-<ts>.txt  (M KB)

  to analyze with an LLM:
    1. open https://claude.ai or chat.openai.com
    2. drag-drop the .md file into the chat
    3. paste the contents of prompt.txt
    4. submit
  ```
- **ADDED:** `--anonymize` flag SHALL strip / replace
  privacy-sensitive identifiers before writing the bundle. When
  set:
  - SSIDs SHALL be replaced with stable handles `SSID_1`, `SSID_2`, …
  - BSSIDs SHALL be replaced with `AP_1`, `AP_2`, … (first-seen
    order).
  - LAN IPs (RFC1918 only — public IPs survive) SHALL be replaced
    with `IP_1`, `IP_2`, …
  - Hostnames (Bonjour names, reverse-DNS values) SHALL be
    replaced with `HOST_1`, `HOST_2`, …
  - BLE identifiers SHALL be replaced with `BLE_1`, `BLE_2`, …
    (privacy-sensitive in dense environments).
  - Vendor names SHALL pass through unchanged — they're
    population-level information.
  Default is OFF; users on private networks keep the verbatim
  identifiers (LLM output is more specific when given the real
  names).
- **ADDED:** the anonymizer SHALL produce STABLE handles across
  the run: the SAME `SSID_1` refers to the same SSID everywhere
  in the report. This lets the user explain what each handle
  is when reading the LLM's response.
- **ADDED:** the `report.md` SHALL include an `## Anonymization`
  appendix when `--anonymize` is active, listing the mapping
  `SSID_1 ↔ <original>` so the user can decode the LLM's
  references back to real names without leaking the mapping
  into the chat.

## Out of Scope

- Built-in OpenAI / Anthropic API client (explicitly rejected
  earlier — maintain offline-only stance).
- Automatic upload to chat.openai.com / claude.ai (fragile login
  flows; the manual drag-drop UX is fine).
- Custom prompts beyond the bundled template — users can write
  their own once they paste the report.
- Schema-stable JSON export. The Markdown report is the
  LLM-facing surface; users wanting machine-readable output use
  the existing JSONL.
- Anonymization at JSONL write time (i.e. anonymizing the
  log file itself). The anonymizer here only runs on the
  `report.md` output; the JSONL stays verbatim. Anonymizing the
  log file would prevent the user from re-analyzing later.

## Migration / Defaults

`diting analyze` without `--for-llm` is unchanged — the existing
terminal output stays the bytes-stable rendering. Users opt in
by passing the flag.

`--for-llm` works with both single-file and multi-file inputs;
single-file callers without `--since` see a "single-session"
report.md without the cross-session blocks (matching the
terminal's append-only contract from A2).

Anonymization is OFF by default. Users on corporate networks who
want to paste into a public LLM should remember to add
`--anonymize`. The terminal output reminds them of the flag's
existence in the post-write guidance copy.

No new third-party dependency.
