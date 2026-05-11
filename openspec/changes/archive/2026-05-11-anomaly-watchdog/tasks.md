## 1. Test plan first (test-first discipline)

- [x] 1.1 Add a new `## ### \`anomaly-watchdog\`` section to
      `tests/TESTING.md` with one row per Requirement in the new
      capability spec (3 Requirements → 3 rows). Each row points at
      the new `tests/test_watchdog.py` test names.
- [x] 1.2 Mirror to `docs/zh/TESTING.md`.

## 2. New module `src/diting/_watchdog.py`

- [x] 2.1 `class WatchdogConfig` — frozen dataclass with two fields:
      `silence_window_s: int` (default 60), `stir_confidence: str`
      (default `"high"`). One classmethod `from_env(env=None)` that
      reads `DITING_NOTIFY_SILENCE_S` and
      `DITING_NOTIFY_STIR_CONFIDENCE`, validates, and falls back to
      defaults with a stderr warning on invalid input.
- [x] 2.2 Validation: `silence_window_s` must be int in `[3, 3600]`;
      `stir_confidence` must be one of `{"high", "medium", "all"}`.
      Print warnings via `print(..., file=sys.stderr)` so a daemon-
      style deployment can pipe stderr to its log.
- [x] 2.3 `class SilenceClock` — `__init__(window_s)`, method
      `should_fire(kind: str, target: str, now: float) -> bool`.
      Uses `time.monotonic` (already imported in cli.py for a
      sibling closure) — no `datetime.now`, to avoid clock-skew bugs.
- [x] 2.4 `def should_notify_stir(payload: dict, gate: str) -> bool`
      — pure function. `gate="high"` → returns `payload["confidence"] == "high"`;
      `gate="medium"` → returns `payload["confidence"] in ("medium", "high")`;
      `gate="all"` → returns True.

## 3. Wire watchdog into `cli.py:_run_monitor` (headless call site)

- [x] 3.1 At the top of `_run_monitor`, after `notify = "--notify" in args`,
      construct `watchdog_cfg = WatchdogConfig.from_env()` and
      `silence_clock = SilenceClock(watchdog_cfg.silence_window_s)`.
- [x] 3.2 Rewrite `maybe_notify` to take `(payload: dict, target: str)`
      and apply the new logic:
        - bail early if `not notify`
        - if `payload["type"] == "rf_stir"`: require
          `should_notify_stir(payload, watchdog_cfg.stir_confidence)`
        - otherwise: any event type is eligible
        - require `silence_clock.should_fire(payload["type"], target, time.monotonic())`
        - then call `_macos_notify(...)`.
- [x] 3.3 Update the two `wifi_consumer` `rf_stir` call sites to pass
      `target=stir.location`.
- [x] 3.4 Add `maybe_notify` calls in `latency_consumer` for both
      `latency_spike` and `loss_burst` — they should fire AFTER the
      existing `should_fire(...)` check (which is the JSONL-emission
      cooldown) so the JSONL detector debouncing and the
      notification debouncing remain independent. Pass
      `target=sample.target` for both.

## 3b. Wire watchdog into TUI (interactive call site)

- [x] 3b.1 Add `--notify` flag parsing to the default TUI subcommand
      dispatch in `cli.py` (the path that constructs `DitingApp`).
      Pass `notify=True` into the constructor.
- [x] 3b.2 Extend `DitingApp.__init__` with a `notify: bool = False`
      parameter. When True, construct `WatchdogConfig.from_env()` and
      `SilenceClock(...)` once at startup and stash them as instance
      attrs `_watchdog_cfg` and `_silence_clock`.
- [x] 3b.3 In the TUI's event-ingest handlers (where events get
      appended to `EventRing` / written via `EventLogger`), call
      into `_maybe_notify(payload, target)` — an instance method
      that reuses the same `_watchdog.maybe_notify` helper as
      `_run_monitor`. Three call sites mirror the monitor wire-up:
      `rf_stir` (from EnvironmentMonitor), `latency_spike` and
      `loss_burst` (from latency events). Use `osascript` via the
      same `_macos_notify` helper.
- [x] 3b.4 Confirm `diting --help` (or however help is surfaced)
      doesn't lie about the flag scope — update inline help / `Help`
      modal text if it currently says `--notify` is monitor-only.

## 4. Tests in `tests/test_watchdog.py`

- [x] 4.1 `test_silence_clock_first_fire_returns_true` — fresh clock,
      first call for any `(kind, target)` returns True.
- [x] 4.2 `test_silence_clock_second_fire_within_window_returns_false`
      — same `(kind, target)` within the window returns False.
- [x] 4.3 `test_silence_clock_second_fire_after_window_returns_true`
      — clock parameterised on `now`, second call past the window
      returns True.
- [x] 4.4 `test_silence_clock_independent_per_tuple` — different
      `target` for same `kind` is independent; different `kind` for
      same `target` is independent.
- [x] 4.5 `test_should_notify_stir_default_gate` — `gate="high"` only
      passes high-confidence payloads.
- [x] 4.6 `test_should_notify_stir_medium_gate` — `gate="medium"`
      passes medium and high; rejects low/missing.
- [x] 4.7 `test_should_notify_stir_all_gate` — `gate="all"` passes
      everything including missing-confidence payloads.
- [x] 4.8 `test_watchdog_config_defaults_when_env_unset` — empty env
      → silence_window_s=300, stir_confidence="high".
- [x] 4.9 `test_watchdog_config_parses_valid_env` — valid integers
      and enum values are accepted.
- [x] 4.10 `test_watchdog_config_falls_back_on_invalid_silence`
      (string, out-of-range int) — default + stderr warning.
- [x] 4.11 `test_watchdog_config_falls_back_on_invalid_stir_gate`
      (typo) — default + stderr warning. Capture stderr via
      pytest's `capsys`.

## 5. CHANGELOG

- [x] 5.1 `CHANGELOG.md` `[Unreleased]` → `### Added` block:
      one entry for `--notify` watchdog expansion. Mention the
      three event types now covered, the silence-window default,
      and the two new env vars.
- [x] 5.2 `docs/zh/CHANGELOG.md` mirror.

## 6. Self-test + ship

- [x] 6.1 `uv run pytest` — expect 399 + ~11 new unit cases + ~1
      TUI smoke case = ~411 pass.
- [x] 6.2 `uv run python scripts/tui_snapshot.py --mode regression --check`
      — 16/16 (synthetic fixtures don't exercise the notification
      code path).
- [x] 6.3 `openspec validate --specs --strict` — 15/15 (canonical
      specs unchanged by this branch; the new `anomaly-watchdog`
      capability spec and `cli` ADDED Requirement don't land in
      canonical until archive).
- [x] 6.4 `openspec validate anomaly-watchdog --strict` — change
      valid.
- [ ] 6.5 Commit (explicit `git add <files>` — no `git add -A` after
      the meeting-notes incident), push, open PR.

## 7. Post-merge

- [ ] 7.1 `openspec archive anomaly-watchdog` — applies:
        - the new `anomaly-watchdog` capability spec under canonical
          `openspec/specs/anomaly-watchdog/spec.md`
        - the ADDED `cli` Requirement (`--notify` flag valid on
          both subcommands)
