"""`diting update` tests — version compare + the CLI verb, all with the
GitHub fetch and the installer re-run patched (no network, no install)."""
from __future__ import annotations

import json as _json

import pytest

from diting import cli
from diting import update as upd


# ---------- version comparison ----------

def test_normalize_strips_leading_v():
    assert upd.normalize("v2.0.5") == "2.0.5"
    assert upd.normalize("2.0.5") == "2.0.5"


def test_version_tuple_and_is_newer():
    assert upd.version_tuple("v2.0.10") == (2, 0, 10)
    assert upd.is_newer("2.0.10", "2.0.9")        # numeric, not lexical
    assert upd.is_newer("v2.1.0", "2.0.99")
    assert not upd.is_newer("2.0.5", "2.0.5")     # equal → not newer
    assert not upd.is_newer("2.0.4", "2.0.5")
    # Pre-release / build suffixes degrade gracefully, no raise.
    assert upd.version_tuple("2.0.5-rc1") == (2, 0, 5)


# ---------- fetch_latest_tag ----------

def test_fetch_latest_tag_parses_tag_name(monkeypatch):
    import io

    class _Resp:
        def __init__(self, body):
            self._b = body.encode()
        def read(self):
            return self._b
        def __enter__(self):
            return io.BytesIO(self._b)
        def __exit__(self, *a):
            return False

    monkeypatch.setattr("urllib.request.urlopen",
                        lambda *a, **k: _Resp('{"tag_name": "v2.0.5"}'))
    assert upd.fetch_latest_tag() == "v2.0.5"


# ---------- the `update` verb ----------

def test_update_json_reports_available(monkeypatch, capsys):
    monkeypatch.setattr("diting.__version__", "2.0.4", raising=False)
    monkeypatch.setattr(upd, "fetch_latest_tag", lambda **k: "v2.0.5")
    with pytest.raises(SystemExit) as ei:
        cli._run_update(["--json"])
    assert ei.value.code == 0
    doc = _json.loads(capsys.readouterr().out)
    assert doc == {"current": "2.0.4", "latest": "2.0.5", "update_available": True}


def test_update_json_up_to_date(monkeypatch, capsys):
    monkeypatch.setattr("diting.__version__", "2.0.5", raising=False)
    monkeypatch.setattr(upd, "fetch_latest_tag", lambda **k: "v2.0.5")
    with pytest.raises(SystemExit):
        cli._run_update(["--json"])
    doc = _json.loads(capsys.readouterr().out)
    assert doc["update_available"] is False


def test_update_check_does_not_install(monkeypatch, capsys):
    monkeypatch.setattr("diting.__version__", "2.0.4", raising=False)
    monkeypatch.setattr(upd, "fetch_latest_tag", lambda **k: "v2.0.5")

    def boom(*a, **k):
        raise AssertionError("--check must not run the installer")

    monkeypatch.setattr(upd, "run_installer", boom)
    with pytest.raises(SystemExit) as ei:
        cli._run_update(["--check"])
    assert ei.value.code == 0
    out = capsys.readouterr().out
    assert "2.0.4" in out and "2.0.5" in out


def test_update_already_latest_exits_0_without_install(monkeypatch, capsys):
    monkeypatch.setattr("diting.__version__", "2.0.5", raising=False)
    monkeypatch.setattr(upd, "fetch_latest_tag", lambda **k: "v2.0.5")
    monkeypatch.setattr(upd, "run_installer",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no install")))
    with pytest.raises(SystemExit) as ei:
        cli._run_update([])
    assert ei.value.code == 0
    assert "latest" in capsys.readouterr().out


def test_update_installs_when_newer_pinning_tag(monkeypatch, capsys):
    monkeypatch.setattr("diting.__version__", "2.0.4", raising=False)
    monkeypatch.setattr(upd, "fetch_latest_tag", lambda **k: "v2.0.5")
    seen = {}

    def fake_install(tag, *, lang=None, **k):
        seen["tag"] = tag
        return 0

    monkeypatch.setattr(upd, "run_installer", fake_install)
    with pytest.raises(SystemExit) as ei:
        cli._run_update([])
    assert ei.value.code == 0
    assert seen["tag"] == "v2.0.5"  # the un-normalized tag pins DITING_VERSION


def test_update_network_failure_exits_1(monkeypatch, capsys):
    def boom(**k):
        raise OSError("dns")

    monkeypatch.setattr(upd, "fetch_latest_tag", boom)
    with pytest.raises(SystemExit) as ei:
        cli._run_update(["--json"])
    assert ei.value.code == 1
    err = capsys.readouterr().err
    assert _json.loads(err)["code"] == 1


def test_run_installer_pins_version_and_runs_bash(monkeypatch):
    """run_installer fetches install.sh and execs `bash -s` with
    DITING_VERSION pinned to the tag."""
    import io

    class _Resp:
        def __enter__(self):
            return io.BytesIO(b"#!/usr/bin/env bash\necho hi\n")
        def __exit__(self, *a):
            return False

    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: _Resp())
    captured = {}

    class _Proc:
        returncode = 0

    def fake_run(cmd, *, input=None, env=None, **k):
        captured["cmd"] = cmd
        captured["env"] = env
        return _Proc()

    monkeypatch.setattr("subprocess.run", fake_run)
    rc = upd.run_installer("v2.0.5", lang="zh")
    assert rc == 0
    assert captured["cmd"][0] == "bash"
    assert captured["env"]["DITING_VERSION"] == "v2.0.5"
    assert captured["env"]["DITING_LANG"] == "zh"
