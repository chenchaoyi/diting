# OpenSpec — wifiscope

Capability index. Each entry links to the canonical spec. Workflow rules
live in `AGENTS.md`. Contributor-facing how-to is at `../docs/workflow.md`.

## Capabilities (canonical)

All 15 capabilities currently in code are spec'd. New code goes
through normal `openspec/changes/<name>/` proposals; no further
`document-*` backfill is pending.

| Capability | Spec | What it owns |
|---|---|---|
| `macos-helper` | [specs/macos-helper/spec.md](specs/macos-helper/spec.md) | Swift helper bundle: TCC permissions, subprocess contract, JSON schema, build / install path |
| `wifi-scanning` | [specs/wifi-scanning/spec.md](specs/wifi-scanning/spec.md) | CoreWLAN scan via helper, beacon IE keys, redaction handling, schema 3 |
| `bluetooth-scanning` | [specs/bluetooth-scanning/spec.md](specs/bluetooth-scanning/spec.md) | BLE advertisement passthrough, schema-4 raw fields, vendor resolution chain, anonymous vs unknown distinction |
| `ble-decoders` | [specs/ble-decoders/spec.md](specs/ble-decoders/spec.md) | Per-protocol decoder framework + canonical decoders (iBeacon, Eddystone, Apple Continuity, Microsoft CDP, RuuviTag) |
| `ble-detail-modal` | [specs/ble-detail-modal/spec.md](specs/ble-detail-modal/spec.md) | Per-device inspect modal: keyboard + mouse selection, RSSI history sparkline, decoded-payload section |
| `link-health` | [specs/link-health/spec.md](specs/link-health/spec.md) | Gateway / WAN ping aggregates, jitter, loss bursts, latency spikes |
| `environment-monitor` | [specs/environment-monitor/spec.md](specs/environment-monitor/spec.md) | RF-stir detector — per-AP σ baseline, three-tier fusion modes, ratio+floor spike rule, cooldown+rearm, calibration loading |
| `events` | [specs/events/spec.md](specs/events/spec.md) | Five-event vocabulary, in-memory `EventRing`, locale-stable JSONL serialisation |
| `event-log` | [specs/event-log/spec.md](specs/event-log/spec.md) | JSONL writer for `--log` and `wifiscope monitor`, flush-after-each, atexit cleanup, English-keys-vs-translated-values split |
| `analyze` | [specs/analyze/spec.md](specs/analyze/spec.md) | Pure-rules log post-processor — heuristic catalogue, loss-percent format auto-detection, duration honesty |
| `inventory` | [specs/inventory/spec.md](specs/inventory/spec.md) | `aps.yaml` loading, four-path AP-name resolution, cluster-label stability, OUI vendor map |
| `roam-detection` | [specs/roam-detection/spec.md](specs/roam-detection/spec.md) | 0-100 link scoring, +10 dB candidate threshold, press-c Wi-Fi cycle |
| `i18n` | [specs/i18n/spec.md](specs/i18n/spec.md) | Language resolution order, `t()` lookup, pad/fit_cells column math, English-keys-in-JSONL invariant |
| `tui-shell` | [specs/tui-shell/spec.md](specs/tui-shell/spec.md) | Four-panel layout, in-place view-toggle, modal lifecycle, GroupedFooter |
| `cli` | [specs/cli/spec.md](specs/cli/spec.md) | Subcommand vocabulary, default-TUI behaviour, `--lang` precedence, `--log` semantics, exit-hint contract |

## Active changes

```
openspec/changes/
```

(empty as of 2026-05-09 — all current proposals are archived.)

## Recent archive

```
openspec/changes/archive/
```

| Date | Change | Capabilities touched |
|---|---|---|
| 2026-05-09 | establish-openspec-workflow | (workflow only) |
| 2026-05-09 | document-macos-helper | `macos-helper` (new) |
| 2026-05-09 | document-wifi-scanning | `wifi-scanning` (new) |
| 2026-05-09 | document-bluetooth-scanning | `bluetooth-scanning` (new) |
| 2026-05-09 | document-ble-decoders | `ble-decoders` (new) |
| 2026-05-09 | document-ble-detail-modal | `ble-detail-modal` (new) |
| 2026-05-09 | document-link-health | `link-health` (new) |
| 2026-05-09 | document-environment-monitor | `environment-monitor` (new) |
| 2026-05-09 | document-events | `events` (new) |
| 2026-05-09 | document-event-log | `event-log` (new) |
| 2026-05-09 | document-analyze | `analyze` (new) |
| 2026-05-09 | document-inventory | `inventory` (new) |
| 2026-05-09 | document-roam-detection | `roam-detection` (new) |
| 2026-05-09 | document-i18n | `i18n` (new) |
| 2026-05-09 | document-tui-shell | `tui-shell` (new) |
| 2026-05-09 | document-cli | `cli` (new) |

## Pre-OpenSpec history

The `docs/specs/v0.x.0-*.md` files predate this workflow. They are
preserved as historical reference but are no longer authoritative —
the per-capability `openspec/specs/<name>/spec.md` files take
precedence. Discrepancies between an old release brief and a current
canonical spec resolve in favour of the canonical spec.
