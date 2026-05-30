"""`diting companion` subcommand tests (pair / status / unpair)."""

from __future__ import annotations

import pytest

from diting import cli, companion


def test_pair_status_unpair_round_trip(tmp_path, monkeypatch, capsys):
    state = tmp_path / "companion.json"
    monkeypatch.setenv("DITING_COMPANION_STATE", str(state))

    cli._run_companion(["pair", "--relay", "https://relay.example"])
    out = capsys.readouterr().out
    assert "Companion pairing" in out
    assert "https://relay.example" in out
    assert state.exists()

    cli._run_companion(["status"])
    out = capsys.readouterr().out
    assert "Paired" in out and "https://relay.example" in out

    cli._run_companion(["unpair"])
    assert "Unpaired" in capsys.readouterr().out
    assert not state.exists()

    cli._run_companion(["status"])  # default action is status
    assert "Not paired" in capsys.readouterr().out


def test_unknown_action_exits_2(tmp_path, monkeypatch):
    monkeypatch.setenv("DITING_COMPANION_STATE", str(tmp_path / "c.json"))
    with pytest.raises(SystemExit) as exc:
        cli._run_companion(["bogus"])
    assert exc.value.code == 2


def test_relay_url_precedence(monkeypatch):
    monkeypatch.delenv("DITING_COMPANION_RELAY", raising=False)
    assert cli._companion_relay_url(["--relay", "https://x"]) == "https://x"
    assert cli._companion_relay_url(["--relay=https://y"]) == "https://y"
    monkeypatch.setenv("DITING_COMPANION_RELAY", "https://env")
    assert cli._companion_relay_url([]) == "https://env"
    monkeypatch.delenv("DITING_COMPANION_RELAY")
    assert cli._companion_relay_url([]) == companion.DEFAULT_RELAY_URL
