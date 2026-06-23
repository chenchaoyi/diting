# Tasks

- [x] `ScanWorker` (main.swift): assign delegate, wait for the settled status
      via the callback (with a fallback timer); register + scan only when
      authorized; redacted + NO prompt otherwise
- [x] Build helper; verify against the current notDetermined machine — `scan`
      returns redacted JSON, repeated scans pop zero dialogs
- [ ] `tests/TESTING.md` + `docs/zh/TESTING.md` row (helper-side, verified by
      hand)
- [ ] all four CI gates (Python suite unaffected; helper verified by hand)
