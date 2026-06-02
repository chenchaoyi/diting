# Tasks

- [x] 1. `decoders/manufacturer.py` — generic recogniser (cid/vendor/body),
  skips dedicated cids, abstains/never-raises.
- [x] 2. Register it last in `decoders/__init__.py`.
- [x] 3. Tests: surfaces cid+body; vendor name when known; skips dedicated
  cids; abstains on missing/short; no fabricated device_type.
- [x] 4. TESTING.md EN/ZH rows.
- [ ] 5. Gates: pytest, snapshot regression, openspec validate (specs + change).
