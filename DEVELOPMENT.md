<sub>**English** · [中文](docs/zh/DEVELOPMENT.md)</sub>

# diting — Contributing & Development

> [`README.md`](README.md) covers what diting does and how to use it.
> This document covers how to develop, test, and contribute to it.

diting runs on **OpenSpec-style SDD**. Every behaviour-affecting
change carries a spec delta proposal under `openspec/changes/`,
gets reviewed alongside the code, and on merge has its delta applied
to the canonical spec under `openspec/specs/<capability>/spec.md`.

## Entry points

| Doc | Purpose |
|---|---|
| [`docs/workflow.md`](docs/workflow.md) ([中文](docs/zh/workflow.md)) | Canonical SDD process — branch rules, change proposals, archive flow, self-test discipline |
| [`tests/TESTING.md`](tests/TESTING.md) ([中文](docs/zh/TESTING.md)) | Canonical test plan — every test maps to a spec requirement; spec coverage matrix lists gaps explicitly |
| [`openspec/AGENTS.md`](openspec/AGENTS.md) | Rules for AI agents working in `openspec/` |
| [`.github/pull_request_template.md`](.github/pull_request_template.md) | PR checklist (branch / spec / test / docs / archive) |
| [`CLAUDE.md`](CLAUDE.md) | Quick orientation + hard rules summary |

CI gates on every PR: pytest matrix (3.11 / 3.12 / 3.13) · TUI snapshot
regression · `openspec validate --specs --strict`.

## Capability index

Each capability has a canonical contract under
`openspec/specs/<name>/spec.md`. New behaviour goes through a change
proposal under `openspec/changes/<name>/` first, then archives into
the canonical spec.

| Capability | What it owns |
|---|---|
| [`macos-helper`](openspec/specs/macos-helper/spec.md) | Swift helper bundle (TCC, subprocess contract, schemas) |
| [`wifi-scanning`](openspec/specs/wifi-scanning/spec.md) | What a scan row promises; redaction handling |
| [`bluetooth-scanning`](openspec/specs/bluetooth-scanning/spec.md) | Schema-4 raw passthrough, vendor resolution chain, anonymous-vs-unknown |
| [`ble-decoders`](openspec/specs/ble-decoders/spec.md) | Per-protocol decoder framework (iBeacon / Eddystone / Apple Continuity / MS CDP / RuuviTag) |
| [`ble-detail-modal`](openspec/specs/ble-detail-modal/spec.md) | Per-device inspect modal: selection, sparkline, decoded payload |
| [`link-health`](openspec/specs/link-health/spec.md) | Gateway/WAN ping aggregates, jitter/loss bursts |
| [`environment-monitor`](openspec/specs/environment-monitor/spec.md) | RF stir detector, σ baselines, calibration |
| [`events`](openspec/specs/events/spec.md) | Five-event vocabulary, ring buffer, JSONL serialisation |
| [`event-log`](openspec/specs/event-log/spec.md) | JSONL writer for `--log` and `diting monitor` |
| [`analyze`](openspec/specs/analyze/spec.md) | Pure-rules log post-processor + heuristic catalogue |
| [`inventory`](openspec/specs/inventory/spec.md) | `aps.yaml` resolution, OUI vendor map, cluster labels |
| [`roam-detection`](openspec/specs/roam-detection/spec.md) | 0–100 link score, +10 dB candidate threshold, press-`c` re-roam |
| [`i18n`](openspec/specs/i18n/spec.md) | EN / ZH UI invariants, JSONL English-keys rule, column-cell math |
| [`tui-shell`](openspec/specs/tui-shell/spec.md) | Four-panel layout, view-toggle, modal lifecycle, GroupedFooter |
| [`cli`](openspec/specs/cli/spec.md) | Subcommand vocabulary, `--lang` precedence, `--log`, exit-hint |

## Local development

```bash
uv sync --all-groups          # installs runtime + dev deps (pytest)
make test                     # full pytest suite
make test-all                 # pytest under EN, ZH, locale-detected ZH
make preview                  # regenerate BOTH preview SVGs (EN + ZH)
make help                     # list all make targets
```

Self-test before push (the four CI gates):

```bash
uv run pytest
uv run python scripts/tui_snapshot.py --mode regression
openspec validate --specs --strict
openspec validate <active-change> --strict   # if there is one
```

Or delegate the same to a subagent via the `/opsx:test` slash command
in Claude Code, which keeps the parent context clean.

GitHub Actions runs the suite on every push and PR to `main` against
Python 3.11 / 3.12 / 3.13 on macOS. CoreWLAN and SCDynamicStore are
not exercised live in CI — those surfaces are mocked at the
subprocess and dynamic-store boundaries.

## Bilingual UI / docs discipline

Two languages live in this repo and they must move together:

1. **Strings.** Every user-visible literal in `src/diting/`
   routes through `i18n.t(...)`. When you add or edit one, also
   add the matching key to `_ZH` in `src/diting/i18n.py`. A
   missing key falls back to the English source, so a stale
   catalog never breaks the app — but it does silently skip
   translation, so translation lag is on the author of the change.
2. **Docs.** Every English doc has a Chinese mirror under
   `docs/zh/`. When you edit one, edit the other in the same
   commit. The cross-link strip at the top of each file
   (`English · 中文`) makes drift visible to readers.
3. **Preview SVGs.** `docs/preview.svg` (English) and
   `docs/preview.zh.svg` (Chinese) are both rendered from the
   same fake backend in `docs/_capture_preview.py`. **Any UI
   change that affects rendering means rerunning `make preview`**
   so both SVGs stay in sync with the code. A drift here is
   immediately visible in the README hero shot.

## How it works

This section is for the curious; everyday use does not require
reading it.

**Resolving an AP from a BSSID.** Two rules, both gated by a
last-byte proximity check:

1. *First five octets match + last-byte window.* Radios and VAPs
   are allocated as `mgmt + N` for small N (typically 1..6). When
   several APs share an OUI block (e.g. an H3C controller handing
   out APs at `…3c:07`, `…3c:15`, `…3c:54`), the prefix alone is
   ambiguous; we require the BSSID's last byte to fall within 8
   above the AP's mgmt MAC last byte and pick the closest match.
2. *Octets 2..5 match + same window.* Some vendors split a chip's
   "user" SSIDs and "vendor-internal" SSIDs across sibling OUI
   blocks (H3C uses `40:fe:95:…` and `44:fe:95:…`). Octets 2..5
   carry the chip's serial bits and stay the same across both
   blocks; this rule groups them under one AP. False-match
   probability is ~1 / 2³².

`radio_overrides` always wins above both rules.

**Channel comes from `SCDynamicStore`'s top-level `CHANNEL` field**,
not from `CWInterface.wlanChannel().channelNumber()`. macOS does
periodic background scans while associated, and a 1 Hz CoreWLAN
poll catches the radio mid-scan often enough that the channel
appears to oscillate. The `SCDynamicStore` field reflects the OS's
notion of the radio's current associated channel and is stable.

**Pluggable backend.** `WiFiBackend` is an ABC with
`get_connection`, `scan`, and `permission_state` methods; macOS
lives in `MacOSWiFiBackend`. A future Linux backend (`nl80211` /
`iw`) drops in without touching the polling, alias, or UI layers.

## See also

- [`CHANGELOG.md`](CHANGELOG.md) — version-by-version log
- [`docs/explainers/wifi-sensing.md`](docs/explainers/wifi-sensing.md) —
  what we deliberately do *not* claim about Wi-Fi sensing
