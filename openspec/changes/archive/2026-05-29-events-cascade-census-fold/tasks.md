## 1. Test plan first (TESTING.md before code — hard rule 4)

- [x] 1.1 Add the new test cases to `tests/TESTING.md` (EN, canonical): event dataclass fields, poller populates device_type/device_class + at_launch window, JSONL optional keys (device_type not type), event formatter cascade + (anonymous)/(unknown) split, EventsScreen census fold + expand/collapse, i18n EN↔ZH parity for census strings.
- [x] 1.2 Mirror the same additions into `docs/zh/TESTING.md` (ZH) in the same edit pass — keep EN↔ZH parity.

## 2. Event data model (`src/diting/events.py`)

- [x] 2.1 Add `device_type: str | None = None` and `device_class: str | None = None` to `BLEDeviceSeenEvent`; add `at_launch: bool = False`. Keep the dataclass frozen + slots.
- [x] 2.2 Add `device_type: str | None = None` and `device_class: str | None = None` to `BLEDeviceLeftEvent` (no `at_launch`).

## 3. Poller emission (`src/diting/ble.py`)

- [x] 3.1 Add module-level `_LAUNCH_WARMUP_S = 12.0` constant with a short why-comment (startup census window).
- [x] 3.2 Record `self._started_at` at `BLEPoller` construction; compute `at_launch = (now - self._started_at) < _LAUNCH_WARMUP_S` for advertising-device seens.
- [x] 3.3 Fresh-cluster seen site (~`ble.py:1833`): pass `device_type=dev.type, device_class=dev.device_class, at_launch=<window>`.
- [x] 3.4 Connected-peripheral seen site (~`ble.py:1851`): pass `device_type=dev.type, device_class=dev.device_class, at_launch=False` (never census).
- [x] 3.5 Full-cluster-departure left site (~`ble.py:1908`): pass `device_type=dev.type, device_class=dev.device_class`.
- [x] 3.6 Fallback per-identifier left site (~`ble.py:1927`): pass `device_type=dev.type, device_class=dev.device_class`.

## 4. JSONL serialisation (`src/diting/event_log.py`)

- [x] 4.1 `emit_ble_device_seen`: add `device_type` / `device_class` keys when not None, and `at_launch` key when True. Device type under key `device_type` (NOT `type`).
- [x] 4.2 `emit_ble_device_left`: add `device_type` / `device_class` keys when not None.

## 5. Display cascade + terminology unification (`src/diting/tui.py`)

- [x] 5.1 Extract a shared name-resolver (e.g. `_ble_display_label(name, device_type, device_class)`) implementing the cascade name → `(rotating ID)` → device_type → device_class → fallback; refactor `_ble_row_line` (`tui.py:3572-3591`) to call it so the list and events share one path.
- [x] 5.2 Add a shared `(anonymous)` vs `(unknown)` decider usable from an event's own fields (`vendor`, `name`, `device_type`, `device_class`, `service_categories`) approximating `is_silent_device`.
- [x] 5.3 Rewrite `_format_ble_device_seen_event` (`tui.py:2144`) to use the cascade + placeholder decider instead of `_ble_seen_name_label` name-only.
- [x] 5.4 Rewrite `_format_ble_device_left_event` (`tui.py:2174`) the same way (replace `event.name or "(anonymous)"`).
- [x] 5.5 Update `_ble_seen_name_label` (`tui.py:2129`) to the cascade so consecutive-duplicate grouping keys on the displayed label.

## 6. At-launch census fold (`src/diting/tui.py`)

- [x] 6.1 Add a census-fold grouping pass (sibling to `_group_consecutive_ble_seen`) that collapses each contiguous run of `at_launch=True` BLE seens into one synthetic summary node carrying the folded events + vendor-count breakdown (top 3 + overflow).
- [x] 6.2 Render the summary row: `session start · {n} devices already present (vendor ×count …)` with the expand/collapse hint; wire it into `EventsScreen` rendering.
- [x] 6.3 Add `EventsScreen` Enter/`→` toggle of `_census_expanded` (default collapsed); expanded renders the individual cascade rows in place beneath the summary. Fold respects the `[5] BLE` filter (folds after filtering) and disappears when BLE seens are filtered out.

## 7. i18n strings (`src/diting/i18n.py`)

- [x] 7.1 EN keys resolve via `t()`-returns-key (no `_EN` dict in this project); `×{n}` marker handled inline (language-neutral).
- [x] 7.2 Add the matching ZH values per the i18n delta spec table (EN↔ZH parity in the same edit).

## 8. Tests

- [x] 8.1 `tests/test_events.py`: seen/left carry device_type/device_class/at_launch; JSONL emits device_type (not type), device_class, at_launch only when set; None/False omitted (via both `event_to_jsonl` round-trip and `EventLogger.emit_*`).
- [x] 8.2 `tests/test_ble.py`: poller populates device_type/device_class from the representative; at_launch True inside window / False after / always False for connected peripherals (advance a fake clock).
- [x] 8.3 `tests/test_tui_helpers.py` formatter tests: cascade falls back name→type→class; `(anonymous)` only when truly silent, `(unknown)` when vendor present but nothing else.
- [x] 8.4 `tests/test_tui_helpers.py` census fold: at-launch run folds to one summary row with correct count + top-3 breakdown; expand/collapse hint flips; mid-session seen stays individual; respects BLE filter; JSONL untouched.
- [x] 8.5 i18n parity test: every new EN census key has a ZH value with placeholders preserved.

## 9. Docs

- [x] 9.1 README assessed: line 66 describes the BLE *list* cascade (unchanged, still accurate); the README does not document events-modal internals, so no edit needed.
- [x] 9.2 Add a CHANGELOG entry under `[Unreleased]` (EN `CHANGELOG.md` + ZH `docs/zh/CHANGELOG.md`) summarising Part A + Part B.

## 10. CI gates (hard rule 3)

- [x] 10.1 `uv run pytest` green — 1135 passed (+24 new).
- [x] 10.2 `uv run python scripts/tui_snapshot.py --mode regression` clean — 16 scenarios, 48 asserts, 0 failed.
- [x] 10.3 `openspec validate --specs --strict` (22/22) and `openspec validate events-cascade-census-fold --type change --strict` both pass.
