"""Runtime glue: build_sink gating + the header status chip."""

from __future__ import annotations

import asyncio
import json

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


def test_build_sink_when_paired(tmp_path, monkeypatch):
    # Hermetic against an ambient DITING_COMPANION=0 (e.g. a self-test
    # shell that exported the mute) — this case asserts the paired path.
    monkeypatch.delenv("DITING_COMPANION", raising=False)
    path = tmp_path / "companion.json"
    st = PairingState.generate("https://r.example")
    st.save(path)
    sink = runtime.build_sink(path)
    assert sink is not None
    assert sink.client.pending == 0


class _Sink:
    def __init__(self, c):
        self.client = c


def test_subtitle_chip_states():
    client = RelayClient("https://r.example", "c", "tok")
    sink = _Sink(client)
    assert runtime.subtitle_chip(sink) == "companion: on"
    client._queue.append(({"seq": 1}, None, None))
    assert "1 queued" in runtime.subtitle_chip(sink)
    client._dropped = 2
    chip = runtime.subtitle_chip(sink)
    assert "1 queued" in chip and "2 dropped" in chip


def _failing_client(failures: int) -> RelayClient:
    """A client with one queued envelope and `failures` consecutive
    fully-failed flushes behind it (transport error 0)."""
    client = RelayClient("https://r.example", "c", "tok",
                         transport=lambda url, headers, body: 0)
    client.enqueue({"seq": 1})
    for _ in range(failures):
        client.flush()
    return client


def test_subtitle_chip_unreachable_at_threshold():
    sink = _Sink(_failing_client(3))
    chip = runtime.subtitle_chip(sink)
    assert "1 queued" in chip and "relay unreachable" in chip


def test_subtitle_chip_plain_below_threshold():
    sink = _Sink(_failing_client(2))
    chip = runtime.subtitle_chip(sink)
    assert "1 queued" in chip and "relay unreachable" not in chip


def test_subtitle_chip_recovers_after_successful_send():
    client = _failing_client(3)
    sink = _Sink(client)
    assert "relay unreachable" in runtime.subtitle_chip(sink)
    # Relay comes back: the drain succeeds and the annotation drops with it.
    client._transport = lambda url, headers, body: 200
    client.enqueue({"seq": 2})
    client.flush()
    chip = runtime.subtitle_chip(sink)
    assert "relay unreachable" not in chip and chip == "companion: on"


class _FlushSink:
    """Minimal sink for flush_loop: forwards flush to a real RelayClient."""

    def __init__(self, client):
        self.client = client

    def flush(self, max_batch=None):
        return self.client.flush(max_batch)


def test_flush_loop_drains_backlog_across_cycles():
    # A backlog deeper than one batch drains to empty across successive
    # periodic flushes — each cycle sends at most DEFAULT_FLUSH_BATCH — with
    # no loss or reordering.
    sent: list[int] = []

    def tx(url, headers, body):
        sent.append(json.loads(body)["seq"])
        return 200

    client = RelayClient("https://r.example", "c", "tok", transport=tx)
    total = runtime.DEFAULT_FLUSH_BATCH * 2 + 5  # spans 3 cycles
    for s in range(1, total + 1):
        client.enqueue({"seq": s})
    sink = _FlushSink(client)

    async def run():
        task = asyncio.create_task(runtime.flush_loop(sink, interval=0))
        for _ in range(500):  # bounded wait — in-memory transport drains fast
            if client.pending == 0:
                break
            await asyncio.sleep(0.001)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(run())
    assert client.pending == 0
    assert sent == list(range(1, total + 1))  # in order, nothing lost
    # More than one cycle was needed — never a single all-or-nothing burst.
    assert total > runtime.DEFAULT_FLUSH_BATCH
