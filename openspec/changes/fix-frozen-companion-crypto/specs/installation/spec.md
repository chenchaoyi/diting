# installation — delta

## ADDED Requirements

### Requirement: The frozen binary SHALL bundle lazy-imported native deps
The PyInstaller-frozen `diting` binary SHALL include every runtime dependency
reachable only via a lazy import — in particular the companion-bridge crypto
path (PyNaCl → libsodium → cffi's `_cffi_backend` C extension), which nothing on
the startup / hot path touches. Opening the companion screen, pairing, or
running `diting companion status` from the frozen binary SHALL NOT crash with a
missing-native-module error (`ModuleNotFoundError: No module named
'_cffi_backend'`). The frozen-build command MUST force-collect such packages
rather than relying on PyInstaller's static import analysis.

#### Scenario: Companion path works in the frozen binary
- **WHEN** a user runs the frozen `diting` and opens the companion screen (`k`) or runs `diting companion status`
- **THEN** the companion crypto imports succeed and no `_cffi_backend` (or other missing-native-module) error is raised

#### Scenario: The build command keeps PyNaCl collected
- **WHEN** the frozen-build command is constructed
- **THEN** it force-collects `nacl` + `cffi` and hidden-imports `_cffi_backend`, so a lazy-imported native dep cannot silently fall out of the bundle
