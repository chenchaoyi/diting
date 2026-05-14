## MODIFIED Requirements

### Requirement: The installer SHALL place the Swift helper bundle under `~/Library/Application Support/diting/` and prime it for TCC in a guided, locale-aware flow
After extracting the tarball, the installer SHALL copy `share/diting-tianer.app/` to `~/Library/Application Support/diting/diting-tianer.app`, strip the quarantine xattr so Gatekeeper does not block first launch, and launch the bundle once via `/usr/bin/open` so macOS surfaces the Location Services, Bluetooth, and Notifications TCC prompts to the user in a single guided flow.

The `open` invocation SHALL pass:
- `--env DITING_LANG=<en|zh>` derived from the macOS user-preferred language (`defaults read -g AppleLanguages` first entry; `zh` if it starts with `zh`, otherwise `en`), so the helper's status window renders in the user's preferred language.
- `--args -AppleLanguages '(<bundle-locale-tag>)'` where the tag is `zh-Hans` for `DITING_LANG=zh` and `en` otherwise. This forces Cocoa's `NSUserDefaults` for the launched process to pick the matching `.lproj`, so the macOS TCC prompt headers, prompt bodies, and the helper status window all use the same locale (no mixed-language stack).

The installer SHALL NOT attempt to read or display a TCC-permissions outcome — the helper's status window owns that surface. The installer SHALL run `open` foreground (not `-g` / background) so the helper window appears on top and macOS prompts layer over it.

#### Scenario: First install primes TCC on a Chinese-locale Mac
- **WHEN** the user runs the installer on a Mac whose `defaults read -g AppleLanguages` first entry starts with `zh`
- **THEN** the installer launches the helper with `DITING_LANG=zh` and `-AppleLanguages '(zh-Hans)'`
- **AND** the helper's status window text, the macOS Location prompt header (`谛听 · 天耳`), and the prompt body text all render in Simplified Chinese — no mixed-language stack

#### Scenario: First install primes TCC on an English-locale Mac
- **WHEN** the user runs the installer on a Mac whose `defaults read -g AppleLanguages` first entry does not start with `zh` (or `defaults` returns no value)
- **THEN** the installer launches the helper with `DITING_LANG=en` and `-AppleLanguages '(en)'`
- **AND** the helper's status window text, the macOS Location prompt header (`diting · tianer`), and the prompt body text all render in English

#### Scenario: Subsequent installs preserve granted permissions when cdhash is unchanged
- **WHEN** the user has already granted Location Services, Bluetooth, and Notifications in a prior install and re-runs the installer with a same-cdhash helper binary
- **THEN** the new copy lands at the same path; TCC keys by cdhash so the grants persist with no re-prompt

#### Scenario: Subsequent install with cdhash change re-prompts once
- **WHEN** a user upgrades from a release whose helper bundle had a different cdhash (e.g. before this change shipped the embedded `AppIcon.icns`)
- **THEN** the install-time prompt flow fires the three TCC prompts again in order, the user clicks Allow on each, and grants land against the new cdhash
- **AND** future same-version installs at the same path skip the prompts
