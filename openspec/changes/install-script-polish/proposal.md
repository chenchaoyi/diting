## Why

`curl -fsSL …/install.sh | bash` today renders as 10+ flat `diting install: …` log lines — every line indistinguishable from its neighbour, no sense of how many steps remain, no visual cue separating "downloading" from "installed" from "needs your Allow click". Users on first contact with the project read this as "noisy script ran" rather than "six clear steps completed; here's what to click next."

We can fix the first-impression UX without changing what the script *does*. The pixel-art beast that already lives in `src/diting/tui.py:_LOGO_MARK_ART` and `src/diting/splash.py` is the project's single brand mark; rendering it once at the top of the installer creates immediate continuity between "I'm installing diting" and "the running app". A six-step numbered progress block (`[1/6] Host darwin-arm64` etc.) gives users a finite sense of progress. A separated end-of-install summary block calls out next-step actions instead of burying them in the same `diting install:` prefix.

The compatibility envelope must stay intact: Homebrew cask flows, CI runners, the project's own `tests/test_install.py` snapshot — all expect the current flat format. So we add a strict three-tier ladder and fall back to today's exact output whenever stdout isn't an interactive TTY.

## What Changes

### One-time header (Tier FULL only)

Three-line pixel-beast in brand orange (`#fea62b`) rendered via 24-bit ANSI, identical art to `_LOGO_MARK_ART`, followed by a single-line tagline:

```
  █
█▀██████▄
▀██▀▀▀▀██
   diting installer · v1.7.3
```

### Six-step numbered progress (Tier FULL + Tier PLAIN)

Replace the flat `diting install: …` stream with a finite list:

```
[1/6] Host          darwin-arm64
[2/6] Release       v1.7.3
[3/6] Download      diting-1.7.3-darwin-arm64.tar.gz   (21 MB)
[4/6] Verify        sha256 cb2cceaf… ✓
[5/6] Install       ~/.local/share/diting
[6/6] Helper        macOS will ask for Location → Bluetooth → Notifications
```

Key/value rows are two-column-aligned via fixed padding; values are the substantive output today's flat log already carries.

### Status markers

- `✓` (green, Unicode) on each completed step in Tier FULL
- `[OK]` (white) in Tier PLAIN
- `✗` (red, Unicode) / `[FAIL]` (red) for the (`die` path) failure marker

### End-of-install summary block (Tier FULL + Tier PLAIN)

After step 6, a distinct indented summary that separates "installed" from prior noise:

```
  Installed.
    binary    ~/.local/bin/diting
    bundle    ~/Library/Application Support/diting/diting-tianer.app
    next      run `diting` (the splash will guide you through the TCC prompts)
```

### Three-tier compatibility ladder

| Tier | Conditions | Output |
|---|---|---|
| FULL | TTY (`[ -t 1 ]`) AND `${LANG}${LC_ALL}` contains `UTF-8` AND `${NO_COLOR:-}` empty AND `${TERM}` not `dumb` | header logo + 6 steps + colors + Unicode markers + summary |
| PLAIN | TTY but one of the FULL conditions fails | no logo, no colors, ASCII markers, 6-step structure + summary |
| LOG | non-TTY (pipe, Homebrew cask shell, CI) | exact `diting install: …` flat output of today — byte-identical for compatibility with existing logs and `tests/test_install.py` snapshots |

`NO_COLOR=1` (the [standard convention](https://no-color.org/)) forces TIER PLAIN even on an interactive TTY. Setting `DITING_INSTALL_FORMAT=log` forces TIER LOG regardless of TTY — gives Homebrew formula maintainers and downstream consumers an explicit escape hatch when they want today's machine-grep-friendly format on an interactive terminal.

### Behavioural invariants preserved

- Exit codes unchanged (every existing `die` site keeps the same exit status).
- `set -euo pipefail` strictness preserved.
- `DITING_INSTALL_TESTONLY=1` short-circuit unchanged (CI runs under non-TTY → TIER LOG → existing snapshot tests pass byte-for-byte).
- The helper-bundle `open --env DITING_LANG=... --args -AppleLanguages (...)` flow is untouched.
- The PATH-update hint at the end keeps printing in every tier; in FULL/PLAIN it lives inside the summary block, in LOG it stays in its existing position at the script's tail.
- The ZH locale branch (the three `helper window`/`授权完成` lines) keeps its existing copy text; the tier change is purely *how* the lines are presented, not *what* they say.

## Capabilities

### New Capabilities

(none — all changes land in the existing `installation` capability.)

### Modified Capabilities

- `installation`: new requirement that the installer SHALL render output via a three-tier compatibility ladder, with TIER LOG byte-identical to today and TIER FULL / TIER PLAIN providing a header + step-numbered progress + summary block.

## Impact

- **Code**: `install.sh` gains ~80 lines (tier detection, three renderer paths, two-column padding helper, ANSI escape constants). Existing `die`, `note`, `cleanup` helpers stay; new helpers `step`, `summary`, `tier_full`, `tier_plain`, `tier_log` route output. No new dependencies — pure ANSI escapes and bash builtins; no `tput`, no `ncurses`, no `awk` dependency growth beyond what's already used.
- **Tests**: `tests/test_install.py` gets 3 new cases — one per tier — pinning the output shape via subprocess capture with stubbed `[ -t 1 ]` (via `script -q`/`expect` on macOS or env var override) and the TESTONLY hook. Existing snapshot assertion stays unchanged (it runs in non-TTY → TIER LOG path).
- **TESTING.md** + **docs/zh/TESTING.md**: new row under the `installation` capability table.
- **README** + **docs/zh/README.md**: no changes required — the install one-liner command is identical; only its output cosmetics change.
- **Snapshot regression** (`scripts/tui_snapshot.py`): unaffected. The installer doesn't touch the TUI.
- **CI**: tests/test_install.py runs under pytest like every other test; no new GitHub Actions step needed.
- **Spec deltas**: `installation`.
