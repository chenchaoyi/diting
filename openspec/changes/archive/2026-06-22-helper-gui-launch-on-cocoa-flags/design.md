## Context

`main.swift` did `if args.count > 1 { switch args[1] { … default: exit(64) } }`,
then fell through to the GUI (`app.run()`) only when `args.count <= 1`. `open
--args -AppleLanguages "(en)"` makes `args[1] == "-AppleLanguages"` → `default` →
`exit(64)`. The GUI (which owns the prompt flow) never ran.

## Decisions

### D1 — Gate the switch on a known-subcommand set
`let knownSubcommands: Set<String> = [scan, ble-scan, bluetooth-status,
location-status, bluetooth-authorization, notification-status, notify, associate,
--help, -h]`. `if args.count > 1, knownSubcommands.contains(args[1]) { switch … }`
— each case exits as before. `else if args.count > 1, !args[1].hasPrefix("-") {
exit(64) }` preserves the "unknown subcommand" error for a real typo. Everything
else (no args, or a `-`-prefixed Cocoa flag) falls through to the GUI.

Rationale: Cocoa launch flags always start with `-` (`-AppleLanguages`,
`-NSDocumentRevisionsDebugMode`, …); our subcommands are bare words (plus
`--help`/`-h`, which are in the known set). So "flag → GUI, bare unknown word →
error" cleanly separates the two.

### D2 — Keep `--args -AppleLanguages` on the Python side
The prompt-localisation arg stays; the helper now handles it. No Python change.

## Risks / Trade-offs

- [A future Cocoa flag we don't expect] → still routes to the GUI (the safe
  default for a launched bundle), never a hard error.
- [Helper rebuild needed] → standard release mechanics; the release builds the
  universal2 helper.

## Verification

Rebuilt locally: `diting-tianer -AppleLanguages "(en)"` stays alive (GUI launches)
instead of exit 64; `location-status` still exits 4; `frobnicate` still exits 64.

## Open Questions
- None.
