## MODIFIED Requirements

### Requirement: `setup` SHALL recover a previously-denied grant by opening System Settings

`setup` SHALL distinguish a grant that is merely PENDING (not yet answered —
macOS `notDetermined`) from one that is SETTLED-denied (`denied` / `restricted`,
which macOS will not re-prompt), using the read-only probes' distinct exit codes.
While a required grant is pending, `setup` SHALL keep waiting for the helper's
prompt — it SHALL NOT call it denied and SHALL NOT open System Settings. Only
when a required grant reads as settled-denied SHALL `setup` open System Settings
to the exact Privacy pane for that permission (Location Services / Bluetooth /
Notifications) and print step-by-step instructions to enable it, then keep
polling so that enabling it is detected. If opening the pane fails, the
instructions SHALL still print. `setup` SHALL NOT use a fixed grace window to
assume a still-pending grant is denied.

#### Scenario: Settled-denied Location is routed to Settings
- **WHEN** the user previously clicked Don't Allow on Location and runs `diting setup`
- **THEN** setup detects the settled denial, opens System Settings to the Location Services privacy pane, and prints how to enable diting's helper

#### Scenario: A pending grant is not mislabeled as denied
- **WHEN** the helper's grant is `notDetermined` (e.g. a fresh install / new cdhash) and the prompt has not yet been answered
- **THEN** setup keeps waiting for the prompt and does NOT announce a denial or open System Settings
