# analyze delta — simplify-llm-bundle

## MODIFIED Requirements

### Requirement: `diting analyze` SHALL accept a `--for-llm` flag that writes a Markdown report + paste-ready prompt to a bundle directory
When `--for-llm` is set on the analyze CLI, the tool SHALL write a **single
self-contained Markdown file** (default `./diting-analysis-for-llm-<ISO-8601-
timestamp>.md` in the current working directory) and SHALL copy that file's
content to the system clipboard by default. `-o` / `--out-dir` names the output
location: a value ending in `.md` is the exact output file; any other value is
a directory the file is written into under the default name. An `-o` value that
already exists as a non-directory, non-`.md` file SHALL be a usage error
(exit 2), not a crash.

The file SHALL contain, in order:

1. The paste-ready analyst prompt. The template SHALL include: a role / data
   context line (string-substituted with the analyzed span and files); a task
   list (identify top patterns; name likely root cause + supporting evidence;
   suggest follow-ups; restate trends with explicit confidence tags; respect
   anonymization handles when present); an output-format instruction
   (markdown, conclusions-first, mark inferences as "hypothesis"); and a
   "don't speculate beyond data" guardrail.
2. A separator, then the Markdown report — the same data the terminal report
   produces (Scope, per-file timelines, all cross-session blocks, all
   per-session heuristic insights). The Markdown report SHALL use fenced
   ` ```text ` blocks for ASCII charts, Markdown tables for ranked data, and
   include a `## Glossary` section defining diting-specific terms.

The clipboard SHALL receive the same (anonymized, when `--anonymize` is set)
content; failure to reach the clipboard (e.g. `pbcopy` unavailable) SHALL
degrade silently with the written file as the fallback.

#### Scenario: `--for-llm` writes one combined file
- **WHEN** the user runs `diting analyze diting-*.jsonl --since 30d --for-llm`
- **THEN** the tool writes one `diting-analysis-for-llm-<timestamp>.md` under the cwd that contains both the analyst prompt and the full report, and that single file is non-empty

#### Scenario: `--for-llm` copies the content to the clipboard by default
- **WHEN** `--for-llm` succeeds
- **THEN** the combined file content is placed on the system clipboard (no extra flag needed), so the user can paste it straight into an AI chat

#### Scenario: `-o` names a file or a directory
- **WHEN** the user runs `--for-llm -o /tmp/run.md` (or `-o /tmp/dir`)
- **THEN** the file is written to `/tmp/run.md` (or `/tmp/dir/diting-analysis-for-llm-<timestamp>.md`); the timestamped cwd default is NOT used

#### Scenario: Combined file includes the glossary and the prompt
- **WHEN** the written file is opened
- **THEN** it contains the analyst prompt sections (role line, numbered task list, output-format instruction, guardrail) AND a `## Glossary` section, in one document

### Requirement: After writing the bundle the CLI SHALL print terminal-side guidance copy
After `--for-llm` succeeds, the CLI SHALL print guidance that confirms the file
was written and copied to the clipboard, and points the user at **any capable
AI chat** — naming a few examples with URLs (e.g. Claude, ChatGPT, DeepSeek,
Gemini, Kimi) rather than presenting a closed list of providers. The guidance
SHALL make clear the pasted content already carries both the prompt and the
data.

When `--anonymize` is NOT set, the guidance SHALL additionally include a
one-line nudge mentioning the `--anonymize` flag for users pasting into a
public LLM.

When `--anonymize` IS set, the guidance SHALL print the in-memory handle ↔
original mapping to the terminal (and SHALL NOT write it into the file or copy
it to the clipboard) so the user can decode the LLM's references later without
leaking the mapping into a public chat.

#### Scenario: Guidance is provider-neutral and names DeepSeek among examples
- **WHEN** the user runs `--for-llm` without `--anonymize`
- **THEN** the post-write output frames the targets as "any AI chat", lists several examples including DeepSeek with URLs, confirms the clipboard copy, and includes the `--anonymize` nudge

#### Scenario: Anonymize-mode prints handle mapping to terminal only
- **WHEN** the user runs `--for-llm --anonymize`
- **THEN** the terminal prints the mapping `SSID_1 ↔ <original>` etc.; the written file contains an `## Anonymization` placeholder pointing back at the terminal, and the mapping is neither in the file nor on the clipboard
