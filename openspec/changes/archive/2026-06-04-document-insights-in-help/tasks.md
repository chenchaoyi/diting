# Tasks

## 1. Test plan (tests-first)
- [x] 1.1 `tests/TESTING.md` (EN) + `docs/zh/TESTING.md` — note the help/basics
  modals now document the insight/threat layer + companion binding; covered by
  the existing tui-smoke render + i18n no-fallthrough checks.

## 2. Help modal
- [x] 2.1 `_help_content` — `k` companion binding line; new **Insights &
  threats** section; revised `--notify` text (TUI insight/threat path).

## 3. Basics glossary
- [x] 3.1 `_basics_content` — **Insights & threats** section: `Familiarity`,
  `INSIGHT`, `THREAT`.

## 4. i18n parity
- [x] 4.1 `i18n.py` — ZH for every new / changed EN key (events-modal block,
  monitor `--notify` block, companion binding, insight/threat section + body,
  glossary terms). Verified no EN fall-through in ZH mode.

## 5. Spec
- [x] 5.1 `tui-shell` delta — footer enumeration corrected for companion;
  help/basics document the insight/threat layer.

## 6. Gates
- [x] 6.1 `uv run pytest`, snapshot regression,
  `openspec validate --specs --strict`,
  `openspec validate document-insights-in-help --strict`.
