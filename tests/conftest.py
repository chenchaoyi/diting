"""Shared pytest hardening for the diting test suite.

Self-test mute: never forward events to a real paired phone from a test
run. Many tests build a full ``DitingApp``, which wires the companion sink
from a ``diting-companion.json`` in the working tree (the developer's real
pairing) and would push synthetic test events to their phone — most
visibly the smoke / event tests. We force the companion self-test mute ON
for the whole session; companion tests that exercise forwarding opt out
per-test (``monkeypatch.delenv("DITING_COMPANION")`` + their own
``DITING_COMPANION_STATE`` / a directly-constructed ``CompanionSink``),
which restores cleanly afterwards.
"""
from __future__ import annotations

import os

import pytest


@pytest.fixture(autouse=True, scope="session")
def _mute_companion_in_tests():
    os.environ["DITING_COMPANION"] = "0"
    yield
