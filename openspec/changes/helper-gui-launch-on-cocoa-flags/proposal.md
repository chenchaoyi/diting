## Why

The helper's argv dispatch treated ANY first argument as a subcommand and
`exit(64)`'d on an unrecognized one. But `diting setup` and the installer open
the bundle with `open … --args -AppleLanguages "(<tag>)"` (to localise the macOS
TCC prompts), which makes `CommandLine.arguments[1] == "-AppleLanguages"` — so the
helper hit the `default` case and **exited 64 before launching its GUI**. The GUI
is the only thing that requests the Location / Bluetooth / Notifications prompts,
so **no prompt ever appeared** and `diting setup` waited forever. This was latent
since the start; until v2.0.1 the prompts actually came from `setup`'s functional
poll probes (`scan` / `bluetooth-status`), which masked it — once those became
read-only (v2.0.1), nothing surfaced a prompt.

## What Changes

- The helper SHALL treat only its known tokens (`scan`, `ble-scan`,
  `bluetooth-status`, `location-status`, `bluetooth-authorization`,
  `notification-status`, `notify`, `associate`, `--help`/`-h`) as subcommands.
  A non-subcommand argument that is a flag (starts with `-`, e.g.
  `-AppleLanguages` injected by `open --args`) SHALL fall through to the GUI —
  launching the permission window so the macOS prompts show. A non-flag,
  non-subcommand token (a genuine typo) still errors with exit 64.

## Capabilities

### Modified Capabilities
- `macos-helper`: launching the bundle with Cocoa / LaunchServices flags (the
  `open --args -AppleLanguages …` path `setup` and the installer use) SHALL
  launch the GUI permission flow, not be misread as an unknown subcommand.

## Impact

- `helper/Sources/diting-tianer/main.swift` — gate the subcommand switch on a
  `knownSubcommands` set; flags fall through to the GUI; non-flag unknowns still
  exit 64. No JSON / schema change. Helper rebuild → ships in the next (patch)
  release; the released helper finally shows the prompts under `diting setup`.
- No Python change (`open_bundle` keeps `--args -AppleLanguages` for prompt
  localisation — now handled correctly).
- Immediate recovery on an already-installed (broken) helper: `open` the bundle
  WITHOUT `--args` (so `args.count == 1` → GUI) drives the prompts directly.
- Tests: helper-side, verified by hand (rebuilt bundle: `-AppleLanguages` keeps
  the process alive / launches the GUI; `location-status` still exits 4; a typo
  still exits 64). Update `tests/TESTING.md` (EN + ZH).
