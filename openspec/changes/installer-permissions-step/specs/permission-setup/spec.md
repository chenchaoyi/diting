## MODIFIED Requirements

### Requirement: `diting setup` SHALL drive and verify the helper's TCC grants

`diting setup` SHALL locate (or build) the Swift helper, open its `.app` bundle
so macOS surfaces the Location → Bluetooth → Notifications prompts, and then
verify the outcome by probing each grant. It SHALL block-and-verify the two
grants required for core function — Location (Wi-Fi scan list) and Bluetooth
(BLE view) — polling until both are granted or a bounded timeout elapses, and
SHALL drive the Notifications prompt as best-effort (never blocking on it
indefinitely). `setup` SHALL print live per-permission status as each grant
lands. It SHALL NOT claim to grant permissions itself — macOS requires the user's
Allow click; setup only drives the prompts and verifies.

`setup`'s live status SHALL show all three permissions — Location, Bluetooth, and
Notifications — reading each as a distinct status (granted / pending / denied) so
a not-yet-answered prompt is shown as waiting, not as denied. Because the helper
requests Notifications LAST (after the required two), `setup` SHALL NOT exit the
instant the required grants land while the Notifications prompt is still pending:
after the required grants are present, `setup` SHALL wait a bounded grace for the
best-effort Notifications grant to settle (granted or denied) before reporting
the final state, then exit regardless of the Notifications outcome (it remains
non-blocking — the grace is bounded). When the helper cannot verify Notifications
(an older helper without the probe), `setup` SHALL NOT wait.

In interactive mode `setup` SHALL open the helper bundle PROMPTLY — before
running any blocking verification probe — so the permission window appears
without waiting on a slow status read. The readiness pre-check that decides
whether grants are already complete SHALL NOT stall the window's appearance:
it SHALL use a short Location settle bound so a not-yet-granted system is
recognized quickly. The accurate (default-settle) read SHALL still be used for
`--json` / non-interactive reporting.

`setup` SHALL verify each grant using READ-ONLY status probes (which neither
prompt the user nor power the radio), so that the ONLY source of TCC prompts is
the opened helper bundle's GUI — which requests the three grants one at a time,
waiting for the user's decision on each. `setup`'s verification poll SHALL NOT
itself trigger a TCC prompt; the user SHALL never see duplicate or stacked
prompts, regardless of how long they take to respond. When the running helper
predates the read-only probes, `setup` MAY fall back to the functional probes
(preserving function on an older helper).

When the `DITING_SETUP_INDENT` environment variable is set to a non-negative
integer, `setup` SHALL left-pad every line of its human-readable terminal output
by that many spaces, so an embedding context (the installer) can align the setup
output within its own frame. The machine-readable `--json` output SHALL NOT be
indented.

#### Scenario: All required grants land
- **WHEN** the user runs `diting setup` and clicks Allow on Location and Bluetooth
- **THEN** setup reports both granted and exits 0

#### Scenario: A required grant never lands before timeout
- **WHEN** the user runs `diting setup` and never grants Bluetooth within the timeout
- **THEN** setup reports Bluetooth still missing, prints what to do, and exits non-zero

#### Scenario: Notifications is shown and given a chance to settle
- **WHEN** the user grants Location and Bluetooth and the Notifications prompt is still pending
- **THEN** setup's live status shows Notifications as waiting (not denied), and setup waits a bounded grace for the Notifications outcome before reporting and exiting

#### Scenario: Slow user sees no stacked prompts
- **WHEN** the user runs `diting setup` and reads each macOS prompt slowly before clicking Allow
- **THEN** only the helper GUI's prompts appear, one at a time; setup's verification poll never adds a second Location or Bluetooth prompt on top

#### Scenario: Permission window appears promptly
- **WHEN** the user runs `diting setup` on a fresh install where Location is not yet granted
- **THEN** the helper permission window appears promptly rather than after a multi-second status-probe stall

#### Scenario: Output is indented under the installer
- **WHEN** the installer runs `diting setup` with `DITING_SETUP_INDENT` set
- **THEN** setup's printed lines are left-padded to align under the installer's helper step
- **AND** `diting setup --json` output is not indented
