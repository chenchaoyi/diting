# analyze delta — localize-llm-document

## ADDED Requirements

### Requirement: The `--for-llm` document SHALL render in the active UI language
The tool SHALL render the `--for-llm` document (the analyst prompt and the
Markdown report) in the active UI language. Under `--lang zh` the prompt SHALL be
Chinese and SHALL explicitly instruct the model to respond in Chinese; the
report's section headers, table column headers, prose lines, and glossary SHALL
be Chinese. Technical identifiers — event-type names (e.g. `ble_device_seen`),
BSSIDs, vendor strings, and JSONL field names — SHALL remain verbatim regardless
of language, since the glossary defines them and the model must line them up
with the data rows. The JSON output (`--json`) is unaffected and keeps
locale-stable English keys.

#### Scenario: Chinese prompt asks for a Chinese answer
- **WHEN** the user runs `diting analyze <log> --lang zh --for-llm`
- **THEN** the written file's analyst prompt is in Chinese and includes an explicit instruction to respond in Chinese

#### Scenario: Report headers and glossary are Chinese, tokens verbatim
- **WHEN** the zh document's report section is read
- **THEN** the section headers and glossary prose are Chinese, while event-type tokens like `ble_device_seen` and BSSIDs appear verbatim

#### Scenario: English locale is unchanged
- **WHEN** the user runs `--for-llm` under the default English locale
- **THEN** the prompt and report render in English exactly as before
