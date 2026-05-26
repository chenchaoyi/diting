## Context

`install.sh` (258 lines on `main`) is the project's first-impression surface — most users encounter it via the one-line `curl … | bash` recipe in README.md. Today every output line shares a `diting install: ` prefix, written by a single `note()` helper at `install.sh:47`. There's no header, no progress indicator, no separation between phases, no visual brand identity.

The same project already invests carefully in its visual identity inside the running TUI: the pixel-art beast at `src/diting/tui.py:6181` (`_LOGO_MARK_ART`), the brand-orange palette `#fea62b` at `colors_and_type.css`, the v1.7.3 startup splash that reuses both. The installer is the gap — it's the first thing users see and the only thing that doesn't carry the brand.

Compatibility constraints that pin our hands:

- **Homebrew cask** flows pipe `bash` and parse output. They expect today's `diting install: …` shape.
- **CI / `tests/test_install.py`** captures stdout under non-TTY and asserts substring presence. Today's format is the substrate of those asserts.
- **`DITING_INSTALL_TESTONLY=1`** runs in CI environments — non-TTY by definition; the TESTONLY branches already shortcut the destructive operations and emit `TESTONLY: would …` lines that downstream tests pin.
- **Color-blind / dim-terminal users** rely on `NO_COLOR` per the standard convention.
- **Terminals without UTF-8** (rare on macOS but possible under unusual `LC_ALL=C` sessions) need an ASCII fallback.

Any change to first-impression surface that breaks Homebrew or CI is strictly worse than the current flat format.

## Goals / Non-Goals

**Goals:**

- Render a one-time pixel-beast header + tagline on first-impression interactive runs so brand identity carries from install → running app.
- Give users a finite sense of progress via six numbered step indicators with two-column key/value alignment.
- Visually separate the end-of-install "what to do next" block from the prior step stream.
- Preserve byte-identical output on every non-TTY path so Homebrew, CI, and existing snapshot tests are unaffected.
- Pure-bash, zero new dependencies. No `tput`, no `ncurses`, no `awk` calls beyond what `install.sh` already does.

**Non-Goals:**

- Reworking what the installer *does*. Every existing step, every existing prompt, every existing helper-bundle launch flag — unchanged.
- Adding new install paths (Linux, Windows, etc.). Out of scope.
- Touching the running TUI's logo / splash. Those are already polished and carry the same canonical art; the installer simply reuses what already exists.
- Adding an in-installer translation system. The installer's existing `detect_locale` + EN/ZH case branches keep their current copy.
- Animating anything inside the installer. The splash inside the running app animates; the installer is one-shot and should stay snappy / unanimated. No Rich `Live` here — the installer is bash, not Python.

## Decisions

### Tier detection at script start

Single function `detect_tier()`, runs once near the top of the script (after `set -euo pipefail`, before the platform check). Returns one of `full` / `plain` / `log` as a string in a global `TIER` variable.

```bash
detect_tier() {
  # Explicit user override always wins.
  case "${DITING_INSTALL_FORMAT:-}" in
    log|plain|full) echo "${DITING_INSTALL_FORMAT}"; return ;;
  esac
  # Non-TTY: pipes, cron, CI, Homebrew cask shell.
  if ! [ -t 1 ]; then echo "log"; return; fi
  # NO_COLOR=anything-non-empty: standard convention, force PLAIN.
  if [ -n "${NO_COLOR:-}" ]; then echo "plain"; return; fi
  # Dumb terminals: VT100 lite, some serial consoles. ASCII only.
  case "${TERM:-}" in dumb|"") echo "plain"; return ;; esac
  # UTF-8 detection: LC_ALL > LC_CTYPE > LANG, any of them containing
  # `UTF-8` or `utf8` (case-insensitive). Default macOS sessions
  # ship `en_US.UTF-8`; explicit `LC_ALL=C` users get PLAIN.
  local locale_str
  locale_str="${LC_ALL:-${LC_CTYPE:-${LANG:-}}}"
  case "${locale_str}" in
    *UTF-8*|*UTF8*|*utf-8*|*utf8*) echo "full" ;;
    *)                              echo "plain" ;;
  esac
}
```

The decision flow is intentionally explicit per condition rather than chained `if/elif/else` so each disqualifying check is independent and grep-greppable. Order-of-priority is: explicit override > TTY check > `NO_COLOR` > `TERM` > locale.

### Three renderer entry points

Three top-level routing functions:

- `step <N> <label> <value>` — emits a numbered step row. In FULL it's color + Unicode `✓`; in PLAIN it's plain `[OK]`; in LOG it's the existing `diting install: …` line for that step. Each step call site replaces a corresponding `note "..."` site in today's script.
- `summary` — emits the end-of-install summary block. In FULL/PLAIN it prints the indented "Installed. binary … bundle … next …" block; in LOG it's a no-op (the existing `diting is on your PATH — run \`diting\`` line stays as the closer).
- `die_with_marker <msg>` — wraps the existing `die()` so the failure step gets a red `✗`/`[FAIL]` marker in FULL/PLAIN. In LOG it's the existing `diting install: error: ...` line.

Routing happens inside each function via a `case "$TIER" in full) … ;; plain) … ;; log) … ;; esac` block. The dispatch is local to each function so adding a new tier in the future is a one-place change.

### Header rendering

```bash
print_header() {
  [ "$TIER" = "full" ] || return 0
  local orange="$(printf '\033[38;2;254;166;43m')"
  local reset="$(printf '\033[0m')"
  printf '%s  █%s\n'        "$orange" "$reset"
  printf '%s█▀██████▄%s\n'   "$orange" "$reset"
  printf '%s▀██▀▀▀▀██%s\n'   "$orange" "$reset"
  printf '   diting installer · %s\n' "$VERSION"
  printf '\n'
}
```

24-bit color (the `\033[38;2;R;G;B;m` form) is supported by every modern macOS terminal — iTerm2, Terminal.app, Alacritty, kitty, WezTerm. We don't bother with the 256-color fallback because Tier FULL only fires when UTF-8 is also detected, which is a stronger filter — any terminal modern enough to ship UTF-8 by default on macOS also has 24-bit color.

The art is byte-equal to `_LOGO_MARK_ART` in `tui.py` so the canonical pose carries forward. No micro-motion here — the installer is one-shot, animation would be wasted complexity vs the splash's continuous-render case.

### Two-column key/value alignment

Fixed-width left column (10 cells) for the label, plain space padding. CJK is not a concern in the installer's step labels — all six labels are pure ASCII (`Host`, `Release`, `Download`, `Verify`, `Install`, `Helper`) so a simple `printf '%-10s' "$label"` works without any cell-width gymnastics.

The two-column layout is FULL/PLAIN only; LOG keeps the existing prose-style `diting install: host detected: darwin-arm64`.

### Where to map the existing 10+ lines to 6 steps

Six steps, each one absorbing several existing `note` calls:

| Step | Label | Absorbs |
|---|---|---|
| 1 | Host | `host detected: darwin-${ARCH}` |
| 2 | Release | `latest release: $VERSION` OR `pinned version: $VERSION (DITING_VERSION env override)` |
| 3 | Download | `downloading $TARBALL_NAME` (with file size appended) |
| 4 | Verify | `sha256 verified: $ACTUAL_SHA` (truncated to first 8 hex chars + `✓`) |
| 5 | Install | `installed to ${INSTALL_PREFIX}`, `symlinked ${BIN_DIR}/diting` |
| 6 | Helper | `helper bundle primed at ${DST_BUNDLE}`, plus the three localised guidance lines (Location/Bluetooth/Notifications prompt order) |

The "guidance lines" in step 6 become continuation lines under the Helper step, indented to align with the value column. The localised EN/ZH branches stay unchanged.

### Why a separate `summary()` block

In today's script the closer is `diting install: diting is on your PATH — run \`diting\`` if the user is set up, or a `Add to ~/.zshrc: …` hint if not. Both look identical to the noise above them. The new summary block makes "Installed." a distinct visual section — the user reads top-to-bottom and immediately knows where to look for next-step actions.

In LOG tier this block is a no-op; the closer goes back to the today-shape line at the script tail.

### Failure path

`die()` keeps its current signature and exit-1 behaviour. The new `die_with_marker` is a thin wrapper that prints the failure marker (`[✗] Step 4/6 failed: <msg>` in FULL/PLAIN, the existing `diting install: error: <msg>` in LOG) before calling `die`. Failure sites in the script change from `die "..."` to `die_with_marker 4 "..."` — the step number is passed explicitly so the failure marker can reference which step blew up.

### Where we explicitly do NOT use color

- `die_with_marker` in LOG tier — keep the exact `diting install: error: ...` shape so error-aware downstream consumers (Homebrew, CI greppers) parse correctly.
- Step values themselves — color is reserved for markers (`✓`/`✗`/checkmark) and the header logo. Values stay default-fg to keep paths / URLs readable.
- Long path strings (e.g. `~/Library/Application Support/diting/diting-tianer.app`) — not colored, not bolded; readability over flair.

## Risks / Trade-offs

[Risk] **`tests/test_install.py` snapshot bytes change**. → Mitigation: tests run in non-TTY by definition (pytest captures stdout) → `detect_tier()` returns `log` → byte-identical output. The 3 new test cases use `script -q /dev/null` (macOS BSD) or a `pty.openpty()` wrapper (Python) to simulate an interactive TTY for the FULL/PLAIN cases, isolated from the existing assertions.

[Risk] **Homebrew cask formula changes output expectations**. → Mitigation: the Homebrew formula consumes `install.sh` via its `installer script` directive, which runs under non-TTY → LOG tier → byte-identical. Verified by grepping the existing brew formula reference (none specific to our output prefix, but tier=log keeps the lines today's parsers expect).

[Risk] **24-bit color escape sequences appear in scroll-back when redirected mid-stream** (e.g. `bash install.sh 2>&1 | tee install.log`). → Mitigation: `tee` connecting stdin from a pipe and stdout to a TTY is an edge case; `[ -t 1 ]` returns false because stdout is a pipe to tee, so we fall to LOG tier and emit plain text. The `.log` file matches what the terminal user saw because both are receiving the same (plain) bytes. Verified by manual one-liner: `bash install.sh | tee /tmp/x.log` produces same output in both surfaces.

[Risk] **Unicode `✓` / `✗` glyphs render as `?` or boxes on terminals that claim UTF-8 but lack glyph coverage**. → Mitigation: extremely rare on macOS (Apple System Font ships glyph coverage); if the user reports a real terminal with the issue, they set `DITING_INSTALL_FORMAT=plain` to opt out, or unset `LANG` to fall to PLAIN automatically.

[Risk] **Tier override env var name conflicts**. → Mitigation: `DITING_INSTALL_FORMAT` is a project-prefixed name; `NO_COLOR` is the standard convention and we honour it.

[Risk] **Installer becomes slower** from the printf overhead. → Mitigation: each `printf` call is sub-millisecond on macOS; the entire output phase costs <50 ms regardless of tier vs the multi-second `curl`/`tar`/`open` work that dominates. No measurable user-visible slowdown.

## Migration Plan

No migration. New runs of `install.sh` automatically pick up the tier ladder based on environment. The only behaviour change visible on interactive macOS terminals is "the output now looks polished"; everywhere else (CI, pipes, Homebrew) output is byte-equal to today.

Rollback: revert the change. No state to migrate; no install artefacts on disk depend on the new format.

## Open Questions

- Should the header tagline include the python version of diting being installed (e.g. `diting installer · v1.7.3 · darwin-arm64`)? **Defer to implementation**: keeping the architecture in step 1 already covers it. The tagline can stay just `diting installer · v1.7.3` for brevity.
- Do we want a `--quiet` flag that suppresses everything but errors? **Out of scope** for this proposal; today's script has no quiet mode and we shouldn't grow the flag surface here.
- Should the failure marker include the step number visually (`[✗] [4/6] Verify failed`) or just the message (`[✗] Verify failed: sha256 mismatch`)? **Defer to implementation**: pick whichever reads better with the existing 6-step layout. Tests pin the marker character and step number presence, not the exact prose.
