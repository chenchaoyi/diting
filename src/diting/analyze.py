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
import statistics
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

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
class Report:
    """Aggregated stats + insights for a single log."""
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


# ---------- analyser ----------

def analyze(events: list[dict[str, Any]], *, source_path: str = "") -> Report:
    """Turn a list of parsed events into a Report.

    Caller-supplied ``source_path`` flows through so the renderer
    can surface "analysing /path/to/log.jsonl" as the heading;
    the analyser itself never reads the file.
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
        if kind == "latency_spike":
            ip = ev.get("target_ip")
            if isinstance(ip, str) and ev.get("target") == "router":
                distinct_router_ips.add(ip)

    report = Report(
        path=source_path,
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
    )

    insights = list(_run_heuristics(report, events))
    return replace(report, insights=insights)


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


def render(report: Report) -> str:
    """Format the report as a multi-line string suitable for
    plain stdout. Keeps to ASCII art so it stays grep-friendly
    in pipes; no terminal-specific colour codes.
    """
    lines: list[str] = []
    lines.append(t("diting analyse {path}", path=report.path or "(stdin)"))
    lines.append("=" * 60)

    # Time span
    if report.span_start and report.span_end:
        delta = report.span_end - report.span_start
        lines.append(t(
            "Time range: {start} → {end}  ({duration})",
            start=report.span_start.astimezone().strftime("%Y-%m-%d %H:%M:%S"),
            end=report.span_end.astimezone().strftime("%H:%M:%S"),
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

    return "\n".join(lines).rstrip() + "\n"
