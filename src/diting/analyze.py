"""Rule-based JSONL log analyser.

Reads a diting event log (the JSONL format produced by both
``diting monitor`` and ``diting --log``) and turns it into
a human-readable report: time span, event counts, link timeline,
plus a list of heuristic insights and TODOs derived from
patterns in the data.

Pure rules — no LLM. Each heuristic is a small dataclass with
an explicit trigger condition and an actionable hint, so the
output reads as a checklist rather than a prose dump.

Surface a sibling test layer in ``tests/test_analyze.py`` for
each heuristic so the trigger conditions are pinned to concrete
event shapes rather than buried in the rendering code.
"""
from __future__ import annotations

import json
import re
import statistics
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from . import i18n
from .i18n import pad_cells, t


# ---------- parsing ----------

def parse_jsonl(path: Path) -> list[dict[str, Any]]:
    """Read a JSONL log file. Malformed lines (truncated last
    line from a hard kill, anything that isn't a JSON object)
    are silently skipped — a real-world log is allowed to have
    a partial trailing line and the analyser must not crash."""
    out: list[dict[str, Any]] = []
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        out.append(obj)
    return out


def _parse_ts(s: str) -> datetime | None:
    """Forgiving ISO-8601 parser. Returns None on garbage so the
    analyser's downstream sorting / windowing skips a bad row
    rather than blowing up the whole report."""
    if not isinstance(s, str):
        return None
    try:
        # Accept the trailing 'Z' shortcut too; fromisoformat in
        # Python 3.11+ handles it natively.
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


# ---------- model ----------

@dataclass(frozen=True, slots=True)
class Insight:
    """One rule-derived observation about the log.

    ``severity`` is ``info`` | ``note`` | ``warn`` — purely
    a hint for the renderer's colour / icon choice. ``todo``
    is the actionable line shown under the observation; empty
    string means the insight is informational only.
    """
    severity: str
    title: str
    detail: str
    todo: str = ""


@dataclass(frozen=True, slots=True)
class NetworkAggregate:
    """Per-network event-count breakdown for the cross-session view."""
    network_label: str   # "Meituan (5G)" or "(unknown network)"
    bssid: str | None
    total: int
    counts_by_type: dict[str, int]
    ssid: str | None = None


@dataclass(frozen=True, slots=True)
class DailyCount:
    """One day's event count + rolling 7-day average."""
    date: str           # ISO YYYY-MM-DD
    total: int
    rolling_7d_avg: float


@dataclass(frozen=True, slots=True)
class TopBSSID:
    bssid: str
    label: str          # AP name + alias / cluster
    roam_count: int
    stir_count: int


@dataclass(frozen=True, slots=True)
class TopBLE:
    identifier: str
    label: str          # vendor + name when available
    seen_count: int


@dataclass(frozen=True, slots=True)
class TopLAN:
    mac: str
    label: str          # vendor + bonjour name + IP
    rotation_count: int


@dataclass(frozen=True, slots=True)
class TopContributors:
    bssids: tuple[TopBSSID, ...]
    ble_identifiers: tuple[TopBLE, ...]
    lan_hosts: tuple[TopLAN, ...]


# ---------- temporal / population (enrich-temporal-analysis) ----------

# A capture this long counts as a "long-timeline run" — temporal analysis
# enables on span alone, not just multi-file / --since. A 13 h overnight
# log IS a long-timeline run.
_LONG_SPAN = timedelta(hours=2)
# Dwell band edges (seconds): a pass-by vs a lingering vs a fixture.
_DWELL_TRANSIENT_S = 120        # < 2 min
_DWELL_RESIDENT_S = 1800        # >= 30 min
# A category's activity is "concentrated" when its busiest few hours hold
# at least this share of the total.
_CONCENTRATION_HOURS = 3
_CONCENTRATION_SHARE = 0.6
# A device "present across most of the span" (>= this fraction of the
# spanned hours, with a small floor) reads as a fixture/regular.
_RESIDENT_HOURS_FRAC = 0.5
_RESIDENT_HOURS_FLOOR = 3
# Scene → the band of hours that scene expects to be quiet. Activity here
# is more noteworthy than the same activity in-hours.
_EXPECTED_QUIET_HOURS = {
    "office": range(0, 6),       # overnight in an office
    "home": range(10, 17),       # the workday at home
}


@dataclass(frozen=True, slots=True)
class DwellSummary:
    """seen→left dwell distribution for BLE devices over the log."""
    n: int
    p50_s: float
    p90_s: float
    transient: int      # dwell < _DWELL_TRANSIENT_S
    lingering: int      # in between
    resident: int       # dwell >= _DWELL_RESIDENT_S


@dataclass(frozen=True, slots=True)
class PopulationSummary:
    """Distinct PHYSICAL BLE devices over the log, keyed on the stable
    familiarity ladder (never the rotating `identifier`)."""
    distinct_devices: int
    residents: int          # present across most of the spanned hours
    passersby: int          # seen in exactly one hour
    unkeyable_sightings: int  # sightings with no stable identity (honest)


@dataclass(frozen=True, slots=True)
class HourlyRhythm:
    """One category's distribution across the 24 hours of the day."""
    category: str
    peak_hour: int
    peak_count: int
    quiet_hour: int
    quiet_count: int
    top_hours_share: float   # share of total in the busiest _CONCENTRATION_HOURS
    total: int

    @property
    def concentrated(self) -> bool:
        return self.top_hours_share >= _CONCENTRATION_SHARE


def _ble_stable_key(row: dict[str, Any]) -> str | None:
    """Stable physical-device identity for a BLE JSONL row, via the same
    ladder ``familiarity.familiarity_key`` uses — manufacturer payload →
    service-data id → (vendor_id, name) → vendor-group → None — so the
    offline analyser and the live store can't drift. NEVER the rotating
    `identifier` (a single device emits many). In serialised logs only
    name / vendor survive (the richer rungs are in-memory-only), so most
    rows resolve to the (name) / vendor-group tail; that's recurrence
    grouping for a population count, not a per-device or trust claim."""
    from .familiarity import familiarity_key
    return familiarity_key(
        "ble",
        manufacturer_hex=row.get("manufacturer_hex"),
        vendor_id=row.get("vendor_id"),
        name=row.get("name"),
        service_data_id=row.get("service_data_id"),
        vendor=row.get("vendor"),
    )


def aggregate_ble_dwell(events: list[dict[str, Any]]) -> DwellSummary | None:
    """Dwell distribution from ``ble_device_left.seen_for_seconds``.
    Returns None when there are no usable left events."""
    dwells = [
        float(e["seen_for_seconds"])
        for e in events
        if e.get("type") == "ble_device_left"
        and isinstance(e.get("seen_for_seconds"), (int, float))
        and e["seen_for_seconds"] >= 0
    ]
    if not dwells:
        return None
    dwells.sort()
    p90 = dwells[min(len(dwells) - 1, (len(dwells) * 9) // 10)]
    return DwellSummary(
        n=len(dwells),
        p50_s=statistics.median(dwells),
        p90_s=p90,
        transient=sum(1 for d in dwells if d < _DWELL_TRANSIENT_S),
        lingering=sum(
            1 for d in dwells if _DWELL_TRANSIENT_S <= d < _DWELL_RESIDENT_S
        ),
        resident=sum(1 for d in dwells if d >= _DWELL_RESIDENT_S),
    )


def aggregate_ble_population(
    events: list[dict[str, Any]],
) -> PopulationSummary | None:
    """Distinct physical BLE devices + a resident-vs-passer-by split,
    keyed on the stable familiarity ladder. Returns None with no BLE
    sightings."""
    hours_by_key: dict[str, set[int]] = {}
    unkeyable = 0
    spanned: set[int] = set()
    any_ble = False
    for e in events:
        if e.get("type") != "ble_device_seen":
            continue
        any_ble = True
        ts = _parse_ts(e.get("ts", ""))
        if ts is None:
            continue
        spanned.add(ts.hour)
        key = _ble_stable_key(e)
        if key is None:
            unkeyable += 1
            continue
        hours_by_key.setdefault(key, set()).add(ts.hour)
    if not any_ble:
        return None
    # A device is a "resident/fixture" when it shows up across most of the
    # hours the log actually spans (with a small floor so a 4 h log still
    # has a meaningful bar).
    resident_cut = max(
        _RESIDENT_HOURS_FLOOR,
        int(len(spanned) * _RESIDENT_HOURS_FRAC),
    )
    residents = sum(1 for hs in hours_by_key.values() if len(hs) >= resident_cut)
    passersby = sum(1 for hs in hours_by_key.values() if len(hs) == 1)
    return PopulationSummary(
        distinct_devices=len(hours_by_key),
        residents=residents,
        passersby=passersby,
        unkeyable_sightings=unkeyable,
    )


def aggregate_hourly_rhythm(
    hour_of_day: dict[int, dict[str, int]], category: str,
) -> HourlyRhythm | None:
    """Peak / quiet hour + busiest-few-hours concentration for one event
    category, from the already-computed hour buckets. None when the
    category has no events."""
    counts = {h: hour_of_day.get(h, {}).get(category, 0) for h in range(24)}
    total = sum(counts.values())
    if total == 0:
        return None
    active = {h: n for h, n in counts.items() if n > 0}
    peak_hour = max(active, key=lambda h: active[h])
    quiet_hour = min(active, key=lambda h: active[h])
    top = sorted(active.values(), reverse=True)[:_CONCENTRATION_HOURS]
    return HourlyRhythm(
        category=category,
        peak_hour=peak_hour,
        peak_count=active[peak_hour],
        quiet_hour=quiet_hour,
        quiet_count=active[quiet_hour],
        top_hours_share=sum(top) / total,
        total=total,
    )


def aggregate_co_peaks(
    rhythms: dict[str, HourlyRhythm],
) -> tuple[tuple[int, tuple[str, ...]], ...]:
    """Hours where two or more categories share their peak — the raw
    material for a cross-signal coincidence insight. Sorted by hour."""
    by_hour: dict[int, list[str]] = {}
    for cat, rh in rhythms.items():
        by_hour.setdefault(rh.peak_hour, []).append(cat)
    return tuple(
        (h, tuple(sorted(cats)))
        for h, cats in sorted(by_hour.items())
        if len(cats) >= 2
    )


@dataclass(frozen=True, slots=True)
class Report:
    """Aggregated stats + insights for a log (or merged set of logs)."""
    path: str
    span_start: datetime | None
    span_end: datetime | None
    total_events: int
    counts_by_type: dict[str, int]
    associations: list[tuple[str | None, str | None]]   # (ssid, bssid)
    roams: int
    band_switches: int
    inter_ap_roams: int
    disassociates: int
    stir_count: int
    stir_modes: dict[str, int]
    stir_confidences: dict[str, int]
    stir_locations: dict[str, int]
    stir_sigma_min: float | None
    stir_sigma_max: float | None
    stir_sigma_p50: float | None
    latency_spike_count: int
    latency_spike_by_target: dict[str, int]
    latency_spike_max_rtt: float | None
    loss_burst_count: int
    loss_burst_max_pct: float | None
    network_changes: list[tuple[str | None, str | None]] = field(
        default_factory=list,
    )
    distinct_router_ips: tuple[str, ...] = ()
    insights: list[Insight] = field(default_factory=list)
    # ---------- cross-session (A2) ----------
    # Source files that fed this report. Single-element list for
    # legacy single-file callers; longer when shell expanded a glob.
    source_paths: tuple[str, ...] = ()
    # `--since` filter that was applied; None for unfiltered runs.
    since: timedelta | None = None
    # Aggregations — only populated when source_paths > 1 OR since
    # is set. The renderer gates the cross-session blocks on these
    # being non-empty so single-file no-since callers see the legacy
    # report unchanged.
    hour_of_day: dict[int, dict[str, int]] = field(default_factory=dict)
    day_of_week_x_hour: tuple[tuple[int, ...], ...] = ()
    per_network: tuple[NetworkAggregate, ...] = ()
    daily_trend: tuple[DailyCount, ...] = ()
    top_contributors: TopContributors | None = None
    # ---------- session_meta (scene awareness) ----------
    # Scenes observed across the input session(s). Empty tuple when no
    # session_meta line was found (pre-scene-aware capture). Single-
    # element tuple for one consistent scene; multi-element when a
    # glob spans different scenes (`Scenes: 3 × home, 1 × office`).
    scenes: tuple[str, ...] = ()
    # Map of scene → source ("cli" / "env" / "default") observed in
    # input session_meta. When the same scene was set multiple times
    # via different sources across input files, the most specific
    # source wins (cli > env > default).
    scene_sources: dict[str, str] = field(default_factory=dict)
    # Observed env counters from session_meta lines, used to enrich
    # the LLM scene-context paragraph with concrete numbers
    # ("observed BSSID count ~80"). Populated from per-event data,
    # not from session_meta itself.
    observed_bssid_count: int = 0
    observed_ble_identifier_count: int = 0
    # ---------- temporal / population (enrich-temporal-analysis) ----------
    # Populated alongside the cross-session aggregations (same gate, now
    # also fired by a long span). Empty / None on short single-session runs.
    ble_dwell: DwellSummary | None = None
    ble_population: PopulationSummary | None = None
    hourly_rhythms: dict[str, "HourlyRhythm"] = field(default_factory=dict)
    co_peaks: tuple[tuple[int, tuple[str, ...]], ...] = ()


# ---------- analyser ----------

def analyze(
    events: list[dict[str, Any]],
    *,
    source_path: str = "",
    source_paths: list[str] | None = None,
    since: timedelta | None = None,
) -> Report:
    """Turn a list of parsed events into a Report.

    ``source_path`` is the legacy single-file argument (preserved
    for callers that pass one file). ``source_paths`` is the
    multi-file form — when set, the renderer treats the run as a
    cross-session analysis and emits the additional aggregation
    blocks. ``since`` flags a `--since DURATION` filter the CLI
    applied before calling us.
    """
    counts: dict[str, int] = {}
    associations: list[tuple[str | None, str | None]] = []
    band_switches = 0
    inter_ap_roams = 0
    disassociates = 0

    stir_modes: dict[str, int] = {}
    stir_confidences: dict[str, int] = {}
    stir_locations: dict[str, int] = {}
    stir_sigmas: list[float] = []

    latency_by_target: dict[str, int] = {}
    latency_max_rtt: float | None = None

    loss_max_pct: float | None = None
    loss_count = 0

    network_changes: list[tuple[str | None, str | None]] = []
    distinct_router_ips: set[str] = set()

    timestamps: list[datetime] = []

    # session_meta accumulation. Across a multi-file glob each input
    # contributes one session_meta line; we track the scenes observed
    # and the most-specific source per scene (cli > env > default).
    scenes_observed: list[str] = []
    scene_sources_map: dict[str, str] = {}
    _SOURCE_RANK = {"cli": 2, "env": 1, "default": 0}
    # Distinct counts from per-event BLE / WiFi observations — fed
    # into the LLM scene-context paragraph.
    distinct_bssids: set[str] = set()
    distinct_ble_identifiers: set[str] = set()

    for ev in events:
        kind = ev.get("type")
        counts[kind] = counts.get(kind, 0) + 1
        ts = _parse_ts(ev.get("ts", ""))
        if ts is not None:
            timestamps.append(ts)

        if kind == "link_state":
            state = ev.get("state")
            if state == "associated":
                associations.append((ev.get("ssid"), ev.get("bssid")))
            elif state == "disassociated":
                disassociates += 1
        elif kind == "roam":
            kind_field = ev.get("kind")
            if kind_field == "band_switch":
                band_switches += 1
            else:
                inter_ap_roams += 1
        elif kind == "rf_stir":
            mode = ev.get("mode") or "unknown"
            stir_modes[mode] = stir_modes.get(mode, 0) + 1
            conf = ev.get("confidence") or "unknown"
            stir_confidences[conf] = stir_confidences.get(conf, 0) + 1
            loc = ev.get("location") or "unknown"
            stir_locations[loc] = stir_locations.get(loc, 0) + 1
            mag = ev.get("magnitude_db")
            if isinstance(mag, (int, float)):
                stir_sigmas.append(float(mag))
        elif kind == "latency_spike":
            target = ev.get("target") or "unknown"
            latency_by_target[target] = latency_by_target.get(target, 0) + 1
            rtt = ev.get("rtt_ms")
            if isinstance(rtt, (int, float)):
                latency_max_rtt = (
                    rtt if latency_max_rtt is None
                    else max(latency_max_rtt, rtt)
                )
        elif kind == "loss_burst":
            loss_count += 1
            pct = ev.get("loss_pct")
            if isinstance(pct, (int, float)):
                loss_max_pct = (
                    pct if loss_max_pct is None else max(loss_max_pct, pct)
                )
            ip = ev.get("target_ip")
            if isinstance(ip, str):
                distinct_router_ips.add(ip)
        elif kind == "network_change":
            network_changes.append((
                ev.get("previous_router_ip"),
                ev.get("new_router_ip"),
            ))
        elif kind == "session_meta":
            scene = ev.get("scene")
            if isinstance(scene, str) and scene:
                scenes_observed.append(scene)
                src = ev.get("scene_source") or "default"
                if scene not in scene_sources_map or (
                    _SOURCE_RANK.get(src, 0)
                    > _SOURCE_RANK.get(scene_sources_map[scene], 0)
                ):
                    scene_sources_map[scene] = src
        if kind == "latency_spike":
            ip = ev.get("target_ip")
            if isinstance(ip, str) and ev.get("target") == "router":
                distinct_router_ips.add(ip)
        # Track distinct identifiers across all event types so the
        # LLM scene-context paragraph can quote concrete numbers.
        bssid = ev.get("bssid")
        if isinstance(bssid, str) and bssid:
            distinct_bssids.add(bssid.lower())
        ble_id = ev.get("identifier")
        if isinstance(ble_id, str) and ble_id and kind in (
            "ble_device_seen", "ble_device_left",
        ):
            distinct_ble_identifiers.add(ble_id)

    # Cross-session aggregations only fire when the caller passed
    # multiple source paths OR a --since filter — i.e. they signal
    # "this is a long-timeline run, not a per-session inspection".
    paths_t = tuple(source_paths) if source_paths else (
        (source_path,) if source_path else ()
    )
    # A long single log is a long-timeline run too — enable temporal
    # analysis on span alone, not only on multi-file / --since. (The
    # user's 13 h overnight log otherwise got no temporal output.)
    span = (
        (max(timestamps) - min(timestamps)) if timestamps else timedelta(0)
    )
    enable_cross_session = (
        (len(paths_t) > 1) or (since is not None) or (span >= _LONG_SPAN)
    )
    if enable_cross_session:
        hour_buckets = aggregate_hour_of_day(events)
        dxh = aggregate_day_of_week_x_hour(events)
        per_net = aggregate_per_network(events)
        daily = aggregate_daily_trend(events)
        contributors = aggregate_top_contributors(events)
        dwell = aggregate_ble_dwell(events)
        population = aggregate_ble_population(events)
        rhythms = {
            cat: rh
            for cat in ("ble_device_seen", "rf_stir", "loss_burst",
                        "latency_spike", "roam")
            if (rh := aggregate_hourly_rhythm(hour_buckets, cat)) is not None
        }
        co_peaks = aggregate_co_peaks(rhythms)
    else:
        hour_buckets = {}
        dxh = ()
        per_net = ()
        daily = ()
        contributors = None
        dwell = None
        population = None
        rhythms = {}
        co_peaks = ()

    report = Report(
        path=source_path or (paths_t[0] if paths_t else ""),
        span_start=min(timestamps) if timestamps else None,
        span_end=max(timestamps) if timestamps else None,
        total_events=len(events),
        counts_by_type=counts,
        associations=associations,
        roams=band_switches + inter_ap_roams,
        band_switches=band_switches,
        inter_ap_roams=inter_ap_roams,
        disassociates=disassociates,
        stir_count=counts.get("rf_stir", 0),
        stir_modes=stir_modes,
        stir_confidences=stir_confidences,
        stir_locations=stir_locations,
        stir_sigma_min=min(stir_sigmas) if stir_sigmas else None,
        stir_sigma_max=max(stir_sigmas) if stir_sigmas else None,
        stir_sigma_p50=(
            statistics.median(stir_sigmas) if stir_sigmas else None
        ),
        latency_spike_count=counts.get("latency_spike", 0),
        latency_spike_by_target=latency_by_target,
        latency_spike_max_rtt=latency_max_rtt,
        loss_burst_count=loss_count,
        loss_burst_max_pct=loss_max_pct,
        network_changes=network_changes,
        distinct_router_ips=tuple(sorted(distinct_router_ips)),
        source_paths=paths_t,
        since=since,
        hour_of_day=hour_buckets,
        day_of_week_x_hour=dxh,
        per_network=per_net,
        daily_trend=daily,
        top_contributors=contributors,
        scenes=tuple(scenes_observed),
        scene_sources=scene_sources_map,
        observed_bssid_count=len(distinct_bssids),
        observed_ble_identifier_count=len(distinct_ble_identifiers),
        ble_dwell=dwell,
        ble_population=population,
        hourly_rhythms=rhythms,
        co_peaks=co_peaks,
    )

    insights = list(_run_heuristics(report, events))
    return replace(report, insights=insights)


# ---------- since-filter parsing ----------

_SINCE_RE = re.compile(r"^(\d+)([smhd])$")


def parse_since(value: str) -> timedelta:
    """Parse `<int><unit>` (`30d` / `24h` / `90m` / `60s`) → timedelta.

    Raises ValueError with a clear message when the input doesn't
    match the supported shape.
    """
    m = _SINCE_RE.match(value.strip())
    if not m:
        raise ValueError(
            f"unparseable duration {value!r}; expected forms like "
            "30d / 7d / 24h / 90m / 60s"
        )
    n = int(m.group(1))
    unit = m.group(2)
    return timedelta(seconds=n * {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit])


def filter_since(
    events: list[dict[str, Any]],
    since: timedelta,
    *,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Return only events whose timestamp is within `since` of `now`.

    Naive in design: walks the list once. The CLI already sorts by
    timestamp before calling us so the filtered output stays in
    order. `now` is exposed for tests; production callers omit it.
    """
    cutoff = (now or datetime.now(timezone.utc)) - since
    out = []
    for ev in events:
        ts = _parse_ts(ev.get("ts", ""))
        if ts is None or ts >= cutoff:
            out.append(ev)
    return out


# ---------- cross-session aggregators ----------

# Event-type families surfaced as separate daily-trend sparklines.
_FAMILY_WIFI = {"roam", "rf_stir"}
_FAMILY_LINK = {"latency_spike", "loss_burst", "link_state"}
_FAMILY_BLE = {"ble_device_seen", "ble_device_left"}
_FAMILY_BONJOUR = {"bonjour_service_seen", "bonjour_service_left"}
_FAMILY_LAN = {"lan_host_seen", "lan_host_left", "lan_host_dhcp_rotation"}

# Public so tests can iterate in stable order.
EVENT_FAMILIES = (
    ("wifi", _FAMILY_WIFI),
    ("link", _FAMILY_LINK),
    ("ble", _FAMILY_BLE),
    ("bonjour", _FAMILY_BONJOUR),
    ("lan", _FAMILY_LAN),
)


def aggregate_hour_of_day(
    events: list[dict[str, Any]],
) -> dict[int, dict[str, int]]:
    """Return ``{hour: {event_type: count}}`` for all 24 hours.

    Hours with no events get an empty Counter; consumers can decide
    whether to display them.
    """
    out: dict[int, dict[str, int]] = {h: {} for h in range(24)}
    for ev in events:
        ts = _parse_ts(ev.get("ts", ""))
        if ts is None:
            continue
        # Use the timestamp's OWN offset (already encoded in the
        # JSONL `ts` string) — NOT `.astimezone()`, which would
        # convert to whatever local TZ the machine running
        # `diting analyze` is in. We want "what hour of the user's
        # day did this happen", not "what hour of the analyzer's
        # day". CI runners (macOS / Linux) are typically UTC, so
        # astimezone() would smear cross-TZ data on CI vs locally.
        hour = ts.hour
        typ = ev.get("type") or "unknown"
        bucket = out[hour]
        bucket[typ] = bucket.get(typ, 0) + 1
    return out


def aggregate_day_of_week_x_hour(
    events: list[dict[str, Any]],
) -> tuple[tuple[int, ...], ...]:
    """Return a 7×24 grid of total event counts.

    Outer index: weekday (Mon=0). Inner: hour 0-23. Cell value:
    total events that landed in (weekday, hour). Returned as nested
    tuples so it's hashable / frozen-friendly.

    Uses the timestamp's OWN offset (no `.astimezone()`) — see the
    same note in `aggregate_hour_of_day`.
    """
    grid: list[list[int]] = [[0] * 24 for _ in range(7)]
    for ev in events:
        ts = _parse_ts(ev.get("ts", ""))
        if ts is None:
            continue
        grid[ts.weekday()][ts.hour] += 1
    return tuple(tuple(row) for row in grid)


def aggregate_per_network(
    events: list[dict[str, Any]],
) -> tuple[NetworkAggregate, ...]:
    """Group events by associated BSSID via the connection_update walk.

    Events without preceding context land in the synthetic
    ``(unknown network)`` bucket.
    """
    # First pass: build a list of (ts, bssid, ssid) from
    # connection_update + link_state(associated) events, sorted.
    ctx: list[tuple[datetime, str | None, str | None]] = []
    for ev in events:
        ts = _parse_ts(ev.get("ts", ""))
        if ts is None:
            continue
        typ = ev.get("type")
        if typ == "connection_update":
            state = ev.get("state")
            if state == "associated":
                ctx.append((ts, ev.get("bssid"), ev.get("ssid")))
            elif state == "disassociated":
                ctx.append((ts, None, None))
        elif typ == "link_state":
            state = ev.get("state")
            if state == "associated":
                ctx.append((ts, ev.get("bssid"), ev.get("ssid")))
            elif state == "disassociated":
                ctx.append((ts, None, None))
    ctx.sort(key=lambda t: t[0])

    def _ctx_for(ts: datetime) -> tuple[str | None, str | None]:
        """Find the most-recent associated (bssid, ssid) at or before ts.

        Linear scan from the right — the lists are typically <1000.
        """
        for c_ts, bssid, ssid in reversed(ctx):
            if c_ts <= ts:
                return bssid, ssid
        return None, None

    buckets: dict[tuple[str | None, str | None], dict[str, int]] = {}
    totals: dict[tuple[str | None, str | None], int] = {}
    for ev in events:
        ts = _parse_ts(ev.get("ts", ""))
        if ts is None:
            continue
        bssid, ssid = _ctx_for(ts)
        # Try to read BSSID directly from the event when present —
        # roam / link_state carry it and we prefer that to ambient
        # context.
        ev_bssid = ev.get("new_bssid") or ev.get("bssid")
        if ev_bssid:
            bssid = ev_bssid
        key = (bssid, ssid)
        bucket = buckets.setdefault(key, {})
        typ = ev.get("type") or "unknown"
        bucket[typ] = bucket.get(typ, 0) + 1
        totals[key] = totals.get(key, 0) + 1

    out: list[NetworkAggregate] = []
    for key, total in totals.items():
        bssid, ssid = key
        if bssid is None and ssid is None:
            label = "(unknown network)"
        elif ssid:
            label = f"{ssid}" + (f" ({bssid})" if bssid else "")
        else:
            label = bssid or "(unknown network)"
        out.append(NetworkAggregate(
            network_label=label,
            bssid=bssid,
            total=total,
            counts_by_type=buckets[key],
            ssid=ssid,
        ))
    out.sort(key=lambda n: n.total, reverse=True)
    return tuple(out)


def aggregate_daily_trend(
    events: list[dict[str, Any]],
) -> tuple[DailyCount, ...]:
    """Per-day total counts + 7-day rolling average."""
    daily: dict[str, int] = {}
    for ev in events:
        ts = _parse_ts(ev.get("ts", ""))
        if ts is None:
            continue
        # Bucket by the date encoded in the event's own offset, NOT
        # by the analyzer-machine's local TZ — see the same note in
        # `aggregate_hour_of_day`.
        d = ts.date().isoformat()
        daily[d] = daily.get(d, 0) + 1

    if not daily:
        return ()

    # Fill date gaps so the rolling avg is continuous across
    # zero-event days.
    first = min(daily.keys())
    last = max(daily.keys())
    from datetime import date as _date
    cur = _date.fromisoformat(first)
    end = _date.fromisoformat(last)
    one_day = timedelta(days=1)
    series: list[tuple[str, int]] = []
    while cur <= end:
        key = cur.isoformat()
        series.append((key, daily.get(key, 0)))
        cur = cur + one_day

    out: list[DailyCount] = []
    window: list[int] = []
    for d, total in series:
        window.append(total)
        if len(window) > 7:
            window.pop(0)
        avg = sum(window) / len(window)
        out.append(DailyCount(date=d, total=total, rolling_7d_avg=avg))
    return tuple(out)


def aggregate_top_contributors(
    events: list[dict[str, Any]],
    *,
    n: int = 10,
) -> TopContributors:
    """Three sub-rankings: BSSIDs (roam+stir), BLE (seen), LAN (dhcp_rotation)."""
    bssid_roam: dict[str, int] = {}
    bssid_stir: dict[str, int] = {}
    ble_seen: dict[str, dict[str, Any]] = {}
    lan_rotate: dict[str, dict[str, Any]] = {}

    for ev in events:
        typ = ev.get("type")
        if typ == "roam":
            b = ev.get("new_bssid")
            if b:
                bssid_roam[b] = bssid_roam.get(b, 0) + 1
        elif typ == "rf_stir":
            b = ev.get("bssid")
            if b:
                bssid_stir[b] = bssid_stir.get(b, 0) + 1
        elif typ == "ble_device_seen":
            # Key on the STABLE familiarity identity, not the rotating BLE
            # `identifier` — otherwise one physical device seen under many
            # rotated addresses ranks as many "1 seen" rows (useless).
            key = _ble_stable_key(ev)
            if key:
                entry = ble_seen.setdefault(key, {"count": 0})
                entry["count"] += 1
                entry["name"] = entry.get("name") or ev.get("name")
                entry["vendor"] = entry.get("vendor") or ev.get("vendor")
        elif typ == "lan_host_dhcp_rotation":
            mac = ev.get("mac")
            if mac:
                entry = lan_rotate.setdefault(mac, {"count": 0})
                entry["count"] += 1
                entry["vendor"] = entry.get("vendor") or ev.get("vendor")
                entry["bonjour_name"] = (
                    entry.get("bonjour_name") or ev.get("bonjour_name")
                )
                entry["hostname"] = entry.get("hostname") or ev.get("hostname")
                entry["ip"] = entry.get("ip") or ev.get("new_ip") or ev.get("ip")

    all_bssids = set(bssid_roam) | set(bssid_stir)
    bssids = sorted(
        all_bssids,
        key=lambda b: bssid_roam.get(b, 0) + bssid_stir.get(b, 0),
        reverse=True,
    )[:n]
    top_bssids = tuple(
        TopBSSID(
            bssid=b,
            label=b,
            roam_count=bssid_roam.get(b, 0),
            stir_count=bssid_stir.get(b, 0),
        )
        for b in bssids
    )

    ble_sorted = sorted(
        ble_seen.items(), key=lambda kv: kv[1]["count"], reverse=True,
    )[:n]
    top_ble = tuple(
        TopBLE(
            identifier=key,
            label=" · ".join(
                p for p in (entry.get("vendor"), entry.get("name"))
                if p
            ) or key,
            seen_count=entry["count"],
        )
        for key, entry in ble_sorted
    )

    lan_sorted = sorted(
        lan_rotate.items(), key=lambda kv: kv[1]["count"], reverse=True,
    )[:n]
    top_lan = tuple(
        TopLAN(
            mac=mac,
            label=" · ".join(
                p for p in (
                    entry.get("vendor"),
                    entry.get("bonjour_name") or entry.get("hostname"),
                    entry.get("ip"),
                ) if p
            ) or mac,
            rotation_count=entry["count"],
        )
        for mac, entry in lan_sorted
    )

    return TopContributors(
        bssids=top_bssids,
        ble_identifiers=top_ble,
        lan_hosts=top_lan,
    )


# ---------- heuristics ----------

def _run_heuristics(
    r: Report, events: list[dict[str, Any]],
) -> list[Insight]:
    """Generate a list of insights from the aggregated report.

    Each heuristic is small and self-contained so adding new
    rules later is a one-function change. Order matters only
    for presentation — the renderer prints them in declared
    order, so put the most important / most actionable rules
    early.
    """
    out: list[Insight] = []

    # -- 1. Empty file: no events at all
    if r.total_events == 0:
        out.append(Insight(
            severity="warn",
            title=t("Empty log"),
            detail=t(
                "No JSONL events parsed. Is diting still writing? "
                "Check the path and that the producer is running."
            ),
            todo=t("Re-run with --log on a session that produces events."),
        ))
        return out

    # -- 2. Mixed-timezone heuristic (the timestamp bug we just fixed)
    #     If two consecutive timestamps differ by an integer number
    #     of hours within a few seconds, the producer probably mixed
    #     local + UTC labelling. Surface as a warning since the
    #     analysis below treats timestamps at face value.
    sorted_ts = sorted(
        ts for ts in (
            _parse_ts(ev.get("ts", "")) for ev in events
        ) if ts is not None
    )
    suspicious_jump = False
    for i in range(1, len(sorted_ts)):
        gap = (sorted_ts[i] - sorted_ts[i - 1]).total_seconds()
        if 3500 <= (gap % 3600) <= 3600 - 100 and gap >= 3500:
            # Gap of ~Nh ± a few seconds. Likely tz mislabel.
            suspicious_jump = True
            break
        # Specifically: gap is N hours within 5 s.
        for hours in range(1, 24):
            if abs(gap - hours * 3600) < 5:
                suspicious_jump = True
                break
        if suspicious_jump:
            break
    if suspicious_jump:
        out.append(Insight(
            severity="warn",
            title=t("Timezone mismatch in log"),
            detail=t(
                "Adjacent events span an exact-hour gap, which usually "
                "means producer wrote some timestamps as local time "
                "labelled UTC. Versions before the timestamp fix had "
                "this bug."
            ),
            todo=t(
                "Update diting and re-record. Existing data is still "
                "usable but cross-timezone analysis may misorder events."
            ),
        ))

    # -- 3. Single-AP environment monitoring
    co = r.stir_modes.get("co_located", 0)
    spat = r.stir_modes.get("spatial_channel", 0)
    high_conf = r.stir_confidences.get("high", 0)
    if r.stir_count >= 5 and high_conf == 0 and len(r.stir_locations) <= 1:
        out.append(Insight(
            severity="note",
            title=t("All stir events medium-confidence"),
            detail=t(
                "Every RF stir landed at medium confidence and on one "
                "AP location ({n} events). With only one co-located AP "
                "diting cannot upgrade events to high confidence — "
                "redundancy fusion needs ≥2 APs in the same room.",
                n=r.stir_count,
            ),
            todo=t(
                "If you want richer presence detection, add a second "
                "AP in the same area on a different channel. Keep your "
                "existing per-floor layout for coverage; add a near "
                "duplicate only where you want the disambiguation."
            ),
        ))

    # -- 4. Sustained stir cluster (continuous activity)
    if r.stir_count >= 3 and r.stir_sigma_p50 is not None and r.stir_sigma_p50 >= 3.0:
        out.append(Insight(
            severity="info",
            title=t("Sustained RF activity"),
            detail=t(
                "{n} stir events with median σ {sigma} dB (range "
                "{lo}–{hi}). Long runs at a similar σ suggest "
                "ongoing motion rather than isolated spikes.",
                n=r.stir_count,
                sigma=f"{r.stir_sigma_p50:.1f}",
                lo=f"{r.stir_sigma_min:.1f}" if r.stir_sigma_min else "?",
                hi=f"{r.stir_sigma_max:.1f}" if r.stir_sigma_max else "?",
            ),
        ))

    # -- 5. Latency spikes with no loss
    if r.latency_spike_count >= 1 and r.loss_burst_count == 0:
        out.append(Insight(
            severity="note",
            title=t("Latency spikes without loss"),
            detail=t(
                "{n} latency spikes fired with zero loss bursts. "
                "Single RTT spikes (router/CPU busy, transient queue, "
                "scan overlap) are different from sustained packet "
                "loss; this set looks like jitter, not link failure.",
                n=r.latency_spike_count,
            ),
            todo=t(
                "If spikes correlate with stir bursts, the AP may be "
                "doing background scans during high airtime. Disable "
                "auto-channel or lower BLE scan rate on the AP if "
                "available."
            ),
        ))

    # -- 6. Loss bursts present
    if r.loss_burst_count >= 1:
        scaled = _scaled_loss_pct(r)
        out.append(Insight(
            severity="warn",
            title=t("Real packet loss observed"),
            detail=t(
                "{n} loss-burst events (peak {pct}%). This is sustained "
                "loss, not single-packet jitter — investigate before "
                "assuming a transient.",
                n=r.loss_burst_count,
                pct=f"{scaled:.0f}" if scaled is not None else "?",
            ),
            todo=t(
                "Check the gateway probe target separately from WAN. "
                "Gateway loss → LAN issue (cable, AP overload). WAN "
                "loss only → ISP / upstream issue."
            ),
        ))

    # -- 6b. Network change observed
    if r.network_changes:
        moves = ", ".join(
            f"{prev or '?'} → {new or '?'}"
            for prev, new in r.network_changes
        )
        out.append(Insight(
            severity="info",
            title=t("Network change(s) detected"),
            detail=t(
                "{n} gateway-IP transition(s) during this session: "
                "{moves}. Treat per-network statistics separately — "
                "stir / latency / loss aggregates pre and post a "
                "network change describe physically different APs.",
                n=len(r.network_changes), moves=moves,
            ),
        ))

    # -- 6c. Stale latency target after roam (the user's bug)
    #     Pre-fix bug: LatencyPoller did not refresh on router_ip
    #     change, so it kept pinging the previous network's
    #     gateway. The smoking gun in the log is "all loss_burst
    #     events target the same router IP" combined with "no
    #     network_change events" combined with "gateway IPs
    #     across roam events are inconsistent". When we DO have
    #     network_change events the heuristic stays quiet — that
    #     means the post-fix code refreshed the poller correctly.
    if (
        r.loss_burst_count >= 5
        and not r.network_changes
        and len(r.distinct_router_ips) <= 1
        and r.roams >= 1
    ):
        ip = r.distinct_router_ips[0] if r.distinct_router_ips else "?"
        out.append(Insight(
            severity="warn",
            title=t("Loss bursts may be probing a stale gateway"),
            detail=t(
                "All {n} loss-burst events target {ip}, even though "
                "the session crossed {roams} roam(s). Pre-0.7.0 "
                "versions had a bug where LatencyPoller did not "
                "refresh after a network change, so the probe kept "
                "pinging the previous network's gateway. The flood "
                "of loss bursts is then a measurement artifact, not "
                "real link degradation.",
                n=r.loss_burst_count, ip=ip, roams=r.roams,
            ),
            todo=t(
                "Update diting and re-record. Post-fix the "
                "LatencyPoller rebuilds on every gateway-IP change "
                "and emits an explicit network_change event."
            ),
        ))

    # -- 7. Frequent disassociates (sticky AP / weak signal cycling)
    if r.disassociates >= 3:
        out.append(Insight(
            severity="warn",
            title=t("Repeated disassociations"),
            detail=t(
                "{n} disassociate events. Repeated reconnects within "
                "one session usually mean weak signal at the edge of "
                "an AP's range, mixed PHY/MCS issues, or driver hand-"
                "off problems.",
                n=r.disassociates,
            ),
            todo=t(
                "Look at your roam events to see if the Mac is failing "
                "to find a target, then either move the second AP "
                "closer or enable 802.11k/v on the existing one."
            ),
        ))

    # -- 8. Roam-heavy session (potential sticky AP)
    if r.roams >= 5:
        ratio = r.band_switches / max(1, r.roams)
        if ratio > 0.7:
            out.append(Insight(
                severity="info",
                title=t("Mostly band-switch roams"),
                detail=t(
                    "{n} roams of which {pct}% were band switches "
                    "(2.4 ↔ 5 GHz on the same AP). Common sign of an "
                    "AP doing aggressive band-steering; no action "
                    "needed unless the Mac picks 2.4 too often.",
                    n=r.roams,
                    pct=int(ratio * 100),
                ),
            ))
        else:
            out.append(Insight(
                severity="note",
                title=t("Frequent inter-AP roams"),
                detail=t(
                    "{n} roams, mostly across different APs. Either you "
                    "are walking around the building, or APs nearby "
                    "have similar enough RSSI that the Mac keeps "
                    "switching between them.",
                    n=r.roams,
                ),
                todo=t(
                    "If you weren't moving, check whether two APs "
                    "advertise the same SSID with overlapping coverage "
                    "and similar TX power. Consider lowering one or "
                    "splitting SSIDs."
                ),
            ))

    # -- T (temporal / population, enrich-temporal-analysis). These only
    #    have inputs on a long-timeline run (the aggregates are None /
    #    empty otherwise), so each guards on its own aggregate.
    out.extend(_temporal_heuristics(r))

    # -- 9. Short session warning
    if (
        r.span_start is not None and r.span_end is not None
        and (r.span_end - r.span_start) < timedelta(minutes=10)
    ):
        out.append(Insight(
            severity="info",
            title=t("Short observation window"),
            detail=t(
                "Log spans under 10 minutes. Heuristics that need "
                "trends (RSSI baselines, traffic patterns) will be "
                "noisy on this little data."
            ),
            todo=t(
                "Re-run with --log over a longer session "
                "(an evening, a workday) for richer signal."
            ),
        ))

    return out


def _category_label(category: str) -> str:
    """Short human label for an event category in temporal copy."""
    return {
        "ble_device_seen": t("BLE arrivals"),
        "rf_stir": t("RF stir"),
        "loss_burst": t("packet loss"),
        "latency_spike": t("latency spikes"),
        "roam": t("roams"),
    }.get(category, category)


def _hour_band(hours: range) -> str:
    """`range(0, 6)` → `00:00–06:00`."""
    return f"{hours.start:02d}:00–{hours.stop:02d}:00"


def _temporal_heuristics(r: "Report") -> list[Insight]:
    """Temporal / population / coincidence insights for a long-timeline
    run. Each guards on its own aggregate, so a short log (aggregates
    None / empty) yields nothing."""
    out: list[Insight] = []

    # -- T1. BLE arrival rhythm
    rh = r.hourly_rhythms.get("ble_device_seen")
    if rh is not None and rh.total >= 50:
        if rh.concentrated:
            shape = t(
                "The busiest {n} hours hold {pct}% of arrivals — a "
                "concentrated daily cycle (people arriving / leaving), "
                "not a flat background.",
                n=_CONCENTRATION_HOURS, pct=int(rh.top_hours_share * 100),
            )
        else:
            shape = t(
                "Arrivals are spread fairly evenly across the day — a "
                "steady ambient churn rather than a clear arrival cycle."
            )
        out.append(Insight(
            severity="info",
            title=t("BLE arrival rhythm"),
            detail=t(
                "BLE arrivals peak around {peak}:00 ({pk}/h) and bottom "
                "out around {quiet}:00 ({qt}/h). {shape}",
                peak=rh.peak_hour, pk=rh.peak_count,
                quiet=rh.quiet_hour, qt=rh.quiet_count, shape=shape,
            ),
            todo=t(
                "Treat the peak hours as your occupancy window; capture "
                "during one to see what is actually arriving."
            ),
        ))

    # -- T2. Dwell / foot-traffic read
    dw = r.ble_dwell
    if dw is not None and dw.n >= 30:
        frac = dw.transient / dw.n
        if frac >= 0.5:
            read = t(
                "{pct}% of sightings were brief — high transient "
                "foot-traffic (devices passing through), not a stable "
                "resident population.",
                pct=int(frac * 100),
            )
        else:
            read = t(
                "Most devices lingered — a stable resident population "
                "rather than pass-through traffic."
            )
        out.append(Insight(
            severity="info",
            title=t("BLE dwell — foot-traffic vs residents"),
            detail=t(
                "{n} departures: median dwell {p50}, 90th-pct {p90}. "
                "{trans} brief (<2 min), {ling} lingering, {res} "
                "resident (>30 min). {read}",
                n=dw.n, p50=_format_duration(dw.p50_s),
                p90=_format_duration(dw.p90_s), trans=dw.transient,
                ling=dw.lingering, res=dw.resident, read=read,
            ),
        ))

    # -- T3. Population — fixtures vs pass-bys
    pop = r.ble_population
    if pop is not None and pop.distinct_devices >= 5:
        unk = (
            t(
                " {u} sightings had no stable identity and are excluded "
                "from the count.",
                u=pop.unkeyable_sightings,
            )
            if pop.unkeyable_sightings else ""
        )
        out.append(Insight(
            severity="info",
            title=t("Device population"),
            detail=t(
                "{n} distinct physical devices over the log (counted by "
                "stable identity, not the rotating BLE address). {res} "
                "were present across most of the span (fixtures / "
                "regulars); {passers} appeared in a single hour "
                "(pass-bys).{unk}",
                n=pop.distinct_devices, res=pop.residents,
                passers=pop.passersby, unk=unk,
            ),
        ))

    # -- T4. Off-hours activity (scene-aware)
    scene = r.scenes[0] if len(set(r.scenes)) == 1 else None
    quiet_hours = _EXPECTED_QUIET_HOURS.get(scene) if scene else None
    if quiet_hours is not None and r.hour_of_day:
        total = sum(sum(b.values()) for b in r.hour_of_day.values())
        quiet_total = sum(
            sum(b.values())
            for h, b in r.hour_of_day.items() if h in quiet_hours
        )
        share = (quiet_total / total) if total else 0.0
        if share >= 0.15:
            out.append(Insight(
                severity="note",
                title=t("Activity during expected-quiet hours"),
                detail=t(
                    "{pct}% of all events fell in the `{scene}` scene's "
                    "expected-quiet window ({band}). Off-baseline timing "
                    "is more noteworthy than the same activity in-hours.",
                    pct=int(share * 100), scene=scene,
                    band=_hour_band(quiet_hours),
                ),
                todo=t(
                    "Skim the overnight events: a device that is active "
                    "when the space should be empty is worth identifying."
                ),
            ))

    # -- T5. Cross-signal coincidence — a rare signal concentrating in the
    #    busy arrival hours is a hypothesis worth a targeted re-capture.
    ble_rh = r.hourly_rhythms.get("ble_device_seen")
    if ble_rh is not None and r.hour_of_day:
        ble_counts = {
            h: r.hour_of_day.get(h, {}).get("ble_device_seen", 0)
            for h in range(24)
        }
        active = [n for n in ble_counts.values() if n > 0]
        median = statistics.median(active) if active else 0
        busy = {h for h, n in ble_counts.items() if n > median}
        for cat in ("loss_burst", "latency_spike", "rf_stir"):
            crh = r.hourly_rhythms.get(cat)
            if crh is None or crh.total < 3:
                continue
            in_busy = sum(
                r.hour_of_day.get(h, {}).get(cat, 0) for h in busy
            )
            if in_busy / crh.total < 0.6:
                continue
            hours = sorted(
                h for h in range(24)
                if r.hour_of_day.get(h, {}).get(cat, 0) > 0 and h in busy
            )
            hours_str = ", ".join(f"{h:02d}:00" for h in hours)
            out.append(Insight(
                severity="note",
                title=t("Signals coinciding in time"),
                detail=t(
                    "{label} concentrated in the busy BLE-arrival hours "
                    "({hours}) — {frac}% of it fell when arrivals were "
                    "above the daily median. A shared timing is a "
                    "hypothesis, not a cause: e.g. loss / latency rising "
                    "as devices arrive points to airtime contention "
                    "during the busy window.",
                    label=_category_label(cat), hours=hours_str,
                    frac=int(in_busy / crh.total * 100),
                ),
                todo=t(
                    "Capture with --log during {hours} and re-analyze to "
                    "test whether the signals are actually linked.",
                    hours=hours_str,
                ),
            ))

    return out


# ---------- rendering ----------

def _format_duration(seconds: float) -> str:
    """Pick the right unit for a duration so a 1-second span does
    not read as '1 min'. Three shapes: seconds-only when under a
    minute, minutes when under an hour, hours+minutes beyond.
    """
    secs = int(seconds)
    if secs < 60:
        return t("{n}s", n=secs)
    minutes = secs // 60
    if minutes < 60:
        return t("{n} min", n=minutes)
    hours = minutes // 60
    rem = minutes % 60
    return t("{h}h {m}m", h=hours, m=rem)


def _scaled_loss_pct(report: Report) -> float | None:
    """Best-effort percent value (0..100) for the report's max
    loss_burst.

    Logs produced before the aggregate-window fix (where the
    rolling-window cutoff was a no-op for samples that had been
    in history > window seconds) carried loss_pct as a
    fraction-of-session 0..1 instead of the documented 0..100.
    Detect that shape via "max < 1.0 AND we have any loss
    bursts" and re-scale so the rendered "peak X%" is honest.
    Newer logs (post-fix) already carry 0..100 percentages and
    pass through unchanged.
    """
    pct = report.loss_burst_max_pct
    if pct is None or report.loss_burst_count == 0:
        return None
    if 0 < pct < 1.0:
        return pct * 100.0
    return pct


# ---------- LLM bridge (Track B): Anonymizer + Markdown renderer + prompt ----------

_RFC1918_PREFIXES = ("10.", "192.168.")
_RFC1918_172 = tuple(f"172.{n}." for n in range(16, 32))


def _is_rfc1918(ip: str) -> bool:
    """True iff `ip` is in a private RFC1918 range (LAN address)."""
    if not isinstance(ip, str):
        return False
    if ip.startswith(_RFC1918_PREFIXES):
        return True
    if ip.startswith(_RFC1918_172):
        return True
    return False


class Anonymizer:
    """Assigns stable first-seen handles to privacy-sensitive identifiers.

    Same value → same handle across the entire report. Different
    kinds use different prefixes so handles can't accidentally
    collide (`SSID_1` is a different namespace from `AP_1`).

    Handles are deterministic given fixed event ordering — a
    re-run on the same input produces the same handles, which
    lets the user store the mapping for cross-reference.

    Vendor names, service categories, event-type names, magnitudes,
    timestamps, and aggregation counts are NOT anonymized — they
    flow through callers verbatim.
    """

    _PREFIXES = {
        "ssid": "SSID",
        "bssid": "AP",
        "ip": "IP",
        "host": "HOST",
        "ble": "BLE",
        "mac": "MAC",
    }

    def __init__(self) -> None:
        self._maps: dict[str, dict[str, str]] = {k: {} for k in self._PREFIXES}
        self._counters: dict[str, int] = {k: 0 for k in self._PREFIXES}

    def map(self, kind: str, value: str | None) -> str | None:
        """Return the stable handle for `value` of the given `kind`.

        `None` returns `None`. Empty string returns empty string.
        IP `kind` skips public IPs (returns them unchanged) so
        `8.8.8.8` / `1.1.1.1` survive verbatim in the report.
        """
        if value is None or value == "":
            return value
        if kind == "ip" and not _is_rfc1918(value):
            return value
        if kind not in self._maps:
            return value
        bucket = self._maps[kind]
        if value in bucket:
            return bucket[value]
        self._counters[kind] += 1
        handle = f"{self._PREFIXES[kind]}_{self._counters[kind]}"
        bucket[value] = handle
        return handle

    def mapping(self) -> list[tuple[str, str]]:
        """Flat ordered list of `(handle, original)` pairs for the
        terminal printout. Order: handles by kind (SSID first, then
        AP, IP, HOST, BLE, MAC), within each kind by first-seen
        index (1, 2, 3, ...)."""
        out: list[tuple[str, str]] = []
        for kind in self._PREFIXES:
            for original, handle in self._maps[kind].items():
                out.append((handle, original))
        # Stable sort by (prefix, numeric-index).
        def _key(pair: tuple[str, str]) -> tuple[str, int]:
            handle, _ = pair
            prefix, _, idx = handle.partition("_")
            try:
                return (prefix, int(idx))
            except ValueError:
                return (prefix, 0)
        out.sort(key=_key)
        return out


def render_markdown(
    report: Report,
    *,
    anonymizer: "Anonymizer | None" = None,
) -> str:
    """Markdown rendition of the report, intended for LLM consumption.

    Mirrors the terminal `render()` content but uses Markdown
    headings, fenced code blocks for ASCII charts, and tables for
    ranked data so an LLM can navigate sections cleanly.

    When `anonymizer` is non-None, identifying fields are replaced
    with stable handles before being written to the Markdown
    output. The handle-↔-original mapping does NOT appear in the
    Markdown — only the CLI prints it to stdout (see the
    `## Anonymization` placeholder).
    """
    a = anonymizer
    zh = i18n.get_lang() == i18n.ZH
    def ax(kind: str, value: str | None) -> str:
        if a is None or value is None:
            return value or ""
        return a.map(kind, value) or ""

    lines: list[str] = []
    lines.append("# diting 分析报告" if zh else "# diting analysis report")
    lines.append("")
    # Scene line surfaces the environment the JSONL was captured in.
    # Always rendered (single or multi-session). Pre-scene-aware
    # captures show `unknown (pre-scene-aware capture)`.
    lines.append(f"**{'场景' if zh else 'Scene'}：** {scene_summary(report)}"
                 if zh else f"**Scene:** {scene_summary(report)}")
    lines.append("")
    enable_cross = (
        len(report.source_paths) > 1 or report.since is not None
    )
    # Cross-session BLOCKS also render for a single long log (hour_of_day
    # non-empty ⇔ the analyser's temporal gate fired).
    show_temporal_blocks = enable_cross or bool(report.hour_of_day)

    # ---- Scope
    if enable_cross:
        if report.span_start and report.span_end:
            span_days = (report.span_end - report.span_start).days
            span_str = (
                f"{report.span_start.date().isoformat()} → "
                f"{report.span_end.date().isoformat()} ({span_days} days)"
            )
        else:
            span_str = "(no events)"
        since_str = (
            _format_duration(report.since.total_seconds())
            if report.since is not None else "none"
        )
        if zh:
            lines.append(
                f"**范围：** {len(report.source_paths) or 1} 个文件 · "
                f"{span_str} · `--since {since_str}`",
            )
        else:
            lines.append(
                f"**Scope:** {len(report.source_paths) or 1} files · "
                f"{span_str} · `--since {since_str}`",
            )
        lines.append("")

    # ---- Counts
    if report.counts_by_type:
        lines.append("## 按类型统计的事件总数" if zh else "## Total events by type")
        lines.append("")
        lines.append("| 类型 | 数量 |" if zh else "| Type | Count |")
        lines.append("|---|---:|")
        for k, v in sorted(report.counts_by_type.items()):
            lines.append(f"| `{k}` | {v} |")
        lines.append(f"| **合计** | **{report.total_events}** |" if zh
                     else f"| **total** | **{report.total_events}** |")
        lines.append("")

    # ---- Connection summary
    if report.associations:
        ssid, bssid = report.associations[-1]
        lines.append("## 最近一次关联" if zh else "## Latest association")
        lines.append("")
        lines.append(
            f"- SSID: `{ax('ssid', ssid) or '?'}`"
        )
        lines.append(
            f"- BSSID: `{ax('bssid', bssid) or '?'}`"
        )
        lines.append("")

    # ---- Heuristic insights
    if report.insights:
        lines.append("## 逐会话启发式洞察" if zh else "## Per-session heuristic insights")
        lines.append("")
        for ins in report.insights:
            lines.append(f"### {ins.title}")
            lines.append("")
            lines.append(f"**严重度：** {ins.severity}" if zh else f"**Severity:** {ins.severity}")
            lines.append("")
            for line in ins.detail.splitlines() or [""]:
                lines.append(line)
            if ins.todo:
                lines.append("")
                lines.append(f"**待办：** {ins.todo}" if zh else f"**TODO:** {ins.todo}")
            lines.append("")

    # ---- Cross-session blocks
    if show_temporal_blocks and (
        report.ble_population or report.ble_dwell
        or report.hourly_rhythms
    ):
        lines.append("## 时序与人口" if zh else "## Temporal & population")
        lines.append("")
        rh = report.hourly_rhythms.get("ble_device_seen")
        if rh is not None:
            if zh:
                lines.append(
                    f"- **BLE 节律**：峰值 {rh.peak_hour:02d}:00"
                    f"（{rh.peak_count}/小时），谷值 {rh.quiet_hour:02d}:00"
                    f"（{rh.quiet_count}/小时）；最忙的 {_CONCENTRATION_HOURS} "
                    f"小时占了到达的 {int(rh.top_hours_share * 100)}%。"
                )
            else:
                lines.append(
                    f"- **BLE rhythm**: peak {rh.peak_hour:02d}:00 "
                    f"({rh.peak_count}/h), quiet {rh.quiet_hour:02d}:00 "
                    f"({rh.quiet_count}/h); busiest {_CONCENTRATION_HOURS} hours "
                    f"hold {int(rh.top_hours_share * 100)}% of arrivals."
                )
        if report.ble_population is not None:
            p = report.ble_population
            if zh:
                lines.append(
                    f"- **人口**：{p.distinct_devices} 台不同设备"
                    f"（按稳定身份，而非滚动地址）—— {p.residents} 常驻、"
                    f"{p.passersby} 过客、{p.unkeyable_sightings} 次不可定位的出现。"
                )
            else:
                lines.append(
                    f"- **Population**: {p.distinct_devices} distinct devices "
                    f"(by stable identity, not rotating address) — "
                    f"{p.residents} resident, {p.passersby} pass-by, "
                    f"{p.unkeyable_sightings} unkeyable sightings."
                )
        if report.ble_dwell is not None:
            d = report.ble_dwell
            if zh:
                lines.append(
                    f"- **停留**：p50 {_format_duration(d.p50_s)}、p90 "
                    f"{_format_duration(d.p90_s)} —— {d.transient} 短暂 / "
                    f"{d.lingering} 逗留 / {d.resident} 常驻。"
                )
            else:
                lines.append(
                    f"- **Dwell**: p50 {_format_duration(d.p50_s)}, p90 "
                    f"{_format_duration(d.p90_s)} — {d.transient} brief / "
                    f"{d.lingering} lingering / {d.resident} resident."
                )
        lines.append("")

    if show_temporal_blocks and report.hour_of_day:
        lines.append("## 按小时事件分布" if zh else "## Events by hour-of-day")
        lines.append("")
        totals = {
            h: sum(report.hour_of_day[h].values()) for h in range(24)
        }
        lines.append("| 小时 | 合计 | 最多类型 |" if zh else "| Hour | Total | Top type |")
        lines.append("|---:|---:|---|")
        for h in range(24):
            top = (
                max(report.hour_of_day[h].items(), key=lambda kv: kv[1])[0]
                if report.hour_of_day[h] else "—"
            )
            lines.append(f"| {h:02d} | {totals[h]} | `{top}` |")
        lines.append("")

    if show_temporal_blocks and report.day_of_week_x_hour:
        lines.append("## 天 × 小时 热力图（密度）" if zh else "## Day × hour heatmap (density)")
        lines.append("")
        lines.append("```text")
        max_cell = max(
            (max(row) for row in report.day_of_week_x_hour),
            default=0,
        )
        if max_cell > 0:
            names = (("周一","周二","周三","周四","周五","周六","周日") if zh
                     else ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"))
            for i, row in enumerate(report.day_of_week_x_hour):
                cells = "".join(
                    _density_char(v, max_cell) for v in row
                )
                lines.append(f"  {names[i]}  {cells}")
            lines.append("       0   6   12  18  23")
        lines.append("```")
        lines.append("")

    if show_temporal_blocks and report.per_network:
        lines.append("## 按事件量排名的网络" if zh else "## Top networks by event volume")
        lines.append("")
        lines.append("| 网络 | 事件 | 明细 |" if zh else "| Network | Events | Breakdown |")
        lines.append("|---|---:|---|")
        for n in report.per_network[:10]:
            if a is not None and n.network_label != "(unknown network)":
                # Rebuild from anonymized parts so both SSID and
                # BSSID get scrubbed, not just one.
                a_ssid = ax("ssid", n.ssid) if n.ssid else None
                a_bssid = ax("bssid", n.bssid) if n.bssid else None
                if a_ssid and a_bssid:
                    label = f"{a_ssid} ({a_bssid})"
                elif a_ssid:
                    label = a_ssid
                elif a_bssid:
                    label = a_bssid
                else:
                    label = n.network_label
            else:
                label = n.network_label
            bd = " · ".join(
                f"{k} {v}" for k, v in sorted(n.counts_by_type.items())
            )
            lines.append(f"| {label} | {n.total} | {bd} |")
        lines.append("")

    if show_temporal_blocks and report.daily_trend:
        lines.append(
            (f"## 每日趋势（{len(report.daily_trend)} 天窗口）" if zh
             else f"## Daily trend ({len(report.daily_trend)}-day window)")
        )
        lines.append("")
        lines.append("```text")
        max_total = max((d.total for d in report.daily_trend), default=0)
        spark = "".join(
            _density_char(d.total, max_total)
            for d in report.daily_trend
        )
        lines.append(f"  {'合计' if zh else 'total'}  {spark}")
        lines.append("```")
        lines.append("")
        lines.append("| 日期 | 合计 | 7 天均值 |" if zh else "| Date | Total | 7-day avg |")
        lines.append("|---|---:|---:|")
        for d in report.daily_trend:
            lines.append(
                f"| {d.date} | {d.total} | {d.rolling_7d_avg:.1f} |"
            )
        lines.append("")

    if show_temporal_blocks and report.top_contributors is not None:
        tc = report.top_contributors
        lines.append("## 主要贡献来源" if zh else "## Top contributors")
        lines.append("")
        if tc.bssids:
            lines.append("### BSSID（按 `roam` + `rf_stir` 次数）" if zh
                         else "### BSSIDs (by `roam` + `rf_stir` count)")
            lines.append("")
            lines.append("| BSSID | roam + stir |")
            lines.append("|---|---:|")
            for b in tc.bssids:
                lines.append(
                    f"| `{ax('bssid', b.bssid)}` "
                    f"| {b.roam_count + b.stir_count} |"
                )
            lines.append("")
        if tc.ble_identifiers:
            lines.append("### BLE 设备（按 `ble_device_seen` 次数）" if zh
                         else "### BLE identifiers (by `ble_device_seen` count)")
            lines.append("")
            lines.append("| 标识 | 出现 |" if zh else "| Identifier | Seen |")
            lines.append("|---|---:|")
            for ble in tc.ble_identifiers:
                label = (
                    ax("ble", ble.identifier)
                    if a is not None
                    else ble.label
                )
                lines.append(f"| `{label}` | {ble.seen_count} |")
            lines.append("")
        if tc.lan_hosts:
            lines.append(
                "### LAN 主机（按 `lan_host_dhcp_rotation` 次数）" if zh
                else "### LAN hosts (by `lan_host_dhcp_rotation` count)",
            )
            lines.append("")
            lines.append("| MAC | DHCP 轮换 |" if zh else "| MAC | DHCP rotations |")
            lines.append("|---|---:|")
            for lan in tc.lan_hosts:
                label = (
                    ax("mac", lan.mac) if a is not None else lan.label
                )
                lines.append(f"| `{label}` | {lan.rotation_count} |")
            lines.append("")

    # ---- Glossary (always included — LLM benefits regardless of mode)
    lines.append("## 术语表" if zh else "## Glossary")
    lines.append("")
    if zh:
        # Event-type tokens stay verbatim — they're the data's vocabulary.
        lines.append(
            "- `rf_stir` —— RSSI 方差越过阈值；周围 RF 环境在变化。"
            "模式：`co_located`（同一物理 AP 的多个 BSSID 一起 stir —— "
            "多半是真实移动）；`spatial_channel`（单个 BSSID stir、邻居"
            "安静 —— 多半是干扰或客户端硬件怪癖）。"
        )
        lines.append(
            "- `roam` —— 客户端关联的 BSSID 变了。`kind=band_switch` 是"
            "同一物理 AP 的两个射频之间（例如同硬件 2.4 → 5 GHz）；"
            "`kind=inter_ap` 是物理上不同的 AP 之间。"
        )
        lines.append(
            "- `latency_spike` / `loss_burst` —— 网关或 WAN 锚定的 RTT "
            "越过阈值（spike：>200 ms 且 >5× 中位数；burst：最近 5 次"
            "探测丢了 3 次）。"
        )
        lines.append(
            "- `link_state` —— 活动 Wi-Fi 接口上的 `associated` / "
            "`disassociated` 转换。"
        )
        lines.append(
            "- `ble_device_seen` / `ble_device_left` —— 一个 BLE 设备"
            "（广播中或已连接）进入或老化出跟踪状态表。无去抖；连单条"
            "广播的幽灵 MAC 也各发一个事件。"
        )
        lines.append(
            "- `bonjour_service_seen` / `bonjour_service_left` —— 一个 "
            "mDNS 服务实例首次被观察到或被移除。"
        )
        lines.append(
            "- `lan_host_seen` / `lan_host_left` / "
            "`lan_host_dhcp_rotation` —— 一台 LAN 主机（非自身 / 非网关）"
            "在本地 /24 扫描内加入 / 离开 / 换了 IP。"
        )
    else:
        lines.append(
            "- `rf_stir` — RSSI variance crossed a threshold; the "
            "ambient RF environment is moving. Modes: `co_located` "
            "(multiple BSSIDs of the same physical AP both stirred — "
            "likely real motion); `spatial_channel` (one BSSID "
            "stirred, neighbours quiet — likely interference or "
            "client-side hardware quirk)."
        )
        lines.append(
            "- `roam` — the client's associated BSSID changed. "
            "`kind=band_switch` is between two radios of the same "
            "physical AP (e.g. 2.4 → 5 GHz on the same hardware); "
            "`kind=inter_ap` is between physically distinct APs."
        )
        lines.append(
            "- `latency_spike` / `loss_burst` — gateway- or "
            "WAN-anchored RTT exceeded thresholds (>200 ms AND >5× "
            "median for spikes; 3 of last 5 probes lost for bursts)."
        )
        lines.append(
            "- `link_state` — `associated` / `disassociated` "
            "transitions on the active Wi-Fi interface."
        )
        lines.append(
            "- `ble_device_seen` / `ble_device_left` — a BLE device "
            "(advertising OR connected) entered or aged out of the "
            "tracked-state map. No debounce; even single-advertisement "
            "ghost MACs fire one event each."
        )
        lines.append(
            "- `bonjour_service_seen` / `bonjour_service_left` — an "
            "mDNS service-instance was first observed or removed."
        )
        lines.append(
            "- `lan_host_seen` / `lan_host_left` / "
            "`lan_host_dhcp_rotation` — a LAN host (non-self / "
            "non-gateway) joined / departed / changed IP within "
            "the local /24 sweep."
        )
    lines.append("")

    # ---- Anonymization appendix (placeholder)
    if a is not None:
        lines.append("## 匿名化" if zh else "## Anonymization")
        lines.append("")
        if zh:
            lines.append(
                "匿名化已启用。句柄 ↔ 原值的对应表在生成本报告时已打到"
                "你的终端。**请保密那份映射** —— 把它粘进公共 LLM 聊天"
                "就破坏了匿名化的意义。"
            )
        else:
            lines.append(
                "Anonymization is active. The handle ↔ original "
                "mappings were printed to your terminal when this "
                "report was generated. **Keep that mapping private** — "
                "pasting it into a public LLM chat defeats the "
                "anonymization purpose."
            )
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def scene_summary(report: Report) -> str:
    """Short one-line summary of the scene(s) in this report.

    Returns strings like:
    - `home (cli)` — single scene, source named in parens
    - `office (env)` — single scene from env var
    - `2 × home, 1 × office` — multi-scene mix
    - `unknown (pre-scene-aware capture)` — no session_meta found

    Used in the Markdown report header.
    """
    if not report.scenes:
        return t("unknown (pre-scene-aware capture)")
    counts: dict[str, int] = {}
    for s in report.scenes:
        counts[s] = counts.get(s, 0) + 1
    if len(counts) == 1:
        scene = next(iter(counts))
        source = report.scene_sources.get(scene, "default")
        return f"{scene} ({source})"
    # Multi-scene: render in count-descending order, ties by name.
    parts = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return ", ".join(f"{n} × {name}" for name, n in parts)


def scene_llm_context_paragraph(report: Report) -> str:
    """Build the `[Scene context]` paragraph injected at the top of
    the LLM prompt.

    For single-scene captures the paragraph names the scene + cites
    the `llm_prior` from `scene_defaults`, backfilled with observed
    counters (BSSID / BLE identifiers) when available.

    For multi-scene mixes the paragraph names the mix and tells the
    LLM to compare across rather than apply one prior.

    For pre-scene-aware captures (no session_meta) the paragraph
    notes the gap and falls back to a generic prior.
    """
    from . import scene as _scene_mod
    zh = i18n.get_lang() == i18n.ZH
    header = "[场景背景]" if zh else "[Scene context]"
    if not report.scenes:
        if zh:
            return (
                f"{header}\n"
                "场景未知（pre-scene-aware 抓取 —— JSONL 没有 "
                "session_meta 行）。只应用通用先验。数据可能属于以下"
                "任一：home（稀疏，新奇性重要）、office（密集企业基线"
                "流动）、public（充满敌意的共享 Wi-Fi）、audit（原始"
                "抓取，无过滤）。"
            )
        return (
            "[Scene context]\n"
            "Scene unknown (pre-scene-aware capture — JSONL has no "
            "session_meta line). Apply general priors only. The "
            "data may span any of: home (sparse, novelty matters), "
            "office (dense enterprise baseline churn), public "
            "(hostile shared Wi-Fi), or audit (raw capture, no "
            "filtering)."
        )
    counts: dict[str, int] = {}
    for s in report.scenes:
        counts[s] = counts.get(s, 0) + 1
    if len(counts) == 1:
        scene = next(iter(counts))
        try:
            prior = _scene_mod.scene_defaults(scene).get("llm_prior", "")
        except ValueError:
            prior = ""
        if prior:
            prior = t(prior)  # localized via the ZH catalog
        env_facts: list[str] = []
        if report.observed_bssid_count:
            env_facts.append(
                (f"观察到 BSSID 数 {report.observed_bssid_count}" if zh
                 else f"observed BSSID count {report.observed_bssid_count}")
            )
        if report.observed_ble_identifier_count:
            env_facts.append(
                (f"观察到 BLE 标识数 {report.observed_ble_identifier_count}"
                 if zh else
                 f"observed BLE identifier count "
                 f"{report.observed_ble_identifier_count}")
            )
        facts = (
            (f"（{'；'.join(env_facts)}）" if zh else
             f" ({'; '.join(env_facts)})") if env_facts else ""
        )
        rhythm = ""
        rh = report.hourly_rhythms.get("ble_device_seen")
        if rh is not None and rh.total >= 50:
            rhythm = (
                (f" 观察到的 BLE 到达节律：最忙约 {rh.peak_hour:02d}:00，"
                 f"最闲约 {rh.quiet_hour:02d}:00。") if zh else
                (f" Observed BLE-arrival rhythm: busiest around "
                 f"{rh.peak_hour:02d}:00, quietest around "
                 f"{rh.quiet_hour:02d}:00.")
            )
        if zh:
            return (
                f"{header}\n"
                f"这些会话在 `{scene}` 模式下抓取{facts}。{prior} "
                f"关注偏离这个基线的地方，而不是基线本身。{rhythm}"
            )
        return (
            f"[Scene context]\n"
            f"These sessions were captured in `{scene}` mode{facts}. "
            f"{prior} Look for departures from this baseline, not "
            f"the baseline itself.{rhythm}"
        )
    # Multi-scene
    parts = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    mix = ", ".join(f"{n} × `{name}`" for name, n in parts)
    if zh:
        return (
            f"{header}\n"
            f"输入跨多个场景：{mix}。把每个场景的先验应用到它自己的"
            f"子集，而不是平均。当同一指标在不同基线下讲出不同故事时，"
            f"跨场景对比。"
        )
    return (
        f"[Scene context]\n"
        f"Input spans multiple scenes: {mix}. Apply each scene's "
        f"prior to its own subset rather than averaging. Compare "
        f"across scenes where the same metric tells different "
        f"stories under different baselines."
    )


def build_llm_prompt(report: Report) -> str:
    """Compose the analyst prompt for `prompt.txt`.

    Substitutes `<span>` and `<files>` from the report context.
    The rest of the text is constant.
    """
    if report.span_start and report.span_end:
        span_str = (
            f"{report.span_start.date().isoformat()} → "
            f"{report.span_end.date().isoformat()}"
        )
    else:
        span_str = "an unknown span" if i18n.get_lang() != i18n.ZH \
            else "一段未知的时间"
    files = len(report.source_paths) or 1
    scene_para = scene_llm_context_paragraph(report)
    if i18n.get_lang() == i18n.ZH:
        return (
            f"{scene_para}\n\n"
            f"你是一名无线 / 网络分析师，正在审阅一份 `diting` 报告"
            f"（macOS 终端 Wi-Fi / BLE / LAN 监视器）。报告覆盖 "
            f"{span_str}，跨 {files} 个会话日志。\n\n"
            f"你的任务：\n\n"
            f"1. 找出数据支持的前 3 个模式。\n"
            f"2. 对每个模式，给出最可能的根因，以及报告中支持它的证据。\n"
            f"3. 建议用户可以用 diting 跑的具体后续调查（例如「周二 "
            f"14:00-15:00 用 --log 抓一段再分析」）。\n"
            f"4. 当报告里的 ASCII 图暗示某种趋势时，把趋势复述为一句话"
            f"的论断，并标注以下之一：「数据支持」「弱信号」「推测」。\n"
            f"5. 如果报告含匿名化附录，不要尝试解码句柄 —— 把句柄当作"
            f"不透明标识符来分析。\n\n"
            f"时序与人口视角 —— 请显式应用：\n"
            f"- 节律与聚集：每种信号（BLE 到达、丢包、延迟、扰动、漫游）"
            f"在一天里集中在什么时候？指出峰值 / 谷值窗口和任何爬升"
            f"（例如早高峰填充），并说明这个时间意味着什么（占用、拥塞"
            f"窗口、备份任务）。\n"
            f"- 按稳定身份的复现：区分「少数物理设备整天在场」和「大量"
            f"短暂过客」。注意：BLE MAC / 每次出现的 id 会轮换，按原始 "
            f"id 计数会高估 —— 请从报告里按稳定身份的人口数推理，而不是"
            f"出现次数。\n"
            f"- 停留：短暂（秒级）vs 常驻（小时级）—— 高短暂占比意味着"
            f"人流，而非固定设备群。\n"
            f"- 跨信号共现：丢包 / 延迟 / 扰动是否和 BLE 到达峰值集中在"
            f"相同的小时？如果是，给出假设（例如人到达带来的空口争用）"
            f"以及能验证它的抓取 —— 不要断言因果。\n"
            f"- off-hours 异常：在本应安静的时段（公司夜间、家里工作日）"
            f"出现的活动，比同样的活动出现在正常时段更值得注意 —— 点"
            f"出来，并说明可能是什么在活动。\n\n"
            f"输出格式：markdown。不要逐字重复报告数据 —— 要解读它。"
            f"结论先行，再给证据。任何超出数据所示的推断都标为「假设」。\n\n"
            f"重要：不要臆测数据没有触及的原因。如果某处看着可疑但你"
            f"无法指向报告里具体的事件，就直说。\n\n"
            f"请用中文输出你的分析。\n"
        )
    return (
        f"{scene_para}\n\n"
        f"You are a wireless / network analyst reviewing a "
        f"`diting` report (macOS terminal Wi-Fi / BLE / LAN "
        f"monitor). The report covers {span_str} across {files} "
        f"session log(s).\n\n"
        f"Your task:\n\n"
        f"1. Identify the top 3 patterns the data supports.\n"
        f"2. For each pattern, name the most likely root cause "
        f"and the evidence in the report that supports it.\n"
        f"3. Suggest concrete follow-up investigations the user "
        f"could run with diting (e.g. \"capture during Tuesday "
        f"14:00-15:00 with --log and re-analyze\").\n"
        f"4. Where ASCII charts in the report suggest a trend, "
        f"restate the trend as a one-line claim and tag it with "
        f"one of: \"supported by data\", \"weak signal\", "
        f"\"speculative\".\n"
        f"5. If the report includes an Anonymization appendix, "
        f"do NOT try to decode the handles — analyze using the "
        f"handles as opaque identifiers.\n\n"
        f"Temporal & population lenses — apply these explicitly:\n"
        f"- Rhythm & clustering: when does each signal concentrate "
        f"(BLE arrivals, loss, latency, stir, roams) by hour? Name "
        f"the peak / quiet windows and any ramp (e.g. a morning "
        f"fill-up), and say what the timing implies (occupancy, a "
        f"congestion window, a backup job).\n"
        f"- Recurrence by STABLE identity: distinguish a few physical "
        f"devices present all day from many brief pass-bys. CAUTION: "
        f"BLE MAC / per-sighting ids rotate, so counting raw ids "
        f"over-counts — reason from the report's stable-identity "
        f"population figures, not sighting counts.\n"
        f"- Dwell: transient (seconds) vs resident (hours) — high "
        f"transient share means foot-traffic, not a fixed population.\n"
        f"- Cross-signal coincidence: do loss / latency / stir cluster "
        f"in the same hours as the BLE-arrival peak? If so, state the "
        f"hypothesis (e.g. airtime contention as people arrive) and "
        f"the capture that would test it — do not assert cause.\n"
        f"- Off-hours anomalies: activity when the scene expects quiet "
        f"(office overnight, home workday) is more noteworthy than the "
        f"same activity in-hours — call it out and say what could be "
        f"active.\n\n"
        f"Output format: markdown. Don't repeat the report data "
        f"verbatim — interpret it. Lead with conclusions, then "
        f"evidence. Mark any inference beyond what the data "
        f"shows as \"hypothesis\".\n\n"
        f"Important: don't speculate about causes the data "
        f"doesn't touch. If something looks suspicious but you "
        f"can't point to specific events in the report, say so.\n"
    )


def build_llm_document(
    report: Report,
    *,
    anonymizer: "Anonymizer | None" = None,
) -> str:
    """One self-contained Markdown document for `--for-llm`: the analyst
    prompt, a horizontal rule, then the full Markdown report inline.

    Handing this single string to an LLM (paste or attach) gives it both
    the instructions and the data — no second file to copy. When
    `anonymizer` is non-None, the report half is anonymized; the prompt
    half carries no identifiers.
    """
    prompt = build_llm_prompt(report)
    body = render_markdown(report, anonymizer=anonymizer)
    return f"{prompt}\n\n---\n\n{body}"


def report_to_dict(report: Report) -> dict[str, Any]:
    """Machine-readable view of a Report for `diting analyze --json`.

    Locale-stable English keys (an agent parses keys, never prose),
    mirroring the JSONL wire-format convention. Covers the same data
    the human `render` shows: scope, counts, link timeline, the
    temporal / population / coincidence aggregates, and the insights.
    None-valued aggregates are emitted as null so the shape is stable.
    """
    def _dwell(d: "DwellSummary | None") -> "dict | None":
        if d is None:
            return None
        return {
            "n": d.n, "p50_s": d.p50_s, "p90_s": d.p90_s,
            "transient": d.transient, "lingering": d.lingering,
            "resident": d.resident,
        }

    def _pop(p: "PopulationSummary | None") -> "dict | None":
        if p is None:
            return None
        return {
            "distinct_devices": p.distinct_devices, "residents": p.residents,
            "passersby": p.passersby,
            "unkeyable_sightings": p.unkeyable_sightings,
        }

    def _rhythm(r: HourlyRhythm) -> dict:
        return {
            "peak_hour": r.peak_hour, "peak_count": r.peak_count,
            "quiet_hour": r.quiet_hour, "quiet_count": r.quiet_count,
            "top_hours_share": round(r.top_hours_share, 4),
            "concentrated": r.concentrated, "total": r.total,
        }

    return {
        "span": {
            "start": report.span_start.isoformat() if report.span_start else None,
            "end": report.span_end.isoformat() if report.span_end else None,
        },
        "source_paths": list(report.source_paths),
        "scenes": list(report.scenes),
        "total_events": report.total_events,
        "counts_by_type": dict(report.counts_by_type),
        "associations": [
            {"ssid": s, "bssid": b} for s, b in report.associations
        ],
        "roams": report.roams,
        "band_switches": report.band_switches,
        "inter_ap_roams": report.inter_ap_roams,
        "disassociates": report.disassociates,
        "stir": {
            "count": report.stir_count,
            "modes": dict(report.stir_modes),
            "confidences": dict(report.stir_confidences),
            "sigma_p50": report.stir_sigma_p50,
        },
        "latency_spikes": report.latency_spike_count,
        "loss_bursts": {
            "count": report.loss_burst_count,
            "max_pct": report.loss_burst_max_pct,
        },
        "network_changes": [
            {"previous": p, "new": n} for p, n in report.network_changes
        ],
        "temporal": {
            "ble_dwell": _dwell(report.ble_dwell),
            "ble_population": _pop(report.ble_population),
            "hourly_rhythms": {
                cat: _rhythm(rh) for cat, rh in report.hourly_rhythms.items()
            },
            "co_peaks": [
                {"hour": h, "categories": list(cats)}
                for h, cats in report.co_peaks
            ],
            "hour_of_day": {
                str(h): dict(b) for h, b in report.hour_of_day.items()
            },
        },
        "insights": [
            {
                "severity": i.severity, "title": i.title,
                "detail": i.detail, "todo": i.todo,
            }
            for i in report.insights
        ],
    }


def render(report: Report) -> str:
    """Format the report as a multi-line string suitable for
    plain stdout. Keeps to ASCII art so it stays grep-friendly
    in pipes; no terminal-specific colour codes.
    """
    lines: list[str] = []
    header_path = report.path or "(stdin)"
    if len(report.source_paths) > 1:
        header_path = f"{len(report.source_paths)} files"
    lines.append(t("diting analyse {path}", path=header_path))
    lines.append("=" * 60)

    # Scope header (multi-file / --since signal only).
    enable_cross_session = (
        len(report.source_paths) > 1 or report.since is not None
    )
    # The cross-session BLOCKS (hour-of-day, temporal, etc.) also show
    # for a single long log — `hour_of_day` is non-empty exactly when the
    # analyser's temporal gate fired (multi-file / --since / long span).
    show_temporal_blocks = enable_cross_session or bool(report.hour_of_day)
    if enable_cross_session:
        if report.span_start and report.span_end:
            span_days = (report.span_end - report.span_start).days
            span_str = (
                f"{report.span_start.astimezone().date().isoformat()} → "
                f"{report.span_end.astimezone().date().isoformat()} "
                f"({span_days} days)"
            )
        else:
            span_str = "(no events)"
        since_str = (
            _format_duration(report.since.total_seconds())
            if report.since is not None else "none"
        )
        lines.append(t(
            "Scope: {files} files · {span} · --since {since}",
            files=len(report.source_paths) or 1,
            span=span_str,
            since=since_str,
        ))
        lines.append("")

    # Time span
    if report.span_start and report.span_end:
        delta = report.span_end - report.span_start
        local_start = report.span_start.astimezone()
        local_end = report.span_end.astimezone()
        # Drop the end date when it matches the start date (most logs
        # are single-session, short enough that repeating the date
        # reads as noise). Re-include it for multi-day spans where
        # `22:04:21 → 13:01:33` reads ambiguously as same-day even
        # though the duration says 14h 57m.
        end_fmt = (
            "%H:%M:%S" if local_start.date() == local_end.date()
            else "%Y-%m-%d %H:%M:%S"
        )
        lines.append(t(
            "Time range: {start} → {end}  ({duration})",
            start=local_start.strftime("%Y-%m-%d %H:%M:%S"),
            end=local_end.strftime(end_fmt),
            duration=_format_duration(delta.total_seconds()),
        ))
    lines.append(t("Total events: {n}", n=report.total_events))
    if report.counts_by_type:
        for kind, n in sorted(report.counts_by_type.items()):
            lines.append(f"  - {kind}: {n}")
    lines.append("")

    # Connection summary
    if report.associations:
        ssid, bssid = report.associations[-1]
        lines.append(t("Latest association: {ssid} @ {bssid}",
                       ssid=ssid or "?", bssid=bssid or "?"))
    if report.roams:
        lines.append(t(
            "Roam events: {n}  (band switch {b} / inter-AP {i})",
            n=report.roams, b=report.band_switches, i=report.inter_ap_roams,
        ))
    if report.disassociates:
        lines.append(t("Disassociates: {n}", n=report.disassociates))
    lines.append("")

    # RF environment
    if report.stir_count:
        lines.append(t("RF stir events: {n}", n=report.stir_count))
        modes = ", ".join(
            f"{k}={v}" for k, v in sorted(report.stir_modes.items())
        )
        confs = ", ".join(
            f"{k}={v}" for k, v in sorted(report.stir_confidences.items())
        )
        # Label width 13 matches the EN baseline ("confidence:  ")
        # so values still left-align in a cell-aware way after the
        # ZH catalog substitutes "模式：" / "置信度：" / "位置：".
        lines.append("  " + pad_cells(t("modes:"), 13) + modes)
        lines.append("  " + pad_cells(t("confidence:"), 13) + confs)
        if report.stir_sigma_min is not None:
            lines.append(t(
                "  σ range:     {lo} – {hi} dB  (median {p50})",
                lo=f"{report.stir_sigma_min:.1f}",
                hi=f"{report.stir_sigma_max:.1f}",
                p50=f"{report.stir_sigma_p50:.1f}",
            ))
        if len(report.stir_locations) > 1:
            top = sorted(
                report.stir_locations.items(),
                key=lambda kv: kv[1], reverse=True,
            )[:3]
            joined = ", ".join(f"{k}({v})" for k, v in top)
            lines.append("  " + pad_cells(t("locations:"), 13) + joined)
        lines.append("")

    # Latency / loss
    if report.latency_spike_count or report.loss_burst_count:
        if report.latency_spike_count:
            by = ", ".join(
                f"{k}={v}" for k, v in sorted(report.latency_spike_by_target.items())
            )
            lines.append(t(
                "Latency spikes: {n}  ({by})  peak {peak} ms",
                n=report.latency_spike_count, by=by,
                peak=f"{report.latency_spike_max_rtt:.0f}"
                if report.latency_spike_max_rtt else "?",
            ))
        if report.loss_burst_count:
            scaled = _scaled_loss_pct(report)
            lines.append(t(
                "Loss bursts: {n}  peak {pct}%",
                n=report.loss_burst_count,
                pct=f"{scaled:.0f}" if scaled is not None else "?",
            ))
        lines.append("")

    # Insights
    if report.insights:
        lines.append(t("Insights"))
        lines.append("-" * 60)
        for ins in report.insights:
            marker = {"warn": "[!]", "note": "[*]", "info": "[i]"}.get(
                ins.severity, "[i]",
            )
            lines.append(f"{marker} {ins.title}")
            for line in ins.detail.splitlines() or [""]:
                lines.append(f"    {line}")
            if ins.todo:
                lines.append(f"    " + t("TODO: ") + ins.todo)
            lines.append("")
    else:
        lines.append(t(
            "No specific insights — the session looks routine. "
            "Re-run with a longer log or a noisier environment for "
            "richer signal."
        ))

    # ---------- cross-session blocks (A2) ----------
    if show_temporal_blocks:
        lines.extend(_render_temporal(report))
        lines.extend(_render_hour_of_day(report.hour_of_day))
        lines.extend(_render_day_x_hour(report.day_of_week_x_hour))
        lines.extend(_render_per_network(report.per_network))
        lines.extend(_render_daily_trend(report.daily_trend))
        if report.top_contributors is not None:
            lines.extend(_render_top_contributors(report.top_contributors))

    return "\n".join(lines).rstrip() + "\n"


# ---------- cross-session renderers ----------

_BAR_BLOCKS = "▁▂▃▄▅▆▇█"


def _bar(value: int, max_value: int, width: int = 40) -> str:
    if max_value <= 0:
        return " " * width
    filled = int(value * width / max_value)
    return "█" * filled + " " * (width - filled)


def _density_char(value: int, max_value: int) -> str:
    if value == 0:
        return " "
    if max_value <= 0:
        return " "
    # 8 bins of intensity.
    idx = max(0, min(7, int((value - 1) * 8 / max(max_value, 1))))
    return _BAR_BLOCKS[idx]


def _render_temporal(report: Report) -> list[str]:
    """Compact at-a-glance temporal / population block (the numbers
    behind the temporal insights). Empty when no aggregate is set."""
    pop, dw = report.ble_population, report.ble_dwell
    rh = report.hourly_rhythms.get("ble_device_seen")
    if pop is None and dw is None and rh is None:
        return []
    out = ["", t("Temporal & population"), "-" * 60]
    if rh is not None:
        out.append(t(
            "  BLE rhythm   peak {peak}:00 ({pk}/h) · quiet {quiet}:00 "
            "({qt}/h)",
            peak=rh.peak_hour, pk=rh.peak_count,
            quiet=rh.quiet_hour, qt=rh.quiet_count,
        ))
    if pop is not None:
        out.append(t(
            "  Population   {n} devices · {res} resident · {passers} "
            "pass-by",
            n=pop.distinct_devices, res=pop.residents, passers=pop.passersby,
        ))
    if dw is not None:
        out.append(t(
            "  Dwell        p50 {p50} · p90 {p90} · {trans} brief / "
            "{ling} lingering / {res} resident",
            p50=_format_duration(dw.p50_s), p90=_format_duration(dw.p90_s),
            trans=dw.transient, ling=dw.lingering, res=dw.resident,
        ))
    if report.co_peaks:
        joined = "; ".join(
            f"{h:02d}:00 (" + ", ".join(_category_label(c) for c in cats) + ")"
            for h, cats in report.co_peaks
        )
        out.append(t("  Co-peaks     {joined}", joined=joined))
    return out


def _render_hour_of_day(buckets: dict[int, dict[str, int]]) -> list[str]:
    if not buckets:
        return []
    out: list[str] = []
    out.append("")
    totals = {h: sum(buckets[h].values()) for h in range(24)}
    grand_total = sum(totals.values())
    out.append(t("Events by hour-of-day                  total: {n}",
                 n=grand_total))
    out.append("-" * 60)
    max_total = max(totals.values()) if totals else 0
    for h in range(24):
        bar = _bar(totals[h], max_total, width=30)
        hint = ""
        if buckets[h]:
            top_type = max(buckets[h].items(), key=lambda kv: kv[1])
            hint = f"  ({t('most:')} {top_type[0]})"
        out.append(f"  {h:02d}  {bar}  {totals[h]:>5}{hint}")
    out.append("")
    return out


def _render_day_x_hour(grid: tuple[tuple[int, ...], ...]) -> list[str]:
    if not grid:
        return []
    out: list[str] = []
    max_cell = max((max(row) for row in grid), default=0)
    if max_cell <= 0:
        return []
    out.append(t("Day × hour heatmap (density)"))
    out.append("-" * 60)
    names = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
    for i, row in enumerate(grid):
        cells = "".join(_density_char(v, max_cell) for v in row)
        out.append(f"  {t(names[i])}  {cells}")
    out.append("       0   6   12  18  23")
    out.append("")
    return out


def _render_per_network(nets: tuple[NetworkAggregate, ...]) -> list[str]:
    if not nets:
        return []
    out: list[str] = []
    out.append(t("Top networks by event volume                 (top 10)"))
    out.append("-" * 60)
    for n in nets[:10]:
        # Compact per-type breakdown — only show non-zero buckets.
        bd = " · ".join(
            f"{k} {v}" for k, v in sorted(n.counts_by_type.items())
        )
        out.append(f"  {n.network_label:<30} {n.total:>6} {t('events')}   {bd}")
    out.append("")
    return out


def _render_daily_trend(daily: tuple[DailyCount, ...]) -> list[str]:
    if not daily:
        return []
    out: list[str] = []
    out.append(t(
        "Daily trend ({n}-day window, with 7-day rolling avg)",
        n=len(daily),
    ))
    out.append("-" * 60)
    # Daily-trend sparklines need per-family per-day counts. Recompute
    # from the daily series via a second pass — we don't have the raw
    # events here, just the totals. So show the total sparkline; the
    # per-family detail lives in hour-of-day breakdown.
    max_total = max((d.total for d in daily), default=0)
    spark = "".join(_density_char(d.total, max_total) for d in daily)
    out.append(f"  {t('total')}  {spark}")
    out.append("")
    return out


def _render_top_contributors(top: TopContributors) -> list[str]:
    out: list[str] = []
    out.append(t("Top contributors"))
    out.append("-" * 60)
    if top.bssids:
        out.append(t("  BSSID                              roam+stir"))
        for b in top.bssids:
            out.append(
                f"    {b.label:<32} "
                f"{b.roam_count + b.stir_count:>6}"
            )
        out.append("")
    if top.ble_identifiers:
        out.append(t("  BLE device                         seen events"))
        for ble in top.ble_identifiers:
            out.append(f"    {ble.label:<32} {ble.seen_count:>6}")
        out.append("")
    if top.lan_hosts:
        out.append(t("  LAN host                           dhcp rotations"))
        for lan in top.lan_hosts:
            out.append(f"    {lan.label:<32} {lan.rotation_count:>6}")
        out.append("")
    return out
