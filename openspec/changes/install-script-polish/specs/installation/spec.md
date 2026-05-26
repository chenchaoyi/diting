## ADDED Requirements

### Requirement: The installer SHALL render output via a three-tier compatibility ladder selected from the runtime environment
`install.sh` SHALL select one of three output tiers at startup and route every user-visible line through that tier. Tier selection SHALL run once before any other output (after `set -euo pipefail`, before platform detection) and SHALL persist for the rest of the run.

The three tiers and their normative selection logic, in priority order:

1. **`DITING_INSTALL_FORMAT={full|plain|log}`** explicit override SHALL force the named tier regardless of environment.
2. **Non-TTY** (`[ -t 1 ]` returns false) SHALL select TIER LOG.
3. **`NO_COLOR` set to any non-empty value** SHALL select TIER PLAIN.
4. **`TERM` set to `dumb` or empty** SHALL select TIER PLAIN.
5. **`UTF-8` locale** (`LC_ALL`, `LC_CTYPE`, or `LANG` contains a UTF-8 marker, case-insensitive) SHALL select TIER FULL.
6. **No UTF-8 locale detected** SHALL select TIER PLAIN.

The three tiers are normative:

- **TIER FULL**: SHALL render a one-time pixel-beast header (byte-equal to `_LOGO_MARK_ART` in `src/diting/tui.py`) in brand orange (`#fea62b` via 24-bit ANSI), a tagline `diting installer · <VERSION>`, then six numbered step rows `[N/6] Label    Value` with two-column alignment, Unicode `✓` / `✗` status markers (green / red respectively), and a separate end-of-install summary block.
- **TIER PLAIN**: SHALL render the same six numbered step rows with two-column alignment, ASCII `[OK]` / `[FAIL]` status markers, no color, no logo, and the same summary block at the end.
- **TIER LOG**: SHALL render the exact `diting install: …` flat output that ships on `main` today — byte-identical so downstream consumers (Homebrew cask, CI, `tests/test_install.py` snapshot assertions) continue to parse correctly.

The six steps are: `Host` (architecture), `Release` (resolved version), `Download` (tarball name + optional size), `Verify` (SHA256, truncated to 8-char prefix in FULL/PLAIN), `Install` (install prefix path), `Helper` (helper-bundle path + the three localised TCC-prompt guidance lines as continuation rows).

The installer SHALL preserve every existing behavioural invariant:

- Same exit codes (every `die` site keeps its current exit status).
- Same `set -euo pipefail` strictness.
- Same `DITING_INSTALL_TESTONLY=1` short-circuit semantics — which runs under CI / non-TTY → TIER LOG → byte-identical to today.
- Same `--env DITING_LANG=<lang>` + `--args -AppleLanguages (<tag>)` helper-bundle launch flow.
- Same ZH-vs-EN locale branch copy text (the three `helper window` / `授权完成` lines for step 6).
- Same PATH-update hint flow at script tail.

Zero new external dependencies: implementation SHALL use only ANSI escape sequences and bash builtins. No `tput`, no `ncurses`, no new `awk` invocations beyond what `install.sh` already uses.

#### Scenario: Interactive macOS terminal with UTF-8 locale and no `NO_COLOR`
- **WHEN** a user runs `bash install.sh` in iTerm2 / Terminal.app with default `LANG=en_US.UTF-8` and no `NO_COLOR` set
- **THEN** the installer prints the brand-orange pixel-beast header followed by six numbered step rows, each with a green `✓` marker on completion, followed by an indented `Installed.` summary block with `binary` / `bundle` / `next` rows

#### Scenario: User sets `NO_COLOR=1`
- **WHEN** the user runs `NO_COLOR=1 bash install.sh` in an interactive UTF-8 terminal
- **THEN** the installer skips the logo and all ANSI color, but still renders the six numbered step rows with ASCII `[OK]` markers and the summary block — TIER PLAIN

#### Scenario: User explicitly forces log format
- **WHEN** the user runs `DITING_INSTALL_FORMAT=log bash install.sh` in any environment
- **THEN** the installer ignores TTY / locale detection and emits the exact `diting install: …` flat format, byte-identical to the pre-change output

#### Scenario: Homebrew cask install (non-TTY)
- **WHEN** Homebrew invokes the script via its `installer script` directive (stdout piped, no TTY)
- **THEN** `[ -t 1 ]` returns false; the installer selects TIER LOG; output is byte-identical to today's format and existing brew-side parsers continue to work

#### Scenario: CI / `DITING_INSTALL_TESTONLY=1` run
- **WHEN** the installer runs under `tests/test_install.py` with `DITING_INSTALL_TESTONLY=1` set and stdout captured (non-TTY)
- **THEN** the script selects TIER LOG; existing TESTONLY assertions in `tests/test_install.py` pass byte-for-byte; the new TIER FULL / TIER PLAIN test cases use a pseudo-TTY harness (`script -q /dev/null` on BSD macOS or `pty.openpty()` in Python) to assert the polished shapes independently

#### Scenario: Bash without UTF-8 locale (`LC_ALL=C`)
- **WHEN** a user runs `LC_ALL=C bash install.sh` in an interactive terminal
- **THEN** the installer falls to TIER PLAIN — no logo, no color, ASCII `[OK]` markers, but still the six-step numbered structure and summary block

#### Scenario: Dumb terminal (`TERM=dumb`)
- **WHEN** stdout is a TTY but `TERM=dumb` or unset
- **THEN** the installer selects TIER PLAIN regardless of locale; the user gets ASCII step markers and a no-color summary

#### Scenario: Step failure surfaces a marker before exit
- **WHEN** any step (download, sha mismatch, extraction, helper-prime) fails with a `die_with_marker` call
- **THEN** TIER FULL / TIER PLAIN print a red `[✗]` (or `[FAIL]`) marker on the failing step row before the existing `diting install: error: <msg>` line; TIER LOG keeps the unchanged `diting install: error: <msg>` flat output; exit code is the same as today
