"""capture-sessions tests — registry, status derivation, lifecycle.

Pure record/status logic runs against a tmp state dir; the spawn/stop
paths use injected or trivial real processes so nothing here needs a
helper or a network.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time

import pytest

from diting import sessions
from diting.sessions import SessionError, SessionStore


def _store(tmp_path) -> SessionStore:
    return SessionStore(root=tmp_path)


# ---------- state dir + CRUD ----------

def test_state_dir_override(monkeypatch, tmp_path):
    monkeypatch.setenv("DITING_STATE_DIR", str(tmp_path / "st"))
    assert sessions.state_dir() == (tmp_path / "st")


def test_lazy_dir_creation(tmp_path):
    store = _store(tmp_path)
    assert not store.sessions_dir.exists()
    store.write_record({"name": "a", "pid": 1, "status": "stopped"})
    assert store.sessions_dir.is_dir() and store.captures_dir.is_dir()


def test_record_round_trip(tmp_path):
    store = _store(tmp_path)
    rec = {"name": "a", "pid": 123, "sensors": "wifi", "status": "running"}
    store.write_record(rec)
    assert store.read_record("a") == rec
    assert [r["name"] for r in store.list_records()] == ["a"]
    assert store.delete_record("a") is True
    assert store.read_record("a") is None


def test_records_found_from_other_cwd(tmp_path, monkeypatch):
    store = _store(tmp_path)
    store.write_record({"name": "a", "pid": 1, "status": "stopped"})
    # The root is absolute, so a different CWD makes no difference.
    monkeypatch.chdir(tmp_path.parent)
    assert [r["name"] for r in _store(tmp_path).list_records()] == ["a"]


def test_invalid_name_rejected(tmp_path):
    for bad in ("", "bad name", "a/b", "x;y"):
        with pytest.raises(SessionError):
            SessionStore.validate_name(bad)
    SessionStore.validate_name("good.name-1_2")  # no raise


# ---------- status derivation ----------

def test_status_running_for_live_pid(tmp_path):
    store = _store(tmp_path)
    rec = {"name": "a", "pid": os.getpid(), "status": "running"}
    assert store.live_status(rec) == "running"


def test_status_exited_for_dead_pid(tmp_path):
    store = _store(tmp_path)
    # A pid that is almost certainly not alive.
    rec = {"name": "a", "pid": 2_000_000_000, "status": "running"}
    assert store.live_status(rec) == "exited"


def test_status_terminal_is_trusted(tmp_path):
    store = _store(tmp_path)
    assert store.live_status({"name": "a", "pid": os.getpid(), "status": "stopped"}) == "stopped"


# ---------- start / stop ----------

def test_start_spawns_expected_argv(tmp_path):
    store = _store(tmp_path)
    seen = {}

    def fake_spawn(argv, stderr_path):
        seen["argv"] = argv
        seen["stderr"] = stderr_path
        return 4242

    rec = store.start(name="s", sensors="all", duration="5m", spawn=fake_spawn)
    argv = seen["argv"]
    assert argv[:4] == [sys.executable, "-m", "diting", "stream"]
    assert "--out" in argv and "--sensors" in argv and "all" in argv
    assert "--duration" in argv and "5m" in argv
    assert rec["pid"] == 4242
    assert store.read_record("s")["pid"] == 4242


def test_start_duplicate_running_rejected(tmp_path):
    store = _store(tmp_path)
    store.start(name="s", spawn=lambda argv, e: os.getpid())  # "running"
    with pytest.raises(SessionError, match="already running"):
        store.start(name="s", spawn=lambda argv, e: os.getpid())


def test_start_overwrites_exited(tmp_path):
    store = _store(tmp_path)
    store.start(name="s", spawn=lambda argv, e: 2_000_000_000)  # dead → exited
    # second start succeeds (no raise) and records a new pid
    rec = store.start(name="s", spawn=lambda argv, e: os.getpid())
    assert rec["pid"] == os.getpid()


def test_stop_signals_and_marks(tmp_path):
    store = _store(tmp_path)
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        store.write_record({"name": "s", "pid": proc.pid, "status": "running",
                            "capture_path": str(tmp_path / "s.jsonl")})
        assert store.stop("s") == "stopped"
        assert store.read_record("s")["status"] == "stopped"
        # SIGTERM was delivered → the process exits (wait() also reaps it,
        # which os.kill(pid,0) can't see through a zombie in this parent).
        proc.wait(timeout=5)
        assert proc.returncode is not None
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=3)


def test_stop_already_stopped_is_ok(tmp_path):
    store = _store(tmp_path)
    store.write_record({"name": "s", "pid": 2_000_000_000, "status": "running"})
    # pid dead → derived exited → stop is a no-op returning the status
    assert store.stop("s") == "exited"


def test_stop_unknown_raises(tmp_path):
    with pytest.raises(SessionError):
        _store(tmp_path).stop("nope")


def test_start_list_stop_integration(tmp_path):
    store = _store(tmp_path)
    procs: list[subprocess.Popen] = []

    def spawn(argv, stderr_path):
        p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        procs.append(p)
        return p.pid

    try:
        store.start(name="s", spawn=spawn)
        views = [store.view(r) for r in store.list_records()]
        assert views and views[0]["status"] == "running"
        assert store.stop("s") == "stopped"
        procs[0].wait(timeout=5)  # SIGTERM delivered → exits + reaped
        assert procs[0].returncode is not None
    finally:
        for p in procs:
            if p.poll() is None:
                p.kill()
                p.wait(timeout=3)


# ---------- tail ----------

def test_tail_last_k_lines(tmp_path):
    store = _store(tmp_path)
    cap = tmp_path / "cap.jsonl"
    cap.write_text("".join(f'{{"i":{i}}}\n' for i in range(10)))
    store.write_record({"name": "s", "pid": 1, "status": "stopped",
                        "capture_path": str(cap)})
    last3 = store.tail_lines("s", 3)
    assert [json.loads(l)["i"] for l in last3] == [7, 8, 9]


# ---------- SIGTERM-clean stream (integration) ----------

def test_stream_sigterm_closes_logger_cleanly(tmp_path):
    """A real `python -m diting stream` that receives SIGTERM must exit 0
    with a COMPLETE final JSONL line (the engine teardown flushed/closed
    the logger), not a truncated one."""
    import signal
    cap = tmp_path / "cap.jsonl"
    env = dict(os.environ, DITING_COMPANION="0")
    proc = subprocess.Popen(
        [sys.executable, "-m", "diting", "stream", "--sensors", "wifi",
         "--out", str(cap)],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, env=env,
    )
    try:
        # session_meta is written synchronously at engine setup → appears fast.
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline and not (cap.is_file() and cap.read_text().strip()):
            time.sleep(0.2)
        assert cap.is_file() and cap.read_text().strip(), "no capture written"
        proc.send_signal(signal.SIGTERM)
        rc = proc.wait(timeout=15)
        assert rc == 0, f"stream did not exit 0 on SIGTERM (rc={rc})"
        last = cap.read_text().splitlines()[-1]
        json.loads(last)  # complete final line, not truncated
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)
