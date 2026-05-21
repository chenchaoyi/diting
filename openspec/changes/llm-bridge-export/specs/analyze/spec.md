## ADDED Requirements

### Requirement: `diting analyze` SHALL accept a `--for-llm` flag that writes a Markdown report + paste-ready prompt to a bundle directory
When `--for-llm [outdir]` is set on the analyze CLI, the tool SHALL write a two-file bundle to `outdir` (default `./diting-llm-<ISO-8601-timestamp>/`):

1. `report.md` — Markdown rendition of the same data the terminal report produces (Scope, per-file timelines, all A2 cross-session blocks, all per-session heuristic insights). The Markdown report SHALL:
   - Use fenced code blocks (` ```text `) for ASCII charts (hour-of-day bars, day×hour heatmap, daily-trend sparkline) so Markdown viewers don't try to interpret block characters as formatting.
   - Use Markdown tables for ranked / per-bucket data (per-network ranking, top contributors).
   - Include a `## Glossary` section defining diting-specific terms (`stir`, `co_located` vs `spatial_channel`, `roam` vs `band_switch`, the 7 new BLE / Bonjour / LAN transition event types, family names) so the LLM doesn't have to guess from context.

2. `prompt.txt` — a paste-ready analyst prompt. The template SHALL include five sections:
   - Role / data context line (string-substituted with `<span>` and `<files>` from the analyzed input).
   - Task list: identify top patterns; for each, name likely root cause + supporting evidence; suggest follow-up investigations; restate trends with explicit confidence tags; respect anonymization handles when present.
   - Output format instruction (markdown, conclusions-first, mark inferences as "hypothesis").
   - Guardrail line ("don't speculate beyond data").

#### Scenario: Multi-file `--for-llm` invocation writes the bundle
- **WHEN** the user runs `diting analyze diting-*.jsonl --since 30d --for-llm`
- **THEN** the tool writes `report.md` + `prompt.txt` to a new timestamped directory under the current working directory; both files exist and are non-empty

#### Scenario: `--for-llm` accepts an explicit outdir
- **WHEN** the user runs `diting analyze foo.jsonl --for-llm /tmp/my-analysis`
- **THEN** the bundle is written to `/tmp/my-analysis/report.md` and `/tmp/my-analysis/prompt.txt`; the timestamped default is NOT generated

#### Scenario: Report Markdown includes the glossary
- **WHEN** the bundle's `report.md` is opened
- **THEN** it contains a `## Glossary` section listing the diting-specific terms (`stir`, `roam`, `ble_device_seen`, etc.) so the consuming LLM has the vocabulary

#### Scenario: Prompt includes all five required sections
- **WHEN** `prompt.txt` is read
- **THEN** it contains: role line referencing diting + the analyzed span; numbered task list; output-format instruction; "don't speculate beyond data" guardrail; honour-anonymization clause when applicable

### Requirement: After writing the bundle the CLI SHALL print terminal-side guidance copy
After `--for-llm` succeeds, the CLI SHALL print a four-step instruction block to stdout:

```
to analyze with an LLM:
  1. open https://claude.ai or chat.openai.com
  2. drag-drop the report.md file into the chat
  3. paste the contents of prompt.txt
  4. submit
```

When `--anonymize` is NOT set, the guidance SHALL additionally include a one-line nudge mentioning the `--anonymize` flag for users pasting into a public LLM.

When `--anonymize` IS set, the guidance SHALL print the in-memory handle ↔ original mapping to stdout (and SHALL NOT write it into the bundle) so the user can decode the LLM's references later without leaking the mapping into a public chat.

#### Scenario: Default guidance includes the anonymize-hint
- **WHEN** the user runs `--for-llm` without `--anonymize`
- **THEN** the post-write stdout includes a hint like `(if you're pasting into a public LLM and want to scrub identifiers, re-run with --anonymize)`

#### Scenario: Anonymize-mode prints handle mapping to terminal only
- **WHEN** the user runs `--for-llm --anonymize`
- **THEN** the stdout prints the mapping `SSID_1 ↔ <original>` etc.; the bundle's `report.md` contains an `## Anonymization` placeholder section that points users back at their terminal output but does NOT itself contain the mapping

### Requirement: `--anonymize` SHALL replace privacy-sensitive identifiers with stable handles before writing the report
When `--anonymize` is set, the report-rendering pipeline SHALL replace the following with stable handles assigned in first-seen order:

| Kind | Handle prefix | What gets replaced |
|---|---|---|
| SSID | `SSID_1`, `SSID_2`, … | `event.ssid`, `event.previous_ssid`, `event.new_ssid` |
| BSSID | `AP_1`, `AP_2`, … | `event.bssid`, `event.new_bssid`, `event.previous_bssid` |
| LAN IP | `IP_1`, `IP_2`, … | `event.ip`, `event.new_ip`, `event.previous_ip`, `event.target_ip` — RFC1918 only |
| Hostname | `HOST_1`, `HOST_2`, … | `event.host`, `event.hostname`, `event.bonjour_name` |
| BLE identifier | `BLE_1`, `BLE_2`, … | `event.identifier` |
| LAN MAC | `MAC_1`, `MAC_2`, … | `event.mac` |

Public IPs (anything outside RFC1918) SHALL pass through unchanged — they're not identifying. Vendor names, service categories, event-type names, magnitudes (RTT, σ, loss %), timestamps, and aggregation counts SHALL pass through unchanged.

The handle assignment SHALL be deterministic given a fixed event ordering: re-running `--for-llm --anonymize` on the same input produces the same handles.

The JSONL log file SHALL NOT be modified by `--anonymize` — anonymization runs one-way at report-generation time so the source data stays available for future analysis.

#### Scenario: Same identifier maps to the same handle everywhere in the report
- **WHEN** the BSSID `aa:bb:cc:11:22:33` appears 30 times across roam / rf_stir / per-network blocks
- **THEN** every occurrence in `report.md` renders as `AP_1` (or whichever handle was assigned at first sight)

#### Scenario: Public IPs pass through unchanged
- **WHEN** a `latency_spike` event has `target_ip=1.1.1.1` (Cloudflare public DNS)
- **THEN** `report.md` renders `1.1.1.1` verbatim; the IP is not assigned a handle

#### Scenario: RFC1918 IPs get handles
- **WHEN** a `lan_host_seen` event has `ip=192.168.1.42`
- **THEN** `report.md` renders the address as `IP_1` (or the next available handle); the original mapping appears only in the terminal output

#### Scenario: Vendor and category names are not anonymized
- **WHEN** the report mentions an event with `vendor="Apple, Inc."` and `category="AirPlay"`
- **THEN** both strings appear verbatim in `report.md`; only identifying fields get handles

### Requirement: Anonymization mapping SHALL be surfaced to the terminal but NOT written into the report bundle
The `report.md`'s `## Anonymization` section SHALL be a placeholder that reads (paraphrased):

> Anonymization is active. Handle ↔ original mappings were printed to your terminal when this report was generated. Keep that mapping private — pasting it into a public LLM chat defeats the anonymization purpose.

The actual mapping table SHALL print to stdout at CLI-end. The user is responsible for storing it locally (e.g. piping CLI output to a private file) before sharing the bundle.

#### Scenario: Report doesn't leak the mapping
- **WHEN** `--for-llm --anonymize` runs on input that maps `home-5G` → `SSID_1`
- **THEN** `report.md` contains the string `SSID_1` but does NOT contain the string `home-5G`

#### Scenario: Terminal prints the mapping
- **WHEN** the same run completes
- **THEN** stdout contains a line like `SSID_1 ↔ home-5G` so the user can decode the LLM's output later
