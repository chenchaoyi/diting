# for-llm-raw — design

## Decisions

- **Reference the original file; never rewrite it.** Without `--anonymize`,
  `--raw` adds nothing to disk — it lists the input log path(s) the user
  already passed and tells them to attach those. No copy, no stale duplicate,
  no extra disk. For a glob of inputs, all paths are listed.
- **Clipboard stays the briefing.** The raw log can be many MB — too big to
  paste. The small briefing `.md` still goes to the clipboard; the guidance
  says "paste the briefing (on your clipboard) and attach the log file(s)."
  Attachment is how AI chats handle large files; paste is for the briefing.
- **The prompt knows raw is attached.** `build_llm_document(report, *,
  anonymizer, raw_attached)` threads a flag to `build_llm_prompt`, which adds
  one instruction (EN + ZH): use the attached raw log to verify the summary and
  dig into specifics (exact timestamps, RSSI sequences, ordering), but rely on
  the briefing's stable-identity figures for population — raw ids over-count.
- **`--anonymize` is the only writer.** The original log has real identifiers,
  so attaching it would leak them. Under `--raw --anonymize` diting scrubs the
  parsed events with the *same* `Anonymizer` instance used for the briefing (so
  handles line up) and writes one `diting-raw-anonymized-<ts>.jsonl`; the
  guidance references that. A focused `scrub_event(ev, anonymizer)` maps the
  spec's identifying fields (ssid/bssid, RFC1918 ip, hostname/bonjour_name,
  ble identifier, mac) and leaves everything else verbatim.
- **`--raw` without `--for-llm`** implies `--for-llm` (you only attach a raw log
  alongside a briefing). On its own it's meaningless, so it turns the briefing
  on, consistent with how `-o` already implies `--for-llm`.

## Risks / Trade-offs

- [User forgets to attach the file] → the guidance prints the exact path(s) and
  says "attach"; the briefing alone still works (graceful).
- [Scrubber misses a field] → it maps exactly the fields the `--anonymize`
  report requirement already enumerates; a test asserts a known identifier is
  replaced and a public IP / vendor passes through.
- [Privacy: non-anonymized raw is real data] → same exposure as the original
  log the user already has; the `--anonymize` path and the existing public-LLM
  nudge cover the public-chat case.
