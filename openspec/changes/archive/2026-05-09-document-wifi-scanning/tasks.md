# Tasks — document wifi-scanning

## 1. Spec backfill — no implementation
- [x] 1.1 Spec extracted from `src/wifiscope/macos_backend.py`, `src/wifiscope/poller.py`, and `helper/Sources/wifiscope-helper/main.swift` (wifi-scan subcommand path).
- [x] 1.2 Cross-checked redaction behaviour against the `_RedactedBackend` regression scenario and the `_inspect_redacted_scan` inspector.

## 2. Optional polish (not blocking archive)
- [x] 2.1 README.md "What it shows" section gains a one-liner pointing to `openspec/specs/wifi-scanning/spec.md`.
- [x] 2.2 The `(redacted)` placeholder is i18n'd consistently — the help / basics text already references it.
