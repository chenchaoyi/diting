# Tasks

- [x] 1. `--no-companion` flag: `_extract_no_companion_arg` sets
  DITING_COMPANION=0; wired globally in main(); help text added.
- [x] 2. Explore harness pins DITING_COMPANION=0.
- [x] 3. README EN/ZH note the flag.
- [x] 4. Test: the extractor strips the flag + sets the env; build_sink then
  returns None.
- [ ] 5. Gates: pytest, snapshot regression, openspec validate (specs + change).
