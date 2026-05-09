# Document the `roam-detection` capability

## Why

The Roam score row of the Diagnostics panel and the same-SSID
better-candidate hint are wifiscope's most "actionable" surface —
they tell the user "press c to switch to a stronger AP". The +10 dB
threshold for surfacing a candidate, the press-c-cycles-Wi-Fi
mechanism, and the shared RSSI vocab between Current link and Roam
score were all settled empirically and are easy to drift away from
in a refactor (the recent ZH-audit caught the
"fair vs usable" mismatch — exactly the failure mode this spec
guards against).

## What Changes

- Introduce capability `roam-detection`.
- No code changes — backfill from the `_link_score`,
  `_best_same_ssid_candidate`, `action_reroam` paths in
  `src/wifiscope/tui.py`.

## Capabilities

### New Capabilities
- `roam-detection`: 0-100 link scoring, +10 dB candidate threshold,
  press-c Wi-Fi cycle action, RSSI vocab consistency invariant.

### Modified Capabilities
None.

## Impact

- Affected code: none (documentation-only)
- Affected specs: creates `openspec/specs/roam-detection/spec.md`
- Cross-cuts with: `wifi-scanning` (consumes scan results to find
  candidates), `tui-shell` (the c keybinding lives there)
- Future impact: changing the +10 dB threshold or the score
  rubric MUST file a MODIFIED Requirement
