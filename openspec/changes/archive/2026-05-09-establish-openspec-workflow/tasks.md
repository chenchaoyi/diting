# Tasks — establish OpenSpec workflow

## 1. Skeleton + agent rules
- [x] 1.1 Create `openspec/specs/`, `openspec/changes/`, `openspec/changes/archive/`
- [x] 1.2 Write `openspec/AGENTS.md` (workflow rules for agents)
- [x] 1.3 Write `openspec/README.md` (capability index)

## 2. Contributor docs
- [x] 2.1 Write `docs/workflow.md` (per-PR conventions, branch naming, archive flow)
- [x] 2.2 Update `CLAUDE.md` with a "Workflow" section pointing at the above

## 3. Initial backfill
- [x] 3.1 `document-macos-helper` archive change + canonical spec
- [x] 3.2 `document-wifi-scanning` archive change + canonical spec
- [x] 3.3 `document-bluetooth-scanning` archive change + canonical spec
- [x] 3.4 `document-ble-decoders` archive change + canonical spec
- [x] 3.5 `document-ble-detail-modal` archive change + canonical spec
- [x] 3.6 `document-link-health` archive change + canonical spec

## 4. Follow-on backfill (closed 2026-05-09 — same day as workflow rollout)
- [x] 4.1 `document-environment-monitor` (RF stir / σ baseline)
- [x] 4.2 `document-events` + `document-event-log` (unified ring + JSONL writer)
- [x] 4.3 `document-analyze` (CLI log post-processor)
- [x] 4.4 `document-i18n` (bilingual UI invariants, column-cell math)
- [x] 4.5 `document-inventory` (aps.yaml + cluster labels)
- [x] 4.6 `document-roam-detection` (same-SSID better candidate logic)
- [x] 4.7 `document-tui-shell` (panel layout, modal lifecycle, footer grouping)
- [x] 4.8 `document-cli` (subcommand contract, --lang resolution, --log default path)

The workflow rollout shipped together with all 9 backfilled
capabilities. Every capability that exists in code today now has
a canonical spec under `openspec/specs/`. Future capability work
flows through normal `openspec/changes/<name>/` proposals rather
than these `document-*` shapes.
