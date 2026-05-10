---
name: tui-audit
description: Open-ended TUI audit against the user's REAL Wi-Fi / BLE environment. Drive the dashboard live, observe what the user actually sees right now, surface bugs and product-improvement directions until the search runs dry or the budget is hit.
allowed-tools: Bash, Read, Write, Edit
argument-hint: [budget-minutes]
---

You are running an **open-ended audit** of diting **against
the user's actual environment**. Real backend, real BSSIDs, real
BLE devices, real latency / RF / event data — not the synthetic
fixtures the regression suite uses. The point is to find
problems the user would actually hit, not to verify that the
synthetic scenarios still render.

## Argument

`$ARGUMENTS`:

- `<int>` (1–60) — explicit budget in **minutes** (default: 20).
- Empty — full exploration with the default 20-minute budget.

## Output location

The capture script picks a fresh timestamped directory each run:

```
/tmp/wfs-tui-audit-YYYYMMDD-HHMMSS/
```

So multiple `/tui-audit` runs in one day don't clobber each
other. Read the path the script prints on its first line; do
NOT hardcode a fixed `/tmp/wfs-tui-audit/` anywhere in your
output. The findings file and any later inspections live under
that timestamped dir.

## Privacy

- Captured PNGs / SVGs / JSON contain the user's real SSIDs,
  BSSIDs, IP addresses, BLE device names ("ccy's iPhone",
  "Magic Keyboard", etc.). Stay in `/tmp/`. Never copy or
  reference them outside the user's machine, never ask the user
  to share the captured PNGs publicly without redaction, never
  commit them.
- The slash command's `--out-dir` argument resolves to a
  timestamped path under `/tmp/`. Do not override it.

## Findings file

Findings persist in real time so a mid-run interrupt does not
lose work. Write to `<out_dir>/findings.md`. Append each new
finding as you discover it; never rewrite the whole file.
Format:

```
## Iteration N — <short hypothesis>
**Severity:** info | note | warn
**Observation:** <what you saw, with concrete data: counts, ratios, screenshots>
**Suggestion:** <concrete next step: file, function, change>
**Screenshot:** <out_dir>/<scenario>.png
```

## Workflow

### Phase 1 — live capture (always run)

1. Run the capture script in explore mode:

   ```bash
   uv run python scripts/tui_snapshot.py --mode explore
   ```

   `scripts/tui_snapshot.py` is the engineering tool living
   under `scripts/`, NOT a user-facing `diting` subcommand.
   In `--mode explore` it builds the TUI on top of
   `MacOSWiFiBackend()` + the real BLE helper, then drives it
   through six keystroke scenarios:

   - `live_main`         — main Wi-Fi view, scan list populated
   - `live_ble`          — `n` → BLE list (real devices nearby)
   - `live_events_modal` — `m` → events from this session
   - `live_help`         — `h` → help modal
   - `live_basics`       — `b` → basics / glossary modal
   - `live_paused`       — `p` → polling paused

   Each scenario allows ≥10 s of settle time so the live scan,
   ping aggregates and BLE snapshot have something real to show.

   Parse the `output: …` line on stdout to learn the
   timestamped out_dir for this run.

2. `Read <out_dir>/snapshot-report.json`. Mechanical inspector
   findings (BLE unknown-vendor ratio, redacted scan, etc.) are
   already there — copy them into `findings.md` as iteration 0
   entries.

3. `Read` every PNG. For each, note any visual issue the
   inspectors couldn't have caught:
   - layout problems (overlapping panels, columns clipped,
     footer cut off)
   - EN ↔ ZH alignment drift if the user runs Chinese UI
   - density problems (too many redundant rows, dead space)
   - colour / contrast issues
   - placeholder text that doesn't match reality (e.g. "no APs
     from last scan — likely throttle" while the user is
     actually disassociated)

   Append to findings.

### Phase 2 — exploration loop

Keep iterating until one of:
- the budget (default 20 min wall-clock) is exhausted
- 3 consecutive iterations produce no new findings (diminishing
  returns)
- the user interrupted

Each iteration:

1. **Form a hypothesis from the live data.** You can't fabricate
   the user's environment, but you can keep digging into what's
   already there. Examples:
   - "BLE list shows N rows with vendor=None — is the OUI map
     missing common consumer brands the user has nearby?"
   - "I saw 3 different roam events on `live_main` between
     consecutive captures — is the AP load-balancing aggressive?"
   - "The events modal had no events fired in the live session
     because the connection was stable — try capturing again
     after walking around or after a brief outage."
   - "BLE rows show 'Magic Keyboard' but no service categories
     populated — is the helper's connected-peripheral
     enumeration including service UUIDs?"

2. **Pick the cheapest way to test it.** Real-mode options are
   narrower than synthetic-mode:
   - **Re-capture**: re-run a single scenario after some delay
     to compare two snapshots (catches jitter, list churn,
     event activity over time):

     ```bash
     uv run python scripts/tui_snapshot.py --mode explore \
         --out-dir <out_dir> --scenarios live_ble
     ```

   - **Inspector tweak**: an observation generalises into a
     rule — add it to `_explore_inspectors` (or the specific
     inspector list) in `scripts/tui_snapshot.py`. The user
     can decide whether to keep the change.

   - **Code-only finding**: cross-read with the source under
     `src/diting/` and pin the issue to a function / line
     number. Sometimes the screenshot only triggers the
     hypothesis; the actual finding lives in the code.

3. **Capture or inspect**, then **read the result**.

4. **Append a finding** to the findings file regardless of
   outcome. "Tried X, no issue" is also useful — tells the
   user what was searched.

5. **Decide**: another iteration, or stop.

### Phase 3 — wrap-up

When the loop exits, output to the chat:

1. **Run summary**: budget used, iterations completed, findings
   count by severity.
2. **Top 3 actionable items**: the highest-leverage findings
   with concrete file/function references.
3. **Code or scenario contributions**: list of edits this run
   made to `scripts/tui_snapshot.py` (new inspector, etc.) so
   the user can decide whether to keep / git-add them.
4. **Pointer to the full findings file**: `<out_dir>/findings.md`.
5. **Privacy reminder**: the captured PNGs contain the user's
   real network data; share with care.

## Stopping rules — important

- The default 20-minute budget is a soft ceiling. If you find
  a juicy bug at minute 19, finish writing it up.
- If `scripts/tui_snapshot.py --mode explore` itself fails (Swift
  helper missing, TCC denied, network down), stop immediately
  and surface the failure plainly. Don't try to analyse
  partial / broken captures as if they were valid.
- If the user has interrupted (you'll be re-entered with prior
  context), pick up where the findings file left off rather
  than starting from scratch — the timestamped dir from the
  last run can be passed back in via `--out-dir <previous>` if
  the user wants continuity.

## Conventions

- Treat the captured PNGs as ground truth. What you see is
  what the user actually saw on their machine just now.
- Don't claim to have "fixed" anything in this command — your
  job is to audit, propose, and (where it costs little) add an
  inspector that surfaces the gap. The user decides what gets
  committed.
- State findings directly. No editorial about your own writing
  voice — the user has explicitly called this out as an AI
  tell.
- Real data only. NEVER edit a synthetic value into a captured
  finding to "anonymise" it; just keep the file in `/tmp/`. If
  you need to share an example externally, write a redacted
  prose summary instead of the raw screenshot.
