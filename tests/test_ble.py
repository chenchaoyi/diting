"""Tests for the BLE scanning layer.

Covers (1) line parsing, (2) vendor lookup, (3) service category
inference, (4) device TTL expiry, (5) UUID-rotation fuzzy merge,
(6) permission denied path, (7) helper subprocess crash, and (8)
malformed JSON line resilience.

The Swift helper itself is not exercised here — the tests inject a
fake stdout stream into BLEPoller via the ``_spawn`` constructor seam,
the same boundary mocked by ``test_helper.py`` for the existing
``scan`` subcommand. This keeps the suite hermetic on CI runners that
have neither Bluetooth hardware nor a built helper bundle.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from wifiscope import ble
from wifiscope.ble import (
    BLEDevice,
    BLEPoller,
    BLEScanUpdate,
    expire_devices,
    load_vendors,
    lookup_vendor,
    merge_for_display,
    service_category,
    update_from_line,
)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

# Realistic helper output line for an Apple device (company ID 76).
SAMPLE_AIRPODS = json.dumps({
    "ts": "2026-05-06T12:34:56.789Z",
    "id": "550E8400-E29B-41D4-A716-446655440000",
    "name": "AirPods Pro",
    "rssi_dbm": -52,
    "is_connectable": True,
    "service_uuids": ["180A", "FE9F"],
    "manufacturer_id": 76,
    "manufacturer_hex": "4c001907cafebabedeadbeef",
})

VENDORS = {76: "Apple, Inc.", 117: "Samsung Electronics Co. Ltd."}


# ------------------------------------------------------------------
# 1. JSON line parsing happy path
# ------------------------------------------------------------------

def test_parse_advertisement_populates_all_fields():
    """A well-formed JSONL event becomes a BLEDevice with every
    field populated and identifier lower-cased."""
    devices: dict[str, BLEDevice] = {}
    state = update_from_line(devices, SAMPLE_AIRPODS, vendors=VENDORS)
    assert state is None
    assert len(devices) == 1
    d = next(iter(devices.values()))
    assert d.identifier == "550e8400-e29b-41d4-a716-446655440000"
    assert d.name == "AirPods Pro"
    assert d.vendor == "Apple, Inc."
    assert d.vendor_id == 76
    assert d.rssi_dbm == -52
    assert d.is_connectable is True
    assert d.services == ("180A", "FE9F")
    assert d.ad_count == 1
    assert d.merged_count == 1
    assert d.first_seen == d.last_seen


def test_parse_subsequent_advertisement_carries_history():
    """A repeat ad for the same identifier keeps first_seen and bumps
    ad_count; last_seen advances to the newer event."""
    t0 = datetime(2026, 5, 6, 12, 0, 0, tzinfo=timezone.utc)
    t1 = t0 + timedelta(seconds=3)
    devices: dict[str, BLEDevice] = {}
    update_from_line(devices, SAMPLE_AIRPODS, vendors=VENDORS, now=t0)
    update_from_line(devices, SAMPLE_AIRPODS, vendors=VENDORS, now=t1)
    d = next(iter(devices.values()))
    assert d.ad_count == 2
    assert d.first_seen == t0
    assert d.last_seen == t1


# ------------------------------------------------------------------
# 2. Vendor lookup
# ------------------------------------------------------------------

def test_lookup_vendor_known_company_id():
    """Apple's well-known SIG company ID resolves to the right vendor."""
    assert lookup_vendor(76, VENDORS) == "Apple, Inc."


def test_lookup_vendor_unknown_returns_none():
    """An unassigned company ID resolves to None — the renderer can
    then show the raw ID and let the user investigate."""
    assert lookup_vendor(99999, VENDORS) is None


def test_lookup_vendor_none_input_returns_none():
    """The 'no manufacturer data' case is the most common BLE state.
    Defensive: lookup must accept None silently."""
    assert lookup_vendor(None, VENDORS) is None


def test_load_vendors_ships_apple_id():
    """The bundled snapshot must contain Apple (company ID 76). If
    ``make update-vendors`` is ever broken or the file is missing,
    this fails loudly."""
    vendors = load_vendors()
    assert vendors.get(76) == "Apple, Inc."


# ------------------------------------------------------------------
# 3. Service category inference
# ------------------------------------------------------------------

def test_service_category_heart_rate():
    """Bluetooth SIG 16-bit UUID 180D is the Heart Rate service."""
    assert service_category("180D") == "Heart Rate"


def test_service_category_hid():
    """1812 is the Human Interface Device profile (keyboard / mouse)."""
    assert service_category("1812") == "HID"


def test_service_category_unknown_passthrough():
    """An unknown service UUID is returned unchanged — the user can
    look it up themselves rather than seeing a misleading label."""
    raw = "ABCD"
    assert service_category(raw) == raw


def test_service_category_long_form_normalised():
    """macOS sometimes reports 16-bit UUIDs in their full 128-bit form
    (Bluetooth SIG base UUID with the 16-bit code embedded). The
    lookup must match either form."""
    long_form = "0000180D-0000-1000-8000-00805F9B34FB"
    assert service_category(long_form) == "Heart Rate"


# ------------------------------------------------------------------
# 4. Decay / TTL
# ------------------------------------------------------------------

def test_expire_drops_unseen_devices():
    """A device whose last_seen is older than ttl_s is dropped from
    the snapshot. Keeps the TUI from hoarding stale rows after a
    device walks out of range."""
    t0 = datetime(2026, 5, 6, 12, 0, 0, tzinfo=timezone.utc)
    devices: dict[str, BLEDevice] = {}
    update_from_line(devices, SAMPLE_AIRPODS, vendors=VENDORS, now=t0)
    pruned = expire_devices(
        devices, now=t0 + timedelta(seconds=60), ttl_s=30.0,
    )
    assert pruned == {}


def test_expire_keeps_recent_devices():
    """A device seen within ttl_s is retained."""
    t0 = datetime(2026, 5, 6, 12, 0, 0, tzinfo=timezone.utc)
    devices: dict[str, BLEDevice] = {}
    update_from_line(devices, SAMPLE_AIRPODS, vendors=VENDORS, now=t0)
    pruned = expire_devices(
        devices, now=t0 + timedelta(seconds=10), ttl_s=30.0,
    )
    assert len(pruned) == 1


# ------------------------------------------------------------------
# 5. Fuzzy merge
# ------------------------------------------------------------------

def test_merge_folds_same_vendor_and_name_within_rssi_window():
    """Two records sharing (vendor_id, name) and within ±10 dB merge
    into one row. ad_count is summed; merged_count records how many
    folded so the renderer can show a (merged N) badge."""
    now = datetime(2026, 5, 6, 12, 0, 0, tzinfo=timezone.utc)
    a = _device("aaa", name="AirPods Pro", vendor_id=76, rssi=-52,
                ad_count=3, now=now)
    b = _device("bbb", name="AirPods Pro", vendor_id=76, rssi=-58,
                ad_count=2, now=now)
    merged = merge_for_display([a, b])
    assert len(merged) == 1
    m = merged[0]
    assert m.merged_count == 2
    assert m.ad_count == 5
    assert m.name == "AirPods Pro"
    assert m.vendor_id == 76


def test_merge_keeps_distant_rssi_separate():
    """Two records sharing identity but with RSSIs > 10 dB apart stay
    separate — they are likely different physical devices in different
    rooms broadcasting under the same generic name."""
    now = datetime(2026, 5, 6, 12, 0, 0, tzinfo=timezone.utc)
    a = _device("aaa", name="generic", vendor_id=42, rssi=-40, now=now)
    b = _device("bbb", name="generic", vendor_id=42, rssi=-80, now=now)
    merged = merge_for_display([a, b])
    assert len(merged) == 2
    assert all(d.merged_count == 1 for d in merged)


def test_merge_does_not_combine_anonymous_devices():
    """Devices with both vendor_id and name None are too anonymous to
    safely merge — the heuristic would conflate every nameless beacon
    nearby. Spec calls this out under 'never silently fall back'."""
    now = datetime(2026, 5, 6, 12, 0, 0, tzinfo=timezone.utc)
    a = _device("aaa", name=None, vendor_id=None, rssi=-50, now=now)
    b = _device("bbb", name=None, vendor_id=None, rssi=-52, now=now)
    merged = merge_for_display([a, b])
    assert len(merged) == 2


def test_merge_sorts_by_rssi_descending():
    """The post-merge list is ordered by signal strength so the closest
    device is at the top of the panel."""
    now = datetime(2026, 5, 6, 12, 0, 0, tzinfo=timezone.utc)
    weak = _device("weak", name="A", vendor_id=1, rssi=-80, now=now)
    strong = _device("strong", name="B", vendor_id=2, rssi=-40, now=now)
    merged = merge_for_display([weak, strong])
    assert merged[0].identifier == "strong"
    assert merged[1].identifier == "weak"


# ------------------------------------------------------------------
# 6. Permission denied
# ------------------------------------------------------------------

def test_permission_denied_line_surfaces_state():
    """An error line with 'unauthorized' marker flips state to
    'permission_denied' without crashing."""
    devices: dict[str, BLEDevice] = {}
    line = json.dumps({"error": "bluetooth unauthorized"})
    state = update_from_line(devices, line, vendors=VENDORS)
    assert state == "permission_denied"
    assert devices == {}


def test_permission_denied_via_subprocess_exit_code():
    """Helper exiting with code 3 (CBManager .unauthorized) flips the
    poller's permission_state to 'denied' even when no error JSON
    line was emitted before the exit."""
    asyncio.run(_run_poller_with_stream(
        lines=[],
        return_code=3,
        assert_state="denied",
    ))


# ------------------------------------------------------------------
# 7. Subprocess crash
# ------------------------------------------------------------------

def test_subprocess_crash_does_not_raise():
    """Helper killed mid-stream (SIGKILL → 137) leaves the poller
    quiet: future snapshots are empty, no exception bubbles up to
    the consumer."""
    asyncio.run(_run_poller_with_stream(
        lines=[SAMPLE_AIRPODS],
        return_code=137,
        # We don't assert state because the spec only requires
        # "no exception bubbles up". Having parsed one ad before the
        # crash leaves state as 'granted', which is also fine.
        min_snapshots=2,
    ))


def test_helper_binary_missing_marks_unavailable():
    """If asyncio.create_subprocess_exec raises OSError (binary not
    found), the poller flips state to 'unavailable' and keeps yielding
    empty snapshots."""

    async def go() -> None:
        async def boom() -> Any:
            raise FileNotFoundError("no helper")
        poller = BLEPoller("/nonexistent", _spawn=boom,
                           snapshot_interval_s=0.05)
        snapshots: list[BLEScanUpdate] = []
        gen = poller.events()
        try:
            async for snap in gen:
                snapshots.append(snap)
                if len(snapshots) >= 2:
                    break
        finally:
            await gen.aclose()
        assert any(s.permission_state == "unavailable" for s in snapshots)

    asyncio.run(go())


# ------------------------------------------------------------------
# 8. Malformed JSON line
# ------------------------------------------------------------------

def test_malformed_line_skipped_subsequent_parsed():
    """One garbage line in the stream is skipped; subsequent valid
    lines parse into devices normally."""
    devices: dict[str, BLEDevice] = {}
    update_from_line(devices, "this is not json", vendors=VENDORS)
    assert devices == {}
    update_from_line(devices, SAMPLE_AIRPODS, vendors=VENDORS)
    assert len(devices) == 1


def test_line_without_id_field_skipped():
    """Defensive: a JSON object without 'id' is skipped, not raised."""
    devices: dict[str, BLEDevice] = {}
    line = json.dumps({"rssi_dbm": -60, "name": "no-id-here"})
    update_from_line(devices, line, vendors=VENDORS)
    assert devices == {}


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------

def _device(
    identifier: str,
    *,
    name: str | None,
    vendor_id: int | None,
    rssi: int | None,
    ad_count: int = 1,
    now: datetime,
) -> BLEDevice:
    return BLEDevice(
        identifier=identifier,
        name=name,
        vendor=lookup_vendor(vendor_id, VENDORS),
        vendor_id=vendor_id,
        services=(),
        rssi_dbm=rssi,
        is_connectable=False,
        first_seen=now,
        last_seen=now,
        ad_count=ad_count,
    )


class _FakeStdout:
    """Async-iterable stand-in for asyncio.StreamReader.

    Yields each pre-supplied byte line in turn, then completes. The
    poller's reader loop only relies on the async-iterator interface;
    we don't need to reach for the full StreamReader machinery.
    """

    def __init__(self, lines: list[bytes]) -> None:
        self._lines = lines

    def __aiter__(self) -> "_FakeStdout":
        self._iter = iter(self._lines)
        return self

    async def __anext__(self) -> bytes:
        try:
            return next(self._iter)
        except StopIteration as exc:
            raise StopAsyncIteration from exc


class _FakeProc:
    """Mimics the subset of asyncio.subprocess.Process used by BLEPoller."""

    def __init__(self, stdout_lines: list[bytes], return_code: int) -> None:
        self.stdout = _FakeStdout(stdout_lines)
        self._return_code = return_code
        self.returncode: int | None = None

    async def wait(self) -> int:
        self.returncode = self._return_code
        return self._return_code

    def terminate(self) -> None:
        # Cooperatively exit on terminate so stop() works correctly
        # even after the stream has drained.
        self.returncode = self._return_code


async def _run_poller_with_stream(
    *,
    lines: list[str],
    return_code: int,
    assert_state: str | None = None,
    min_snapshots: int = 2,
    max_snapshots: int = 30,
) -> None:
    encoded = [(line + "\n").encode("utf-8") for line in lines]

    async def fake_spawn() -> Any:
        return _FakeProc(encoded, return_code)

    poller = BLEPoller(
        "/fake/helper", _spawn=fake_spawn,
        snapshot_interval_s=0.02, ttl_s=30.0,
    )
    snapshots: list[BLEScanUpdate] = []
    gen = poller.events()
    try:
        async for snap in gen:
            snapshots.append(snap)
            done = len(snapshots) >= min_snapshots
            if assert_state is not None:
                done = done and any(
                    s.permission_state == assert_state for s in snapshots
                )
            if done or len(snapshots) >= max_snapshots:
                break
    finally:
        await gen.aclose()

    assert len(snapshots) >= min_snapshots
    if assert_state is not None:
        assert any(s.permission_state == assert_state for s in snapshots), (
            f"expected state {assert_state!r} in "
            f"{[s.permission_state for s in snapshots]!r}"
        )
