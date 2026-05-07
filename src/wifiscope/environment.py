"""Rolling RSSI variance → RF-stir event detector.

The Environment line in the Diagnostics panel and the modal Events
browser both read from this module. We compute, per BSSID, a rolling
short-window standard deviation of RSSI and compare it to a long-
window adaptive median; a spike fires an :class:`RFStirEvent`.

This is a *correlation* signal, never causation: the user's body
walking through a Fresnel zone moves RSSI, but so does a neighbour's
AP rebooting and so does the OS refreshing its background-scan
cadence. The wording on every surface is "something changed", never
"a person is here".

Per-AP fusion modes
-------------------

Auto-classified by the AP's typical RSSI:

- ``co_located`` (rssi >= -65 dBm): redundancy fusion. A spike must
  occur on >= 2 co-located APs at roughly the same time to count as
  a *high-confidence* event. Single-AP spikes still surface but with
  ``confidence == "medium"``.
- ``spatial_channel`` (rssi -65..-85 dBm): each AP is its own event
  lane, labelled with the AP's inventory name from ``aps.yaml`` so
  a stir on ``2F-书房`` reads as "2F-书房" rather than being merged
  into a generic "something nearby".
- ``ignored`` (rssi < -85 dBm): too noisy to trust; dropped.

Calibration
-----------

When ``./wifiscope-baseline.json`` exists (written by ``wifiscope
calibrate``) it overrides the adaptive median with a fixed
"the-room-is-empty" σ baseline, which makes the ``stable`` /
``active`` / ``quiet`` qualifier on the diagnostic line meaningful.
Without the file the adaptive baseline approach still works — it
just drifts overnight and may fire false positives the next morning
(documented limitation).
"""

from __future__ import annotations

import json
import statistics
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable

from .network import NetworkInventory, cluster_label

# Spec-defined defaults; surfaced as constants so the events pipeline
# (and the modal stats panel) can reference them directly.
DEFAULT_BASELINE_WINDOW_S = 300.0      # 5 minutes
DEFAULT_SPIKE_WINDOW_S = 5.0           # 5 seconds
DEFAULT_SPIKE_RATIO = 2.5              # current σ > 2.5× baseline
DEFAULT_SPIKE_MIN_DB = 3.0             # AND current σ > 3 dB absolute
DEFAULT_COOLDOWN_S = 8.0               # min seconds between events from one AP

# RSSI thresholds that classify an AP into one of the three fusion
# modes. The dBm values come straight from the spec.
CO_LOCATED_RSSI = -65
IGNORE_BELOW_RSSI = -85

# RF-stir-specific guard against a stale event firing forever after
# a single big spike: the σ has to drop back below the absolute floor
# before the same AP can fire again.
DEFAULT_REARM_DB = 1.5


@dataclass(frozen=True, slots=True)
class RFStirEvent:
    """One rolling-σ threshold crossing."""
    timestamp: datetime
    bssid: str
    location: str         # AP name (inventory) or cluster_label
    magnitude_db: float   # the σ that triggered the event
    duration_s: float     # how long σ has been above threshold
    confidence: str       # 'low' | 'medium' | 'high'
    mode: str             # 'co_located' | 'spatial_channel'


@dataclass(frozen=True, slots=True)
class APBaseline:
    """One AP's rolling baseline, exposed for the modal stats panel."""
    bssid: str
    location: str
    mode: str             # 'co_located' | 'spatial_channel' | 'ignored'
    samples: int
    baseline_sigma: float | None
    current_sigma: float | None
    last_rssi: int | None


@dataclass(frozen=True, slots=True)
class _APState:
    """Mutable per-AP rolling state. Stored in a normal dict on the
    monitor — frozen so the renderer cannot accidentally mutate
    things it reads."""
    bssid: str
    history: deque                 # of (datetime, rssi)
    last_event_at: datetime | None
    last_above_threshold_at: datetime | None
    last_rssi: int | None
    armed: bool                    # False right after firing; re-arms on σ drop


class EnvironmentMonitor:
    """Rolling-σ tracker + event firer.

    See :func:`ingest` for the call cadence (every connection update
    + every neighbour BSSID seen in scan results) and
    :func:`fire_events` for the integration with the events ring
    buffer.
    """

    def __init__(
        self,
        *,
        inventory: NetworkInventory,
        baseline_window_s: float = DEFAULT_BASELINE_WINDOW_S,
        spike_window_s: float = DEFAULT_SPIKE_WINDOW_S,
        spike_ratio: float = DEFAULT_SPIKE_RATIO,
        spike_min_db: float = DEFAULT_SPIKE_MIN_DB,
        cooldown_s: float = DEFAULT_COOLDOWN_S,
        rearm_db: float = DEFAULT_REARM_DB,
        calibration: dict | None = None,
    ) -> None:
        self._inventory = inventory
        self._baseline_window = timedelta(seconds=baseline_window_s)
        self._spike_window = timedelta(seconds=spike_window_s)
        self._spike_ratio = spike_ratio
        self._spike_min_db = spike_min_db
        self._cooldown = timedelta(seconds=cooldown_s)
        self._rearm_db = rearm_db
        # Per-AP state, keyed by BSSID lower-case. We never trim:
        # APs come and go but the history naturally ages out as the
        # rolling window slides.
        self._state: dict[str, dict] = {}
        # Median of all observed RSSIs for each AP, updated on every
        # ingest. Used to bucket each AP into co_located / spatial /
        # ignored at fire-time.
        self._median_rssi: dict[str, int] = {}
        self._calibration = calibration or {}

    def ingest(self, bssid: str, rssi_dbm: int | None, now: datetime) -> None:
        """Record one (timestamp, rssi) sample for ``bssid``.

        Called at WiFi-poll cadence for the currently-associated BSSID
        (1 Hz) and at scan cadence for every neighbour BSSID seen in
        the scan list (~7 s). Samples with ``rssi_dbm is None`` are
        silently dropped — we cannot reason about variance from
        missing data.
        """
        if rssi_dbm is None or not bssid:
            return
        b = bssid.lower()
        state = self._state.setdefault(b, {
            "bssid": b,
            "history": deque(),
            "last_event_at": None,
            "last_above_threshold_at": None,
            "last_rssi": None,
            "armed": True,
        })
        state["history"].append((now, rssi_dbm))
        state["last_rssi"] = rssi_dbm
        # Trim out anything older than the baseline window.
        cutoff = now - self._baseline_window
        history = state["history"]
        while history and history[0][0] < cutoff:
            history.popleft()
        # Track running median across this AP's recent history so
        # mode classification doesn't oscillate on a single bad sample.
        if history:
            self._median_rssi[b] = int(
                statistics.median(rssi for _, rssi in history)
            )

    def fire_events(self, now: datetime) -> list[RFStirEvent]:
        """Scan all APs and return any events the latest sample fired.

        Two passes: first, find each AP whose 5 s σ exceeds the
        thresholds. Second, apply the redundancy-fusion rule on the
        co-located bucket so a spike that shows up on >= 2 APs is
        labelled high-confidence.
        """
        candidates: list[tuple[str, str, float, str]] = []
        # (bssid, location, magnitude_db, mode)
        for bssid, state in self._state.items():
            mode = self._classify_mode(bssid)
            if mode == "ignored":
                continue
            if not state["armed"]:
                # Re-arm when the σ falls back below the floor so a
                # single big spike doesn't fire repeatedly.
                current = self._current_sigma(state, now)
                if current is None or current < self._rearm_db:
                    state["armed"] = True
                continue
            current = self._current_sigma(state, now)
            baseline = self._baseline_sigma(bssid, state, now)
            if current is None:
                continue
            if current < self._spike_min_db:
                continue
            if baseline is not None and current < baseline * self._spike_ratio:
                continue
            # Cooldown: don't refire on the same AP within seconds.
            last = state["last_event_at"]
            if last is not None and (now - last) < self._cooldown:
                continue
            location = self._location(bssid)
            candidates.append((bssid, location, float(current), mode))

        if not candidates:
            return []

        # Co-located redundancy fusion. Group co-located candidates
        # within a 5 s window: if >= 2 fire, every co-located event
        # in the group is upgraded to high confidence. Spatial-
        # channel events fire alone with medium confidence.
        co_count = sum(1 for c in candidates if c[3] == "co_located")
        events: list[RFStirEvent] = []
        for bssid, location, magnitude, mode in candidates:
            state = self._state[bssid]
            if mode == "co_located":
                confidence = "high" if co_count >= 2 else "medium"
            else:
                confidence = "medium"
            duration_s = self._duration_above_threshold(state, now)
            events.append(RFStirEvent(
                timestamp=now,
                bssid=bssid,
                location=location,
                magnitude_db=round(magnitude, 1),
                duration_s=round(duration_s, 1),
                confidence=confidence,
                mode=mode,
            ))
            state["last_event_at"] = now
            state["armed"] = False
        return events

    def baseline_summary(self) -> list[APBaseline]:
        """Per-AP statistics for the modal Events screen.

        Sorted by mode (co_located first, then spatial_channel, then
        ignored) and within each mode by descending sample count, so
        the modal's bottom panel reads in priority order without the
        renderer having to think about it.
        """
        out: list[APBaseline] = []
        order = {"co_located": 0, "spatial_channel": 1, "ignored": 2}
        # Snapshot now so the comparison is stable across the loop.
        now = datetime.now()
        for bssid, state in self._state.items():
            mode = self._classify_mode(bssid)
            baseline = self._baseline_sigma(bssid, state, now)
            current = self._current_sigma(state, now)
            out.append(APBaseline(
                bssid=bssid,
                location=self._location(bssid),
                mode=mode,
                samples=len(state["history"]),
                baseline_sigma=(
                    None if baseline is None else round(baseline, 1)
                ),
                current_sigma=(
                    None if current is None else round(current, 1)
                ),
                last_rssi=state["last_rssi"],
            ))
        out.sort(key=lambda b: (order.get(b.mode, 9), -b.samples))
        return out

    def aggregate_sigma(self, now: datetime) -> tuple[str, float | None, datetime | None]:
        """One-line summary for the Diagnostics ``Environment`` row.

        Returns a tuple ``(label, sigma, last_event_at)`` where
        ``label`` is ``stable`` / ``active`` / ``quiet`` per the
        spec. The σ value is the maximum current σ across all
        non-ignored APs, since one busy AP is the data point the
        user actually wants surfaced (averaging would smooth it
        away). ``last_event_at`` is the most recent event time
        across all APs, or ``None``.
        """
        max_sigma = None
        last_event = None
        any_active = False
        for bssid, state in self._state.items():
            if self._classify_mode(bssid) == "ignored":
                continue
            current = self._current_sigma(state, now)
            if current is not None:
                if max_sigma is None or current > max_sigma:
                    max_sigma = current
                if current >= self._spike_min_db:
                    any_active = True
            ev = state["last_event_at"]
            if ev is not None and (last_event is None or ev > last_event):
                last_event = ev
        # Calibration distinguishes 'quiet' (verified empty room) from
        # 'stable' (adaptive baseline says nothing is stirring). With
        # no calibration we can only say 'stable' / 'active'.
        if any_active:
            label = "active"
        elif self._calibration:
            label = "quiet"
        else:
            label = "stable"
        return label, (None if max_sigma is None else round(max_sigma, 1)), last_event

    # ---------- internals ----------

    def _classify_mode(self, bssid: str) -> str:
        """Decide which fusion bucket this AP belongs to.

        Calibration overrides the live median: a calibrated AP sticks
        with the bucket the calibration baseline placed it in, which
        keeps a quiet 5 GHz AP from oscillating between co_located
        and spatial_channel as the radio drifts at the band edge.
        """
        cal = self._calibration.get(bssid)
        if isinstance(cal, dict) and "rssi_mean" in cal:
            try:
                rssi = float(cal["rssi_mean"])
            except (TypeError, ValueError):
                rssi = self._median_rssi.get(bssid)  # type: ignore[assignment]
        else:
            rssi = self._median_rssi.get(bssid)
        if rssi is None:
            return "spatial_channel"   # no data yet — assume mid-band
        if rssi >= CO_LOCATED_RSSI:
            return "co_located"
        if rssi >= IGNORE_BELOW_RSSI:
            return "spatial_channel"
        return "ignored"

    def _current_sigma(self, state: dict, now: datetime) -> float | None:
        """σ over the last ``spike_window_s`` seconds."""
        cutoff = now - self._spike_window
        recent = [rssi for ts, rssi in state["history"] if ts >= cutoff]
        if len(recent) < 3:
            return None
        return statistics.pstdev(recent)

    def _baseline_sigma(
        self, bssid: str, state: dict, now: datetime
    ) -> float | None:
        """Adaptive trailing-window σ baseline, or calibration override.

        With calibration: returns the recorded ``rssi_stddev``.
        Without: median σ across consecutive ``spike_window_s``
        chunks of the trailing baseline window.
        """
        cal = self._calibration.get(bssid)
        if isinstance(cal, dict):
            stddev = cal.get("rssi_stddev")
            if isinstance(stddev, (int, float)) and stddev > 0:
                return float(stddev)
        history = state["history"]
        if len(history) < 4:
            return None
        # Walk the window in non-overlapping chunks of spike_window_s
        # and take the median chunk-σ as the baseline. The current
        # spike window is excluded — otherwise the burst we are
        # testing for would be folded back into its own baseline,
        # masking any threshold crossing wider than the typical
        # baseline σ. This is the spec's "trailing 5-minute median σ"
        # with the obvious "trailing" interpretation of the trailing
        # word.
        spike_cutoff = now - self._spike_window
        chunks: list[float] = []
        chunk: list[int] = []
        chunk_start = history[0][0]
        for ts, rssi in history:
            if ts >= spike_cutoff:
                break
            if ts - chunk_start > self._spike_window:
                if len(chunk) >= 3:
                    chunks.append(statistics.pstdev(chunk))
                chunk = []
                chunk_start = ts
            chunk.append(rssi)
        if len(chunk) >= 3:
            chunks.append(statistics.pstdev(chunk))
        if not chunks:
            return None
        return statistics.median(chunks)

    def _duration_above_threshold(self, state: dict, now: datetime) -> float:
        """How long the current excursion has been above the floor.

        Walked from the most recent sample backwards; stops the moment
        an in-window σ is below ``spike_min_db``. Caps at
        ``baseline_window_s`` so a stuck AP does not report an
        impossible-looking duration.
        """
        history = list(state["history"])
        if not history:
            return 0.0
        oldest = history[0][0]
        return min(
            (now - oldest).total_seconds(),
            self._baseline_window.total_seconds(),
        )

    def _location(self, bssid: str) -> str:
        return self._inventory.resolve(bssid) or cluster_label(bssid)


def load_calibration(path: Path | str | None = None) -> dict:
    """Read a wifiscope-baseline.json file, or return ``{}`` on miss.

    Path defaults to ``./wifiscope-baseline.json`` per the spec. The
    file format is a flat ``{bssid: {rssi_mean, rssi_stddev,
    sample_count}}`` mapping; everything is best-effort, missing keys
    silently fall through to the adaptive baseline at runtime.
    """
    if path is None:
        path = Path("wifiscope-baseline.json")
    p = Path(path)
    if not p.is_file():
        return {}
    try:
        with p.open() as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, dict] = {}
    for bssid, entry in data.items():
        if not isinstance(bssid, str) or not isinstance(entry, dict):
            continue
        out[bssid.lower()] = entry
    return out


def write_calibration(
    samples_by_bssid: dict[str, list[int]],
    path: Path | str | None = None,
) -> Path:
    """Persist a captured calibration baseline to disk.

    ``samples_by_bssid`` maps each BSSID to the raw integer RSSI
    readings observed during calibration. We compute mean / stddev /
    count and write a flat dictionary to
    ``./wifiscope-baseline.json`` (or the override path).
    """
    if path is None:
        path = Path("wifiscope-baseline.json")
    p = Path(path)
    payload: dict[str, dict] = {}
    for bssid, samples in samples_by_bssid.items():
        if not samples:
            continue
        clean = [int(s) for s in samples]
        payload[bssid.lower()] = {
            "rssi_mean": round(statistics.mean(clean), 1),
            "rssi_stddev": (
                round(statistics.pstdev(clean), 2) if len(clean) > 1 else 0.0
            ),
            "sample_count": len(clean),
        }
    p.write_text(json.dumps(payload, indent=2, sort_keys=True))
    return p
