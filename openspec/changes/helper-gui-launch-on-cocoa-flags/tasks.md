## 1. Test plan first

- [x] 1.1 `tests/TESTING.md` (EN): macos-helper row — opening the bundle with a Cocoa flag (`-AppleLanguages`) launches the GUI (not exit 64); real typo still exit 64; known subcommands unaffected
- [x] 1.2 ZH parity in `docs/zh/TESTING.md`

## 2. Helper

- [x] 2.1 Gate the subcommand switch on a `knownSubcommands` set; a flag (`-`-prefixed) first arg falls through to the GUI; a non-flag unknown still `exit(64)`
- [x] 2.2 Rebuild (`./helper/build.sh`) and verify by hand: `-AppleLanguages "(en)"` keeps the process alive (GUI), `location-status` exits 4, `frobnicate` exits 64

## 3. Gates

- [x] 3.1 `uv run pytest`
- [x] 3.2 `uv run python scripts/tui_snapshot.py --mode regression`
- [x] 3.3 `openspec validate --specs --strict` and `openspec validate helper-gui-launch-on-cocoa-flags --strict`
