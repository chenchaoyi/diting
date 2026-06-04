# Fix the stale primary-binding count in the Hidden bindings requirement

## Why

The `tui-shell` "Hidden bindings" requirement still says the footer shows
"**eight** primary bindings". The footer now shows **ten** — `quit`, `pause`,
`rescan`, `sort`, `re-roam`, `view`, `events`, `companion`, `help`, `basics` —
ever since the companion (`k`) binding landed (#140) and was reflected in the
sibling footer requirement (#163). The "eight" was missed in that pass, leaving
the canonical spec internally inconsistent.

## What Changes

Correct the count from "eight" to "ten" in the Hidden bindings requirement body.
No behavior change, no code change — the footer already renders ten.

## Impact

- Affected specs: `tui-shell` (one requirement-body word).
- Affected code: none.
