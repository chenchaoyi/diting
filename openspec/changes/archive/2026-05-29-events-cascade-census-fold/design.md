## Context

The events surface has three rendering layers that drifted apart:

- **BLE list** (`_ble_row_line`, `tui.py:3552`) resolves a device's display name with a cascade: helper `name` → `(rotating ID)` for high-entropy names → Continuity `type` (*Find My target*, *MS device beacon*) → Nearby-Info `device_class` (*iPhone*, *Mac*) → `(unknown)`; and distinguishes `(anonymous)` (`is_silent_device`, `ble.py:193`) from `(unknown)`.
- **Event formatters** (`_format_ble_device_seen_event` / `_left`, `tui.py:2144`) only do `event.name or "(anonymous)"` — because `BLEDeviceSeenEvent` / `BLEDeviceLeftEvent` (`events.py:96`) never carried `type` / `device_class`. So events are less informative than the list and overload "(anonymous)".
- **Diagnostic strip** (`tui.py:2749`) counts `is_silent_device` for its `N anonymous` figure — the strict definition.

Part A re-aligns the event formatters with the list cascade and the strict `(anonymous)` definition. Part B addresses the *volume* problem the v1.8.0 cluster merger left behind: the startup census burst. The poller's `_detect_transitions` (`ble.py:~1790`) fires a `seen` for every device that graduates the presence gate; at launch, the entire visible population graduates in the first few polls, producing a 5-second burst of ~20 seens that buries genuine mid-session transitions.

Hard constraint from the user (2026-05-28): **do not hide anything.** Every device that "could be hidden" must remain knowable. Part B therefore *folds and labels*, never suppresses; the JSONL log keeps every event.

## Goals / Non-Goals

**Goals:**
- One meaning of `(anonymous)` across diagnostic strip, BLE list, and events — the `is_silent_device` definition.
- Events carry and display the same `type` / `device_class` the list already uses, so a device shown as `iPhone` in the list reads `iPhone` in the events.
- The at-launch census collapses to a single expandable summary row in the `m` modal; one keystroke reveals every folded device.
- Additive JSONL only; existing seen↔left identifier correlation unchanged.

**Non-Goals:**
- Folding the *live* streaming `EventsPanel` (the always-on bottom panel). Folding a streaming append-only panel means mutating already-rendered rows — out of scope. The live panel gets Part A's cascade but not Part B's fold.
- Changing the upstream cluster-merge fingerprint or the `(merged N)` badge (v1.8.0, working).
- Any new filter bucket or keybinding beyond the census-row expand toggle.
- Hiding, suppressing, or default-collapsing any *non*-census events.

## Decisions

### D1 — Event field names: `device_type` (not `type`), `device_class`
The dataclass and JSONL field for the Continuity advertisement type is **`device_type`**, not `type`. Rationale: the event-log JSONL envelope already uses the key `"type"` for the event *kind* (`"ble_device_seen"`). Reusing `type` for the device's Continuity type would collide in the serialized line. `device_class` has no collision and keeps the `BLEDevice` field name. Alternative considered: serialize the device type under `adv_type` — rejected as less self-documenting than `device_type`. The in-memory dataclass field matches the JSONL key (`device_type`) even though the source attribute is `BLEDevice.type`, so the populate line reads `device_type=dev.type`.

### D2 — Display cascade lives in one shared helper
Extract the list's name-resolution cascade into a single function (e.g. `_ble_display_name(name, type, device_class) -> (text, is_silent_fallback)`) used by BOTH `_ble_row_line` and the event formatters, so the two paths cannot drift again (same discipline as v1.8.0's shared `_RSSI_WINDOW_DB` constant). The placeholder decision — `(anonymous)` vs `(unknown)` — is computed from the fields the *caller* has:
- List: full `BLEDevice`, uses `is_silent_device(d)`.
- Event: approximate `is_silent` from the event's own fields — `vendor is None and not name and not device_type and not device_class and not service_categories`. This matches `is_silent_device` for everything the event carries (the event lacks `vendor_id` and raw `services`, but `service_categories` is the resolved form and `vendor` already folds `vendor_id`; a device with a company-id but no resolved vendor is vanishingly rare and would read `(unknown)`, the safe side).

`_ble_seen_name_label` (used for grouping keys) is updated to the same cascade so the consecutive-duplicate RLE still groups correctly.

### D3 — `at_launch` is a fixed wall-clock window on the poller
The poller records `self._started_at` at construction. A seen is `at_launch = (now - self._started_at) < _LAUNCH_WARMUP_S`, default **12 s** (covers the splash + first scan-settle; one module-level tunable constant). Chosen over alternatives:
- *"First poll only"* — too narrow; BLE discovery trickles devices in over ~10 s, so half the census would arrive after poll 1.
- *"Until the visible set stops growing"* — fragile against bursty discovery; not deterministically testable.
- Fixed window is deterministic, one constant, trivially testable by advancing a fake clock.

Connected-peripheral seens (`ble.py:1851`) are hard-coded `at_launch=False` — a bonded peripheral is high-signal regardless of timing. After the window closes, `at_launch` is permanently False for the session (a device arriving at minute 5 is a real arrival).

### D4 — Census fold is a render-only grouping in `EventsScreen`
A new grouping pass (sibling to `_group_consecutive_ble_seen`) collapses the contiguous run of `at_launch=True` BLE seens into one synthetic summary node carrying the folded events. The summary row renders `session start · {N} devices already present ({vendor} ×{count} · …)` with the vendor breakdown sorted by descending count (top ~3 vendors, then `· …` if more). The row is selectable; Enter / → toggles an `expanded` flag stored on the `EventsScreen` (keyed by the fold node) — expanded re-renders the individual cascade-formatted rows in place, collapsed shows the summary. Default collapsed.

Interaction detail: `EventsScreen` already supports modal scrolling; the fold adds one selectable node + an Enter/→ handler. If the run is interrupted by a non-at_launch event (rare — a real arrival during the warmup window), each contiguous at_launch run folds separately. The `[5] BLE` filter shows the same fold (the bucket filters by event type, fold is orthogonal).

### D5 — JSONL is additive and None-omitted
`emit_ble_device_seen` / `_left` add `device_type` / `device_class` only when not None, and `at_launch` only when True (seen only). This matches the existing "omit None fields" requirement and the "byte-identical for unchanged inputs minus the new signal" expectation. A consumer that never read these keys is unaffected.

## Risks / Trade-offs

- **[Cascade changes the grouping key]** → `_ble_seen_name_label` feeds the consecutive-duplicate RLE; switching it from name-only to the full cascade means two devices that both fell back to `(anonymous)` before might now group differently (one `iPhone`, one `(anonymous)`). This is *more* correct (they are different devices) but changes existing fold counts. Mitigation: a test pins the new grouping behavior; the audit's `×N` rows were already noisy, so finer grouping is an improvement.
- **[12 s warmup window mis-tags a fast real arrival]** → A device that genuinely walks in at second 8 gets folded into the census. Mitigation: acceptable — at 8 s the user is still in startup; the summary is one keystroke from showing it, and nothing is lost from the JSONL. The constant is tunable if real use shows the window too long.
- **[Census fold interaction complexity]** → expand/collapse state on a modal is more than the v1.7.2 RLE. Mitigation: state is a single dict on `EventsScreen`, render-only, no EventRing mutation; a smoke test drives the toggle.
- **[`is_silent` approximation in event formatter diverges from `is_silent_device`]** → the event lacks `vendor_id`/raw `services`. Mitigation: D2 shows the approximation only differs for a company-id-present-but-vendor-unresolved device, which renders `(unknown)` (the conservative, non-anonymous side) — no false `(anonymous)`.

## Migration Plan

Pure additive in-process change; no data migration. Rollback = revert the branch. Old JSONL files (without the new keys) continue to parse — the TUI's `decode`/load path already tolerates absent optional fields (schema-tolerance convention). `DITING_BLE_EVENT_MERGER=0` remains the escape hatch for users who want per-identifier seen/left; the census fold is independent and always expandable.

## Open Questions

- Should the summary row's vendor breakdown cap at top-3 vendors or show all? → Default top-3 + `· …`; revisit if a real capture shows it reads poorly. (Resolved as top-3 for v1; cheap to widen later.)
