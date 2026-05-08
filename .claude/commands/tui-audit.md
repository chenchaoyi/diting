---
name: tui-audit
description: Drive the wifiscope TUI through scenario captures, visually read each screenshot, and report regressions + product-improvement opportunities.
allowed-tools: Bash, Read, Write, Edit
argument-hint: [scenario_id]   # optional, runs one scenario only
---

You are auditing the wifiscope TUI for visual / UX bugs and
product-improvement opportunities. The user invoked `/tui-audit`
to ask you to **look at the dashboard with your own eyes**, not
just run unit tests.

## Workflow

1. **Run the snapshot CLI** to capture screenshots of the
   designed scenarios:

   ```bash
   uv run wifiscope snapshot --out-dir /tmp/wfs-tui-audit
   ```

   If the user passed an argument (`$ARGUMENTS`), restrict to
   that scenario:

   ```bash
   uv run wifiscope snapshot --out-dir /tmp/wfs-tui-audit --scenarios $ARGUMENTS
   ```

   The CLI:
   - drives the TUI via Textual's pilot
   - writes one `.svg` + one `.png` per scenario
   - writes `snapshot-report.json` with assertions + heuristic findings

2. **Read the JSON report first** — `Read /tmp/wfs-tui-audit/snapshot-report.json`. Mechanical assertion failures and inspector findings are already there; you don't need to re-derive them.

3. **Visually read every PNG** — for each scenario row in the
   report, `Read` the corresponding `.png` file. Look at it
   like a user would. Note anything that catches your eye:

   - layout problems (overlapping panels, columns clipped at
     window edge, footer cut off)
   - visual inconsistencies between EN and ZH (alignment shifts
     when CJK widens columns)
   - empty / placeholder content where a real value was expected
   - unhelpful "(unknown)" / "?" labels that are common enough
     to suggest a data-coverage gap
   - colour issues (low contrast, semantic colour misused)
   - density problems (too many rows, too few rows, repeating
     near-identical rows that could be aggregated)

4. **Look beyond the shipped scenarios.** The harness's scenario
   list is a starting point, not a ceiling. If you see a clue
   in one scenario that suggests a deeper bug or a missing
   exploration, propose (and where reasonable, add) a new
   scenario in `src/wifiscope/snapshot.py` that exercises it.
   Edge cases worth probing:

   - very long SSID / AP names (column truncation behaviour)
   - extremely strong RSSI (-30 dBm — does the bar saturate?)
   - extremely weak signal (-95 dBm — does noise floor render?)
   - many BLE devices (50+ rows — does pagination / sort hold?)
   - many simultaneous events (ring buffer overflow shape)
   - `c` key (force re-roam) — currently no scenario covers it

5. **Synthesise the findings into a structured Markdown
   report** with three sections:

   ### Visual issues (your eyes only)
   Things you saw that the inspector heuristics could not have
   found mechanically. Reference scenario id + screenshot path.

   ### Product opportunities
   The inspector findings (already in JSON) plus anything you
   noticed that suggests a feature gap, a data-coverage gap
   (more OUIs, more Continuity types), or a UX redesign.

   ### Regression status
   One-line summary of the assertion pass/fail counts.

   Each finding should include a concrete next step (which file
   to edit, what to change). Don't write "the UI could be
   better" — write "the BLE list footer in `_ble_list_text`
   wraps when there are 30+ rows; consider truncation logic
   like `_scan_list_lines`."

## Conventions

- Treat the captured PNGs as the ground truth — what the user
  would actually see if they ran wifiscope right now.
- Don't claim to have "fixed" anything in this command — that
  is the user's call. Your job is to audit and report.
- If you do add a new scenario or inspector to
  `src/wifiscope/snapshot.py` during the run, mention it in the
  report so the user can decide whether to commit it.
- Strip any AI-flavoured copy from your report. State findings
  directly; don't editorialise about your own writing voice.

## Recovery

If `uv run wifiscope snapshot` fails to launch (no Swift helper,
TCC not granted, broken display backend) — say so plainly and
stop. The audit only works against a runnable TUI. Don't try to
analyse a partial / broken capture as if it were valid.
