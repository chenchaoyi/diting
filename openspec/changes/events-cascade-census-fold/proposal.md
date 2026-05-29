## Why

Two problems on the events surface, both surfaced by the 2026-05-28 `/tui-audit` run against a dense ~36-device office:

1. **"(anonymous)" means two different things on one screen.** The BLE diagnostic strip's `1 anonymous` counts `is_silent_device` (a broadcast carrying *zero* identifying info — no vendor, name, type, device_class, or services). But the event formatters print `· (anonymous)` whenever `event.name` is None, even when the vendor *and* an Apple-decoded device class are known. So a device the BLE list confidently labels `iPhone` shows up in the events modal as `Apple, Inc. · (anonymous)`. A user reading `1 anonymous` in the strip then seeing ~20 `(anonymous)` event lines gets contradictory signals, and the events are strictly *less* informative than the list because `BLEDeviceSeenEvent` / `BLEDeviceLeftEvent` never carried the `type` / `device_class` the list cascade uses.

2. **The at-launch census buries the genuinely interesting events.** The v1.8.0 cluster merger cut the BLE event flood from 100+ → ~27, but the residual is still dominated by the *startup census*: every device already in the room when diting launches fires one `seen` in the first ~5 s. The high-signal events (AirPods connecting, an inter-AP roam, an RF stir, a device that actually walks in or out mid-session) are buried among ~20 already-present-at-launch rows.

Neither fix hides anything — the design constraint from the user is that *every device that could be hidden must still be knowable*. The events become richer (Part A) and the launch burst becomes scannable but fully expandable (Part B).

## What Changes

**Part A — event display cascade + terminology unification**

- `BLEDeviceSeenEvent` / `BLEDeviceLeftEvent` gain `device_type: str | None` and `device_class: str | None`, populated by the poller from the cluster representative's `BLEDevice.type` / `.device_class`.
- The BLE event formatters (live `EventsPanel` and the `m` modal, which share `_format_ble_device_seen_event` / `_left`) mirror the BLE *list* name cascade: helper name → `(rotating ID)` for high-entropy names → `device_type` (e.g. *Find My target*) → `device_class` (e.g. *iPhone*) → placeholder.
- The placeholder is `(anonymous)` only when the event carries no vendor, no name, no type, no device_class, and no service categories — matching `is_silent_device`. Otherwise `(unknown)`. "(anonymous)" now means the same thing on every diting surface.
- The event-log JSONL gains optional `device_type` / `device_class` keys (omitted when None, per the existing convention). The device's Continuity type serializes under `device_type`, NOT `type`, because the JSONL envelope already uses `type` for the event kind.

**Part B — at-launch census fold (Layer 2, no hiding)**

- `BLEDeviceSeenEvent` gains `at_launch: bool`. The poller marks advertising-device seens `True` during a fixed startup warmup window (default ~12 s, one tunable constant) and `False` thereafter. Connected-peripheral seens are always `at_launch=False` (a bonded peripheral present at start is high-signal, never census).
- The `EventsScreen` modal folds all contiguous `at_launch=True` BLE seens into **one expandable summary row**: `session start · N devices already present (Apple ×8 · Microsoft ×5 · …)`. Pressing Enter / → on the row expands it to the individual cascade-formatted rows; collapse re-folds. Default state is collapsed.
- Genuine post-launch seens/lefts (`at_launch=False`) render individually as today. The live `EventsPanel` stream is unchanged in structure (it applies the Part A cascade but does not fold — folding a streaming panel is out of scope).
- The JSONL log records **every** event including the at-launch ones (optional `at_launch: true` key when set); the fold is render-only. `DITING_BLE_EVENT_MERGER=0` continues to disable the upstream cluster merge; a device that wants the raw unfolded modal can expand the summary row.

## Capabilities

### New Capabilities
<!-- none -->

### Modified Capabilities
- `events`: `BLEDeviceSeenEvent` / `BLEDeviceLeftEvent` gain `device_type` / `device_class`; `BLEDeviceSeenEvent` gains `at_launch`. JSONL serialisation gains the matching optional keys (None-omitted; device type under `device_type`).
- `bluetooth-scanning`: the BLE poller populates `device_type` / `device_class` on every emitted transition event from the cluster representative, and tracks a launch-phase window to set `at_launch` on seens.
- `tui-shell`: the `[BLE]` event format follows the list name cascade and the unified `(anonymous)`/`(unknown)` placeholder rule; `EventsScreen` folds at-launch BLE seens into one expandable summary row.
- `i18n`: new EN+ZH strings for the census summary row (`session start`, `N devices already present`, vendor-count breakdown separator, expand/collapse hint).

## Impact

- **Code**: `src/diting/events.py` (two dataclasses), `src/diting/ble.py` (4 event-construction sites + launch-phase tracking), `src/diting/tui.py` (`_format_ble_device_seen_event` / `_left` cascade, `_ble_seen_name_label`, a census-fold grouping + EventsScreen expand/collapse interaction), `src/diting/event_log.py` (2 JSONL emitters), `src/diting/i18n.py` (new keys EN+ZH).
- **JSONL contract**: additive only — new keys are optional and None-omitted; existing consumers correlating seen↔left by `identifier` are unaffected. Not a breaking change.
- **Tests**: `tests/test_ble.py` (poller populates new fields + at_launch window), `tests/test_events.py` / event-log tests (JSONL keys), `tests/` TUI formatter + EventsScreen fold tests. `tests/TESTING.md` (EN) + `docs/zh/TESTING.md` (ZH) updated first.
- **Docs**: `README.md` / `docs/zh/README.md` events-modal description if it mentions the anonymous flood; CHANGELOG EN+ZH.
- **No permission-surface change. No helper-schema change.**
