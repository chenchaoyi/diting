# Design

Track B of the long-timeline analysis effort. Bridges diting's
A2 aggregates to LLM analysis via a Markdown report + paste-ready
prompt, no API integration.

## D1. Why no API integration

User explicitly chose against the maigret `--ai` pattern (built-in
OpenAI API key). Reasons:

- Adds an external network dependency to a tool that's
  intentionally offline.
- Forces a `pip install diting[ai]` extras branch with
  `openai` / `anthropic` SDKs.
- Token cost lives in diting's user-experience surface rather than
  the user's own LLM account.
- Drag-drop into chat.openai.com / claude.ai is a 5-second UX —
  not worth the engineering tax.

So the design pattern is "emit artifacts the user can paste",
not "wrap the LLM".

## D2. Markdown report shape

`report.md` mirrors the terminal report's content but uses
Markdown structure so the LLM can navigate it:

```markdown
# diting analysis report

**Scope:** 12 files · 2026-04-19 → 2026-05-20 · `--since 30d`

## Connection timeline (per file)
...

## Per-session heuristics

### Insight: Frequent inter-AP roams
**Severity:** info
**Detail:** ...
**TODO:** ...

## Cross-session aggregations

### Events by hour-of-day

| Hour | Total | Top type |
|---:|---:|---|
| 09 | 47 | rf_stir |
| ...

### Day × hour heatmap
```text
Mon  ▁▁▁▁  ▁▁▁▂▁▁▅▁▂▂▂ ▁
...
```

### Top networks
...

## Glossary
...

## Anonymization (when --anonymize)
| Handle | Original |
|---|---|
| `SSID_1` | `home-5G` |
...
```

The terminal report uses ASCII-art bars; the Markdown report
reuses the same ASCII inside fenced code blocks (so a Markdown
viewer doesn't try to interpret the block characters as
formatting), plus tables for ranked / per-bucket data which read
better as Markdown tables in an LLM chat.

## D3. Prompt template

`prompt.txt` is one bundled template the user pastes. Five
sections:

```
You are a wireless / network analyst reviewing a `diting`
report (macOS terminal Wi-Fi / BLE / LAN monitor). The report
covers <span> across <files> session logs.

Your task:

1. Identify the top 3 patterns the data supports.
2. For each pattern, name the most likely root cause and the
   evidence that supports it.
3. Suggest concrete follow-up investigations the user could
   run with diting (e.g. "capture during Tuesday 14:00-15:00
   with `--log` then re-analyze").
4. Where ASCII charts in the report suggest a trend, restate
   the trend as a one-line claim and tag it with one of:
   "supported by data", "weak signal", "speculative".
5. If the report includes an Anonymization appendix, do NOT
   decode the handles — analyze using the handles as opaque
   identifiers.

Output format: markdown. Don't repeat the report data
verbatim — interpret it. Lead with conclusions, then
evidence. Mark any inference beyond what the data shows as
"hypothesis".

Important: don't speculate about causes the data doesn't
touch. If something looks suspicious but you can't point to
specific events in the report, say so.
```

The `<span>` and `<files>` get string-substituted from the report
context. The rest is constant.

## D4. Anonymization strategy

Stable handles via deterministic ordering — first-seen order in
the report itself (not lexicographic). This means a re-run on
the same data produces the same handles, which means the user
can save the mapping for later cross-reference.

Implementation:

```python
class Anonymizer:
    def __init__(self):
        self._maps: dict[str, dict[str, str]] = {
            "ssid": {}, "bssid": {}, "ip": {}, "host": {},
            "ble": {},
        }
        self._counters: dict[str, int] = defaultdict(int)

    def map(self, kind: str, value: str) -> str:
        if value in self._maps[kind]:
            return self._maps[kind][value]
        self._counters[kind] += 1
        prefix = {
            "ssid": "SSID", "bssid": "AP", "ip": "IP",
            "host": "HOST", "ble": "BLE",
        }[kind]
        handle = f"{prefix}_{self._counters[kind]}"
        self._maps[kind][value] = handle
        return handle

    def public_mapping(self) -> dict[str, str]:
        # Flatten for the report's appendix.
        ...
```

The anonymizer is fed the events stream + the aggregation outputs
in pre-render order. Each value gets mapped at first sight; the
report renderer asks the anonymizer to translate identifiers
before writing them.

**What gets anonymized:**

- `event.ssid`, `event.bssid`, `event.new_bssid`, `event.previous_bssid`
- `event.ip`, `event.new_ip`, `event.previous_ip` — when RFC1918
  (192.168.x / 10.x / 172.16-31.x) only. Public IPs (`8.8.8.8`,
  `1.1.1.1`) survive verbatim — they're not identifying.
- `event.host`, `event.hostname`, `event.bonjour_name`
- `event.identifier` (BLE)
- `event.mac` (LAN host MAC)
- Aggregation labels that compose these (e.g. "Meituan (5G)" →
  "SSID_1 (5G)")
- Top-contributors rows

**What stays verbatim:**

- Vendor names ("Apple, Inc.", "Cisco Systems")
- Service categories ("AirPlay", "HID")
- Event-type names ("roam", "lan_host_seen")
- Magnitudes (RTT ms, σ dB, loss %)
- Timestamps (the `Time range` line — strip TZ if needed)
- Aggregation counts

## D5. Why JSONL stays unanonymized

The user's `diting-*.jsonl` files are the source of truth for
"what happened on my network on day X". Anonymizing the log at
write time would prevent re-analysis later. The anonymizer here
operates one-way at report generation, so the JSONL stays usable
forever.

## D6. CLI ergonomics

```
$ diting analyze diting-*.jsonl --since 30d --for-llm
✓ wrote diting-llm-2026-05-21T10-30-00/report.md  (32 KB)
✓ wrote diting-llm-2026-05-21T10-30-00/prompt.txt (1.4 KB)

to analyze with an LLM:
  1. open https://claude.ai or chat.openai.com
  2. drag-drop the report.md file into the chat
  3. paste the contents of prompt.txt
  4. submit

(if you're pasting into a public LLM and want to scrub
identifiers, re-run with --anonymize)
```

The "(if you're pasting into a public LLM...)" hint always shows
when `--anonymize` is OFF, so the user is reminded of the
trade-off without being lectured.

When `--anonymize` IS active, the post-write hint changes to:

```
✓ wrote diting-llm-.../report.md       (32 KB, anonymized)
✓ wrote diting-llm-.../prompt.txt      (1.4 KB)

anonymization mapping (keep this private — do NOT paste):
  SSID_1 ↔ home-5G
  SSID_2 ↔ Meituan
  AP_1 ↔ aa:bb:cc:...
  ...
```

The mapping prints to TERMINAL ONLY — not into the .md file. The
.md file's "## Anonymization" appendix is a placeholder reminding
the user to consult their terminal output.

## D7. Test surface

`tests/test_analyze.py` additions (under a new
`# --- Track B: LLM-bridge export ---` section):

- `test_anonymizer_assigns_stable_handles`
- `test_anonymizer_same_value_returns_same_handle`
- `test_anonymizer_preserves_public_ip_addresses`
- `test_anonymizer_replaces_rfc1918_addresses`
- `test_for_llm_writes_report_markdown`
- `test_for_llm_writes_prompt_txt`
- `test_for_llm_with_anonymize_replaces_identifiers`
- `test_for_llm_without_anonymize_preserves_identifiers`
- `test_for_llm_prompt_template_includes_required_sections`
- `test_for_llm_terminal_guidance_appears_on_stdout`

`tests/test_cli.py` additions:

- `test_analyze_for_llm_flag_threads_through`
- `test_analyze_anonymize_flag_threads_through`

## D8. Surface impact

- `src/diting/analyze.py` — new `Anonymizer` class (~80 LoC),
  Markdown renderer (~250 LoC), prompt-template generator
  (~80 LoC).
- `src/diting/cli.py` — `--for-llm` / `--anonymize` argparse
  flags, output directory creation, terminal-guidance printing.
- `tests/test_analyze.py` — additions (~300 LoC).
- `tests/test_cli.py` — small additions.
- `docs/explainers/llm-bridge.md` (new) — short user-facing
  doc on the workflow. Mirrored in `docs/zh/explainers/`.

No new third-party dependency.
