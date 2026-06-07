# add-listening-mark-empty-state — tasks

## 1. Test plan first

- [x] 1.1 TESTING.md rows (EN) for the frame builder + waiting-state
      smoke coverage
- [x] 1.2 Mirror in docs/zh/TESTING.md
- [x] 1.3 Failing tests: `_listening_mark` pure cases (frame 0 rest,
      pulse travels, cycle wraps, beast rows constant, caption
      appended); smoke: LAN waiting state contains the mark, data
      clears it

## 2. Implementation

- [x] 2.1 `_listening_mark(tick, caption)` pure frame builder
- [x] 2.2 `_ListeningWait` mixin: paused-by-default interval, resume
      on waiting-state paint, pause on data / on_hide, frame-freeze
      while `app._paused`
- [x] 2.3 Wire into ScanPanel / BLEPanel / BonjourPanel / LANPanel
      waiting paths
- [x] 2.4 Design README animation carve-out note

## 3. Verify

- [x] 3.1 `uv run pytest`
- [x] 3.2 `uv run python scripts/tui_snapshot.py --mode regression`
- [x] 3.3 `openspec validate --specs --strict` +
      `openspec validate add-listening-mark-empty-state --strict`
