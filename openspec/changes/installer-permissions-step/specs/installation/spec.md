## MODIFIED Requirements

### Requirement: The installer SHALL place the Swift helper bundle under `~/Library/Application Support/diting/` and prime it for TCC
After extracting the tarball, the installer SHALL copy `share/diting-tianer.app/`
to `~/Library/Application Support/diting/diting-tianer.app`, strip the quarantine
xattr so Gatekeeper does not block first launch, and then drive the TCC grants to
completion by invoking the just-installed `diting setup`. `setup` opens the
bundle so macOS surfaces the Location → Bluetooth → Notifications prompts and
verifies the outcome (per the `permission-setup` capability), so the user grants
once at install rather than re-granting at first launch.

In the framed render tiers (FULL / PLAIN) the installer SHALL present the
permission grant as its own numbered step — the final step, labelled
`Permissions` — and SHALL render `diting setup`'s output as the body of that
step (indented under the step header via `DITING_SETUP_INDENT`). The helper-copy
step (`Helper`) and the grant step (`Permissions`) SHALL be distinct numbered
steps, so the displayed step total reflects the grant as its own step.

The installer SHALL render the helper / prompt language in the user's
macOS-preferred locale: it SHALL pass `DITING_LANG=<en|zh>` to `setup` (derived
from `defaults read -g AppleLanguages` first entry; `zh` when it starts with
`zh`, otherwise `en`), and `setup`'s bundle launch SHALL carry the matching
`-AppleLanguages '(<bundle-locale-tag>)'` (`zh-Hans` for `zh`, else `en`) so the
helper status window, the macOS TCC prompt headers, and the prompt bodies all
render in one locale (no mixed-language stack).

On an interactive (TTY) install the `setup` step SHALL block-and-verify the
required grants (Location, Bluetooth); on a non-interactive install (non-TTY / CI
/ piped) it SHALL NOT block — the installer SHALL invoke `setup` in its
non-interactive mode so the install completes without waiting. `setup` owns the
permission-outcome surface; the installer SHALL NOT separately fire a
fire-and-forget `open`.

#### Scenario: First install primes TCC on a Chinese-locale Mac
- **WHEN** the user runs the installer on a Mac whose `defaults read -g AppleLanguages` first entry starts with `zh`
- **THEN** the installer invokes `diting setup` with `DITING_LANG=zh`, and the helper launches with `-AppleLanguages '(zh-Hans)'`
- **AND** the helper's status window text, the macOS Location prompt header (`谛听 · 天耳`), and the prompt body text all render in Simplified Chinese — no mixed-language stack

#### Scenario: First install primes TCC on an English-locale Mac
- **WHEN** the user runs the installer on a Mac whose `defaults read -g AppleLanguages` first entry does not start with `zh` (or `defaults` returns no value)
- **THEN** the installer invokes `diting setup` with `DITING_LANG=en`, and the helper launches with `-AppleLanguages '(en)'`
- **AND** the helper status window text, the macOS Location prompt header (`diting · tianer`), and the prompt body text all render in English

#### Scenario: The permission grant is its own numbered step
- **WHEN** the user runs the installer in a framed tier (FULL / PLAIN)
- **THEN** the grant is shown as the final numbered step labelled `Permissions`, distinct from the `Helper` step, and `diting setup`'s output is indented as that step's body

#### Scenario: Interactive install verifies the grants before finishing
- **WHEN** the user runs the installer in an interactive terminal and clicks Allow on the Location and Bluetooth prompts
- **THEN** the `setup` step confirms both grants are present before the install completes, so the first `diting` launch does not re-prompt

#### Scenario: Non-interactive install does not block
- **WHEN** the installer runs under CI / a pipe (stdout is not a TTY)
- **THEN** the `setup` step runs non-interactively (probe-once, no open, no wait) and the install completes without blocking

#### Scenario: Subsequent installs preserve granted permissions when cdhash is unchanged
- **WHEN** the user has already granted Location Services, Bluetooth, and Notifications in a prior install and re-runs the installer with a same-cdhash helper binary
- **THEN** the new copy lands at the same path; TCC keys by cdhash so the grants persist; `setup` verifies them already-present with no re-prompt

#### Scenario: Subsequent install with cdhash change re-prompts once
- **WHEN** a user upgrades from a release whose helper bundle had a different cdhash
- **THEN** the `setup` step fires the TCC prompts again in order, the user clicks Allow on each, and grants land against the new cdhash
- **AND** future same-version installs at the same path skip the prompts
