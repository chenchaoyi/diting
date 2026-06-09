# analyze delta — for-llm-raw

## ADDED Requirements

### Requirement: `--for-llm --raw` SHALL surface the raw event log alongside the briefing
The tool SHALL accept `--raw` with `--for-llm` (and `--raw` alone SHALL imply
`--for-llm`). With `--raw`, the briefing is written and copied to the clipboard
as usual, AND the post-write guidance SHALL direct the user to also attach the
raw JSONL event log to the AI chat. Without `--anonymize`, `--raw` SHALL
reference the **existing input log file(s)** by path and SHALL NOT rewrite or
copy them. The analyst prompt SHALL state that a raw log is attached and SHALL
instruct the model to use it for specifics while trusting the briefing's
stable-identity figures for population counts.

#### Scenario: --raw references the original log, no rewrite
- **WHEN** the user runs `diting analyze mylog.jsonl --for-llm --raw`
- **THEN** no copy of `mylog.jsonl` is written; the guidance lists `mylog.jsonl` as the file to attach alongside the briefing, and the prompt mentions the attached raw log

#### Scenario: --raw alone implies --for-llm
- **WHEN** the user runs `diting analyze mylog.jsonl --raw`
- **THEN** the briefing is produced (as if `--for-llm` were given) and the raw guidance is shown

### Requirement: `--raw --anonymize` SHALL write a scrubbed raw log instead of referencing the original
When both `--raw` and `--anonymize` are set, the tool SHALL NOT reference the
real input log (it carries real identifiers). It SHALL write one scrubbed
`diting-raw-anonymized-<ISO-8601-timestamp>.jsonl` in which the identifying
fields (SSID, BSSID, RFC1918 IP, hostname / Bonjour name, BLE identifier, LAN
MAC) are replaced with the same stable handles used in the briefing, and the
guidance SHALL reference that scrubbed file. Public IPs, vendor names,
event-type names, magnitudes, and timestamps SHALL pass through unchanged.

#### Scenario: anonymized raw is a scrubbed copy with matching handles
- **WHEN** the user runs `diting analyze mylog.jsonl --for-llm --raw --anonymize`
- **THEN** a `diting-raw-anonymized-<timestamp>.jsonl` is written whose events have BSSIDs / SSIDs / RFC1918 IPs / identifiers replaced by the same handles the briefing uses, the original log is NOT referenced, and a public IP like `1.1.1.1` is left verbatim
