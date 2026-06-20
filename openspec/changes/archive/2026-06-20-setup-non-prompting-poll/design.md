## Context

The helper's `HelperAppDelegate` (GUI launch) sequences the three prompts
correctly: it requests Location, and only on the Location auth callback does it
init `CBCentralManager` (Bluetooth prompt), and only on the Bluetooth callback
does it call `UNUserNotificationCenter.requestAuthorization` (Notifications) — so
the GUI shows at most one prompt at a time and waits for the user. The bug is
entirely on the `setup` (Python) side: its verification poll runs `scan`
(`requestWhenInUseAuthorization`) and `bluetooth-status` (`CBCentralManager`),
both of which re-fire prompts.

## Goals / Non-Goals

**Goals:**
- `setup` verifies without ever firing a prompt → only the helper GUI prompts,
  one at a time, at the user's pace.
- Clean `setup` output (no scene banner, concise status).

**Non-Goals:**
- Changing the helper GUI grant sequencing (already correct).
- Changing `scan` / `bluetooth-status` (functional checks used elsewhere).
- Rewiring the TUI's `_ensure_helper_ready` (separate; out of scope here).

## Decisions

### D1 — Read-only probes, not new prompts
Add `location-status` (reads `CLLocationManager().authorizationStatus`) and
`bluetooth-authorization` (reads `CBManager.authorization`). Both are property
reads — they do not call `requestWhenInUseAuthorization`, do not instantiate a
live `CBCentralManager`, and do not power the radio, so they never prompt. Exit
0 when authorized (`authorizedWhenInUse`/`authorizedAlways`;
`allowedAlways`), non-zero otherwise. Same disclaim hop as the other probes so
TCC attributes to the bundle. macOS deploy target is v11 — both APIs are available.

  Alternative considered: change `bluetooth-status` to a pure auth read.
  Rejected — it doubles as the BLE-readiness check (needs `.poweredOn`, i.e.
  authorized AND radio on); a separate `bluetooth-authorization` keeps both
  meanings.

### D2 — `setup` polls read-only; degrade gracefully
`permission.probe()` uses the read-only probes for Location and Bluetooth when
the helper advertises them (`--help` grep, like the notification-status gate),
and otherwise falls back to the existing prompting probes — so `setup` still
works (with the old imperfect prompting) against an older installed helper, and
runs clean once the patch's rebuilt helper is in place. The Notifications check
is already read-only.

### D3 — Quiet the scene banner for `setup`
The scene-detection banner (`auto-detected scene: …`) is resolved in `_dispatch`
for every command and is irrelevant to `setup`. Suppress its emission when the
dispatched command is `setup` (the scene-resolution machinery is untouched; only
the banner print is gated). Keeps the install output focused on the grant flow.

## Risks / Trade-offs

- [Read-only auth status differs from the functional scan check] → For "did the
  user grant?", authorization status is the correct signal and matches the click;
  the TUI keeps the functional scan check for "is the scan unredacted". Both valid.
- [Older installed helper lacks the new probes] → Graceful fallback to the
  current prompting probes (no worse than today); the common path after the patch
  upgrade is clean.
- [Helper rebuild needed] → Same release mechanics as the prior helper change;
  CI builds the universal2 helper.

## Migration Plan

1. Land the helper probes + Python read-only polling + banner gate.
2. Patch release (v2.0.1) ships the rebuilt helper; upgraded installs poll clean.

## Open Questions

- None.
