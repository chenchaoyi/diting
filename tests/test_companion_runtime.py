"""Runtime glue: build_sink gating + the header status chip."""

from __future__ import annotations

from diting.companion import runtime
from diting.companion.relay_client import RelayClient
from diting.companion.state import PairingState


def test_build_sink_none_when_unpaired(tmp_path):
    assert runtime.build_sink(tmp_path / "absent.json") is None


def test_build_sink_none_when_disabled_env(tmp_path, monkeypatch):
    path = tmp_path / "companion.json"
    PairingState.generate("https://r.example").save(path)
    monkeypatch.setenv("DITING_COMPANION", "0")
    assert runtime.build_sink(path) is None


def test_build_sink_when_paired(tmp_path):
    path = tmp_path / "companion.json"
    st = PairingState.generate("https://r.example")
    st.save(path)
    sink = runtime.build_sink(path)
    assert sink is not None
    assert sink.client.pending == 0


def test_subtitle_chip_states():
    client = RelayClient("https://r.example", "c", "tok")

    class _Sink:
        def __init__(self, c):
            self.client = c

    sink = _Sink(client)
    assert runtime.subtitle_chip(sink) == "companion: on"
    client._queue.append(({"seq": 1}, None, None))
    assert "1 queued" in runtime.subtitle_chip(sink)
    client._dropped = 2
    chip = runtime.subtitle_chip(sink)
    assert "1 queued" in chip and "2 dropped" in chip
