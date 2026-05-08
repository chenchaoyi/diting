---
name: tui-audit
description: Open-ended TUI exploration. Drive the dashboard through scenarios, generate new ones from observed clues, and surface product-improvement directions until the search runs dry or the budget is hit.
allowed-tools: Bash, Read, Write, Edit
argument-hint: [budget-minutes] | [scenario_id]
---

You are running an **open-ended audit** of the wifiscope TUI.
The user does not want a one-shot run of the prebuilt
scenarios — they want you to **explore**: try different inputs,
observe behaviour, identify gaps, propose product directions,
and keep going until the search itself runs out of fresh ideas
(or you hit the budget).

## Argument

`$ARGUMENTS` is interpreted as either:

- `<int>` (1–60) — explicit budget in **minutes** (default: 20).
- An existing scenario id (e.g. `ble_normal`) — focus the audit
  on that one corner only, no exploration loop.
- Empty — full exploration with the default 20-minute budget.

## Findings file

Findings persist in real time so a mid-run interrupt does not
lose work. Write to `/tmp/wfs-tui-audit/findings.md`. Append
each new finding as you discover it; never rewrite the whole
file at once. Format:

```
## Iteration N — <short hypothesis>
**Severity:** info | note | warn
**Observation:** <what you saw>
**Suggestion:** <concrete next step: file, function, change>
**Screenshot:** /tmp/wfs-tui-audit/<scenario>.png
```

## Workflow

### Phase 1 — baseline (always run)

1. Run the prebuilt scenarios:

   ```bash
   uv run wifiscope snapshot --out-dir /tmp/wfs-tui-audit
   ```

2. `Read /tmp/wfs-tui-audit/snapshot-report.json`. Mechanical
   inspector findings already live there — copy them into your
   findings file as iteration 0 entries.

3. `Read` every PNG. For each, note any visual issue the
   inspectors could not have caught: alignment, contrast,
   density, EN ↔ ZH layout drift, columns clipped at the
   viewport edge, decorative-but-empty rows, etc. Append to
   findings.

### Phase 2 — exploration loop

Keep iterating until one of:
- the budget (default 20 min wall-clock) is exhausted
- you have produced 3 consecutive iterations with **no new**
  findings (diminishing returns)
- the user interrupted

Each iteration:

1. **Form a hypothesis.** Examples — but invent your own:
   - "Long SSID names truncate badly in the connection panel."
   - "BLE list footer wraps when there are 50+ rows."
   - "Pressing `c` mid-scan crashes the poller."
   - "EnvironmentMonitor with one calibrated AP shows a bogus σ."
   - "All Apple BLE rows show vendor=None when the OUI map
     misses 4c:e9:e4."
   - "Two roams within 2 s create a duplicate event row."
   - "SSID with embedded emoji breaks the Connection panel
     border."

2. **Pick the cheapest way to test it:**
   - **Existing scenario edit**: tweak data inside an existing
     scenario in `src/wifiscope/snapshot.py` — quick.
   - **New scenario**: add a new entry to `_all_scenarios()`
     with the right backend / data / keystrokes. Keep the
     synthetic data minimal and self-explanatory.
   - **Inspector tweak**: occasionally a hypothesis is best
     expressed as an inspector rule (e.g. "warn when more than
     N rows show identical truncated AP-prefix labels"). Add
     to the inspectors list.

3. **Capture**: re-run only the affected scenario:

   ```bash
   uv run wifiscope snapshot --out-dir /tmp/wfs-tui-audit \
       --scenarios <new_or_modified_id>
   ```

4. **Read the produced PNG** and verify your hypothesis.

5. **Append a finding** to the findings file regardless of
   outcome — "tried X, no issue" is also useful signal so the
   user knows what was searched.

6. **Decide**: another iteration, or stop.

### Phase 3 — wrap-up

When the loop exits, output to the chat:

1. **Run summary**: budget used, iterations completed,
   findings count by severity.
2. **Top 3 actionable items**: the highest-leverage findings
   with concrete file/function references.
3. **New scenarios contributed**: list of ids the run added to
   `src/wifiscope/snapshot.py`, so the user can decide whether
   to keep / git-add them.
4. **Pointer to the full findings file**:
   `/tmp/wfs-tui-audit/findings.md`.

## Stopping rules — important

- The default 20-minute budget is a soft ceiling. If you find
  a really juicy bug at minute 19, finish writing it up; don't
  cut yourself off mid-thought.
- If the snapshot CLI itself fails (Swift helper missing, TCC
  unrelated breakage, Textual import error), stop immediately
  and surface the failure. Do not try to analyse partial /
  broken captures as if they were valid.
- If the user has interrupted (you'll be re-entered with prior
  context), pick up where the findings file left off rather
  than starting from scratch.

## Conventions

- Treat the captured PNGs as ground truth. What you see is
  what the user would see.
- Don't claim to have "fixed" anything in this command — your
  job is to audit, propose, and (where it costs little) add a
  scenario or inspector that surfaces the gap. The user decides
  what gets committed.
- Strip AI-flavoured copy from your report. State findings
  directly; no editorial about your own writing voice. The
  user has explicitly called this out as a tell.
- Synthetic data only. Never invent realistic-looking BSSIDs
  or SSIDs that could be confused with the user's real
  network. Use clearly-fake ranges (`aa:bb:cc:*`,
  `de:ad:be:ef:*`, `synthetic-X`).
