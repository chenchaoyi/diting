# diting (谛听) — agent / contributor brief

A real-time terminal Wi-Fi + BLE monitor for macOS. Pure Python TUI on
top of a small Swift helper bundle that owns the macOS TCC permissions
(Location Services for unredacted Wi-Fi scan, Bluetooth for BLE).

## Quick orientation

```
src/diting/        ← Python TUI + analyzers + decoders
helper/Sources/       ← Swift helper bundle (CoreWLAN + CoreBluetooth)
openspec/             ← Spec-driven development (SDD) — see below
docs/                 ← Workflow guide, screenshots, translations,
                       design system (`docs/design/diting-design/`)
scripts/              ← engineering tooling (snapshot capture, surveys)
tests/                ← pytest unit + Textual smoke tests
```

## Workflow — read this before any non-trivial change

This repo runs on **OpenSpec-style SDD**. Every behaviour-affecting
change carries a spec delta proposal under `openspec/changes/`, gets
reviewed alongside the code, and on merge has its delta applied into
canonical `openspec/specs/<capability>/spec.md`.

- Agent rules: `openspec/AGENTS.md` (read this once before touching
  anything in `openspec/`)
- Capability index + active changes: `openspec/README.md`
- Contributor entry point: `DEVELOPMENT.md` (中文：`docs/zh/DEVELOPMENT.md`)
- SDD process detail: `docs/workflow.md` (中文：`docs/zh/workflow.md`)
- Test plan: `tests/TESTING.md` (中文：`docs/zh/TESTING.md`) — canonical
- PR template: `.github/pull_request_template.md`

### Hard rules (review-blocking)

1. **New branch only.** Cut from latest `main` with `feature/`,
   `fix/`, `refactor/`, or `chore/` prefix. Never commit to `main`.
2. **OpenSpec change required** for behaviour-affecting work
   (`/opsx:propose <name>`).
3. **Self-test before push** — run `/opsx:test` (delegates to a
   subagent) or all four CI gates manually:
   ```bash
   uv run pytest
   uv run python scripts/tui_snapshot.py --mode regression
   openspec validate --specs --strict
   openspec validate <change> --strict
   ```
4. **Test-first discipline** — `tests/TESTING.md` is the canonical
   test plan. Update it (EN + ZH) BEFORE writing the test code.
5. **EN ↔ ZH parity** — every `i18n.py` EN-key edit MUST update the
   ZH value. Every `docs/<file>.md` edit MUST land with a matching
   `docs/zh/<file>.md` edit in the same PR.
6. **README stays current** — user-facing surface changes update
   both `README.md` and `docs/zh/README.md` in the same PR.

Do not edit `openspec/specs/*` directly outside of the archive step
of a merged change. New behaviour goes through a change proposal
first, then archives into the canonical spec.

## Run / test commands

```bash
uv run diting                       # launch TUI
uv run pytest                          # unit + smoke (requires no real env)
uv run python scripts/tui_snapshot.py --mode regression   # synthetic regression
uv run python scripts/tui_snapshot.py --mode explore      # real-env audit
```

The `/tui-audit` slash command in this repo runs the explore-mode
capture and walks an open-ended audit; it is the right tool when a
user reports a real-environment UX issue.

## Privacy

- BLE / Wi-Fi captures contain real BSSIDs / SSIDs / device names /
  IPs. They live in `/tmp/` by default and never get committed.
- `aps.yaml` (AP-naming inventory) is git-ignored; `aps.example.yaml`
  is the public-shareable template.
- `diting-*.jsonl` event-log files in the repo root are git-ignored
  per session.
- `diting-companion.json` (companion pairing — holds the secretbox key)
  is git-ignored; `diting-companion.example.json` is the public template.

## Companion protocol (cross-repo, canonical here)

The desktop↔mobile pairing wire contract — `companion-protocol` — is
**owned by this repo** under `src/diting/companion/protocol/` (versioned;
JSON Schema + golden fixtures + `manifest.json` hashes). diting-mobile
*vendors* these artifacts under its own `protocol/` and conforms to them;
it must not redefine the format. Any protocol-affecting change is a paired
OpenSpec change in both repos at the same version, fixtures regenerated
here first (`python -m diting.companion.protocol._generate`), then
re-vendored. The relay (Cloudflare Worker) lives in `relay/`.

## Project-specific conventions

- Python target: 3.11. Type hints throughout. `from __future__ import
  annotations` in every module so forward references work.
- Strings shown to the user go through `t()` (in `src/diting/i18n.py`).
  EN is the catalog key; ZH is the alternate catalog.
- Column-aligned widgets use `pad_cells` / `fit_cells`, NOT
  `str.ljust` — CJK glyphs occupy two terminal cells.
- Helper schema is bumped (currently 4) when its JSON output gains
  fields. Python tolerates older schemas; never break back-compat.
- Decoders go under `src/diting/decoders/`, register via the
  `@register` decorator, and **must not raise** on malformed input —
  abstain (return `None`) instead.

## Design

This repo has a design system at `docs/design/diting-design/`. Whenever
you generate UI, marketing copy, README sections, snapshot mocks,
slides, or any visual artifact for diting:

- Read `docs/design/diting-design/README.md` first.
- Use `docs/design/diting-design/colors_and_type.css` for any HTML.
- Copy assets out of `docs/design/diting-design/assets/` rather than
  drawing your own SVGs or generating images.
- Follow the voice rules: lowercase `diting`, you-not-we, no
  emoji, parenthesised italic empty states.
- The pixel-art beast in `assets/logo-mark.svg` is the only mark.
  Do not redesign it.
