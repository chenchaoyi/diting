## 1. Test plan first

- [x] 1.1 Update `tests/TESTING.md` (EN) — new `capture-sessions` section (state-dir resolution, record CRUD, live status derivation, start/stop/tail, SIGTERM-clean stream) + a `cli` row for the `capture` verb
- [x] 1.2 Mirror into `docs/zh/TESTING.md` (ZH parity)

## 2. SessionStore + entry

- [x] 2.1 Add `src/diting/__main__.py` calling `cli.main()` so `python -m diting` works
- [x] 2.2 Create `src/diting/sessions.py` `SessionStore`: state-dir resolution (`DITING_STATE_DIR` else `~/.diting`), record path/capture path/stderr path layout, lazy dir creation
- [x] 2.3 Record CRUD (write/read/list/delete one JSON record) + name validation `[A-Za-z0-9._-]+`
- [x] 2.4 Live status derivation: `pid_alive(pid)` (`os.kill(pid,0)`); `running` vs `exited`/`crashed` vs `stopped`
- [x] 2.5 `start(...)`: spawn `[sys.executable, "-m", "diting", "stream", …]` detached (`start_new_session=True`, stdin/stdout=DEVNULL, stderr→logfile), write record; reject a still-running name
- [x] 2.6 `stop(name|all)`: SIGTERM the pid(s), mark stopped (idempotent)
- [x] 2.7 `tail(name, n, follow)`: last-K lines + optional follow

## 3. SIGTERM-clean stream

- [x] 3.1 In `_run_stream`, install `loop.add_signal_handler(SIGTERM, …)` before `engine.run()` that cancels the run so the engine teardown flushes + closes the logger; exit 0. Leave SIGINT unchanged

## 4. CLI wiring

- [x] 4.1 `_run_capture(argv)` dispatcher routing `start`/`list`/`status`/`stop`/`tail` (+ `--help`); uniform `--json` on `list`/`status`
- [x] 4.2 Add `capture` to `_CANONICAL`/`_COMMANDS` table (actions + flags) so the manifest + `--help` carry it; route it in `_dispatch`

## 5. Tests

- [x] 5.1 `tests/test_sessions.py`: state-dir override; record CRUD + name validation; status derivation (alive pid → running; dead pid → exited); start spawns with the expected argv (fake/patched Popen) and writes a record; duplicate-running rejected; stop sends SIGTERM + marks stopped; tail last-K
- [x] 5.2 `tests/test_sessions.py`: integration — start a trivial detached process, assert `list` sees it running, `stop` ends it (use a short sleeper or a real `python -m diting stream --duration`)
- [x] 5.3 `tests/test_cli.py`: `capture` routing + manifest entry; `capture --help` lists actions
- [x] 5.4 `uv run pytest`

## 6. Docs + parity

- [x] 6.1 `docs/agents.md`: document the session lifecycle (`start` → leave → `status`/`tail` → `analyze`)
- [x] 6.2 `docs/zh/agents.md`: ZH parity
- [x] 6.3 `README.md` + `docs/zh/README.md`: add `capture` examples
- [x] 6.4 Any new user-facing `t()` strings get EN + ZH catalog entries

## 7. Gates

- [x] 7.1 `uv run pytest`
- [x] 7.2 `uv run python scripts/tui_snapshot.py --mode regression`
- [x] 7.3 `openspec validate --specs --strict` and `openspec validate capture-sessions --strict`
