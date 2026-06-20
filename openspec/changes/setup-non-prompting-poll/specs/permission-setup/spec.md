## MODIFIED Requirements

### Requirement: `diting setup` SHALL drive and verify the helper's TCC grants

`diting setup` SHALL locate (or build) the Swift helper, open its `.app` bundle
so macOS surfaces the Location → Bluetooth → Notifications prompts, and then
verify the outcome by probing each grant. It SHALL block-and-verify the two
grants required for core function — Location (Wi-Fi scan list) and Bluetooth
(BLE view) — polling until both are granted or a bounded timeout elapses, and
SHALL drive the Notifications prompt as best-effort (never blocking on it).
`setup` SHALL print live per-permission status as each grant lands. It SHALL NOT
claim to grant permissions itself — macOS requires the user's Allow click; setup
only drives the prompts and verifies.

`setup` SHALL verify each grant using READ-ONLY status probes (which neither
prompt the user nor power the radio), so that the ONLY source of TCC prompts is
the opened helper bundle's GUI — which requests the three grants one at a time,
waiting for the user's decision on each. `setup`'s verification poll SHALL NOT
itself trigger a TCC prompt; the user SHALL never see duplicate or stacked
prompts, regardless of how long they take to respond. When the running helper
predates the read-only probes, `setup` MAY fall back to the functional probes
(preserving function on an older helper).

#### Scenario: All required grants land
- **WHEN** the user runs `diting setup` and clicks Allow on Location and Bluetooth
- **THEN** setup reports both granted and exits 0

#### Scenario: A required grant never lands before timeout
- **WHEN** the user runs `diting setup` and never grants Bluetooth within the timeout
- **THEN** setup reports Bluetooth still missing, prints what to do, and exits non-zero

#### Scenario: Slow user sees no stacked prompts
- **WHEN** the user runs `diting setup` and reads each macOS prompt slowly before clicking Allow
- **THEN** only the helper GUI's prompts appear, one at a time; setup's verification poll never adds a second Location or Bluetooth prompt on top
