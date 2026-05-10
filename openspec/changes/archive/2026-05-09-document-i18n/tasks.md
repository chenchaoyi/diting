# Tasks — document i18n

## 1. Spec backfill — no implementation
- [x] 1.1 Spec extracted from `src/wifiscope/i18n.py` (`resolve_lang`, `set_lang`, `t`, `pad_cells`, `fit_cells`, the `_ZH` catalog conventions documented in the file's comments).
- [x] 1.2 Cross-checked acronym non-translation rule against the comment block at the top of `_ZH`.

## 2. Optional polish (not blocking archive)
- [x] 2.1 Add a one-liner `__init__` docstring pointing at the canonical spec.
- [x] 2.2 The README "Languages" section gains a brief mention of the JSONL English-keys invariant for users who want to pipe Chinese-UI sessions to log analysis tools.
