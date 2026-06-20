## Why

`diting setup` (shipped in v2.0.0) drives the macOS permission prompts by opening
the helper bundle — whose GUI correctly sequences Location → Bluetooth →
Notifications one at a time — but then VERIFIES by polling every 2 s with probes
that *themselves re-trigger prompts*: `has_permission` runs the helper's `scan`
(which calls `requestWhenInUseAuthorization()`) and `has_bluetooth_permission`
runs `bluetooth-status` (which instantiates a `CBCentralManager`). So while the
user is reading the helper's prompt, `setup`'s poll fires DUPLICATE Location /
Bluetooth prompts that stack on top of each other — worse the slower the user
reads. The fix is to make `setup` observe with read-only authorization checks so
the only thing prompting is the helper GUI, which already waits for the user on
each grant.

## What Changes

- Add two **read-only** TCC status probes to the Swift helper that NEITHER
  prompt NOR power the radio:
  - `location-status` — reads `CLLocationManager.authorizationStatus`;
  - `bluetooth-authorization` — reads `CBManager.authorization`.
  (`notification-status` is already read-only.) The existing `scan` /
  `bluetooth-status` subcommands — which the TUI and BLE readiness rely on for
  *functional* checks — are unchanged.
- `diting setup` polls these read-only probes instead of the prompting ones, so
  it waits for the user at their own pace and the helper GUI is the sole source
  of prompts (one at a time, no stacking). The Python probes used by `setup`
  prefer the read-only subcommands and **degrade gracefully** to the old probes
  when run against an older helper that lacks them.
- Tidy the `setup` output: suppress the irrelevant scene-detection banner for the
  `setup` command, and keep the per-permission status concise.

## Capabilities

### New Capabilities
<!-- none -->

### Modified Capabilities
- `macos-helper`: add the read-only `location-status` and `bluetooth-authorization`
  probe subcommands.
- `permission-setup`: `setup` SHALL verify via read-only status polling so the
  helper GUI is the only prompter and grants are handled one at a time, waiting
  for the user — no duplicate / stacked prompts.

## Impact

- `helper/Sources/diting-tianer/main.swift` — `location-status` +
  `bluetooth-authorization` subcommands (exit-code only; listed in `--help`). No
  JSON / schema change. Helper rebuild → ships in the next (patch) release.
- `src/diting/_helper.py` — `location_authorized` / `bluetooth_authorized` (read
  the new probes) + `has_location_status_subcommand` /
  `has_bluetooth_authorization_subcommand` detection for graceful degradation.
- `src/diting/permission.py` — `probe()` uses the read-only probes when
  available, else falls back.
- `src/diting/cli.py` — suppress the scene banner for `setup`; minor display tidy.
- `tests/` — `test_setup.py` (probe prefers read-only; degradation) +
  `test_helper.py` (new probe parsing). Update `tests/TESTING.md` (EN + ZH) first.
- No docs surface change beyond a TESTING.md note; behaviour, not API.
