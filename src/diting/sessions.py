"""Managed capture sessions.

`SessionStore` owns the on-disk registry of named capture sessions: it
spawns a detached `diting stream` per session, records it, derives live
status from process liveness, stops sessions cleanly (SIGTERM), and tails
their capture files.

The registry lives under a STABLE state dir (``DITING_STATE_DIR`` else
``~/.diting``) — not the CWD like diting's other state files — so
``diting capture list`` finds sessions from any directory. Capture JSONL
holds real BSSIDs / MACs; living under ``~/.diting`` (outside any repo)
keeps it uncommitted.
"""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")


class SessionError(Exception):
    """A user-facing session error (bad name, duplicate, unknown)."""


def state_dir() -> Path:
    """The stable diting state root: ``DITING_STATE_DIR`` or ``~/.diting``."""
    override = os.environ.get("DITING_STATE_DIR")
    return Path(override).expanduser() if override else Path.home() / ".diting"


class SessionStore:
    def __init__(self, root: Path | None = None) -> None:
        self._root = Path(root) if root is not None else state_dir()

    # ---------- paths ----------

    @property
    def sessions_dir(self) -> Path:
        return self._root / "sessions"

    @property
    def captures_dir(self) -> Path:
        return self._root / "captures"

    def _record_path(self, name: str) -> Path:
        return self.sessions_dir / f"{name}.json"

    def _stderr_path(self, name: str) -> Path:
        return self.sessions_dir / f"{name}.stderr.log"

    def default_capture_path(self, name: str) -> Path:
        return self.captures_dir / f"{name}.jsonl"

    def _ensure_dirs(self) -> None:
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.captures_dir.mkdir(parents=True, exist_ok=True)

    # ---------- record CRUD ----------

    @staticmethod
    def validate_name(name: str) -> None:
        if not name or not _NAME_RE.match(name):
            raise SessionError(
                f"invalid session name {name!r}; use letters, digits, . _ -"
            )

    def write_record(self, rec: dict) -> None:
        self._ensure_dirs()
        self._record_path(rec["name"]).write_text(
            json.dumps(rec, ensure_ascii=False, indent=2)
        )

    def read_record(self, name: str) -> dict | None:
        p = self._record_path(name)
        if not p.is_file():
            return None
        try:
            return json.loads(p.read_text())
        except (json.JSONDecodeError, OSError):
            return None

    def delete_record(self, name: str) -> bool:
        p = self._record_path(name)
        if p.is_file():
            p.unlink()
            return True
        return False

    def list_records(self) -> list[dict]:
        if not self.sessions_dir.is_dir():
            return []
        out: list[dict] = []
        for p in sorted(self.sessions_dir.glob("*.json")):
            try:
                out.append(json.loads(p.read_text()))
            except (json.JSONDecodeError, OSError):
                continue
        return out

    # ---------- liveness / status ----------

    @staticmethod
    def pid_alive(pid: int | None) -> bool:
        if not pid:
            return False
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True  # exists but not ours
        except OSError:
            return False
        return True

    def live_status(self, rec: dict) -> str:
        """Derive status, never trusting a stale ``running``.

        A record whose status is a terminal value (``stopped`` / ``exited`` /
        ``crashed``) is returned as-is; a ``running`` record is verified
        against the pid — alive → ``running``, dead → ``exited`` (it ran and
        ended on its own, e.g. ``--duration`` elapsed)."""
        recorded = rec.get("status")
        if recorded in ("stopped", "exited", "crashed"):
            return recorded
        return "running" if self.pid_alive(rec.get("pid")) else "exited"

    def view(self, rec: dict) -> dict:
        v = dict(rec)
        v["status"] = self.live_status(rec)
        return v

    # ---------- lifecycle ----------

    def build_argv(self, *, capture_path: Path, sensors: str | None,
                   duration: str | None) -> list[str]:
        argv = [sys.executable, "-m", "diting", "stream",
                "--out", str(capture_path)]
        if sensors:
            argv += ["--sensors", sensors]
        if duration:
            argv += ["--duration", duration]
        return argv

    def start(self, *, name: str, sensors: str | None = None,
              out: str | None = None, duration: str | None = None,
              spawn=None) -> dict:
        """Spawn a detached capture and record it. ``spawn`` is an injection
        seam for tests: ``spawn(argv, stderr_path) -> pid``."""
        self.validate_name(name)
        existing = self.read_record(name)
        if existing is not None and self.live_status(existing) == "running":
            raise SessionError(
                f"session {name!r} is already running; stop it first"
            )
        self._ensure_dirs()
        capture_path = (
            Path(out).expanduser() if out else self.default_capture_path(name)
        )
        argv = self.build_argv(
            capture_path=capture_path, sensors=sensors, duration=duration,
        )
        stderr_path = self._stderr_path(name)
        pid = (spawn or self._spawn)(argv, stderr_path)
        rec = {
            "name": name,
            "pid": pid,
            "sensors": sensors or "wifi,latency,rf",
            "capture_path": str(capture_path),
            "stderr_path": str(stderr_path),
            "started_at": datetime.now(timezone.utc).isoformat(),
            "duration": duration,
            "status": "running",
            "argv": argv,
        }
        self.write_record(rec)
        return rec

    @staticmethod
    def _spawn(argv: list[str], stderr_path: Path) -> int:
        # Detached: own process group (survives the parent's exit), no stdin,
        # JSONL goes to --out so stdout is discarded, stderr to a logfile.
        errf = open(stderr_path, "ab")
        proc = subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=errf,
            start_new_session=True,
        )
        return proc.pid

    def stop(self, name: str) -> str:
        """SIGTERM a running session and mark it stopped; idempotent on a
        session that has already ended. Returns the resulting status."""
        rec = self.read_record(name)
        if rec is None:
            raise SessionError(f"no such session {name!r}")
        status = self.live_status(rec)
        if status != "running":
            return status  # already exited / stopped → nothing to do
        pid = rec.get("pid")
        try:
            os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, OSError):
            pass
        rec["status"] = "stopped"
        self.write_record(rec)
        return "stopped"

    def stop_all(self) -> list[tuple[str, str]]:
        out: list[tuple[str, str]] = []
        for rec in self.list_records():
            if self.live_status(rec) == "running":
                out.append((rec["name"], self.stop(rec["name"])))
        return out

    # ---------- tail ----------

    def tail_lines(self, name: str, n: int = 20) -> list[str]:
        rec = self.read_record(name)
        if rec is None:
            raise SessionError(f"no such session {name!r}")
        path = Path(rec["capture_path"])
        if not path.is_file():
            return []
        lines = [ln for ln in path.read_text().splitlines() if ln.strip()]
        return lines[-n:] if n > 0 else lines
