"""Rule-based JSONL log analyser.

Reads a wifiscope event log (the JSONL format produced by both
``wifiscope monitor`` and ``wifiscope --log``) and turns it into
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
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .i18n import t


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
    )

    insights = list(_run_heuristics(report, events))
    return Report(
        path=report.path,
        span_start=report.span_start,
        span_end=report.span_end,
        total_events=report.total_events,
        counts_by_type=report.counts_by_type,
        associations=report.associations,
        roams=report.roams,
        band_switches=report.band_switches,
        inter_ap_roams=report.inter_ap_roams,
        disassociates=report.disassociates,
        stir_count=report.stir_count,
        stir_modes=report.stir_modes,
        stir_confidences=report.stir_confidences,
        stir_locations=report.stir_locations,
        stir_sigma_min=report.stir_sigma_min,
        stir_sigma_max=report.stir_sigma_max,
        stir_sigma_p50=report.stir_sigma_p50,
        latency_spike_count=report.latency_spike_count,
        latency_spike_by_target=report.latency_spike_by_target,
        latency_spike_max_rtt=report.latency_spike_max_rtt,
        loss_burst_count=report.loss_burst_count,
        loss_burst_max_pct=report.loss_burst_max_pct,
        insights=insights,
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
                "No JSONL events parsed. Is wifiscope still writing? "
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
                "Update wifiscope and re-record. Existing data is still "
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
                "wifiscope cannot upgrade events to high confidence — "
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
        out.append(Insight(
            severity="warn",
            title=t("Real packet loss observed"),
            detail=t(
                "{n} loss-burst events (peak {pct}%). This is sustained "
                "loss, not single-packet jitter — investigate before "
                "assuming a transient.",
                n=r.loss_burst_count,
                pct=f"{r.loss_burst_max_pct:.0f}" if r.loss_burst_max_pct else "?",
            ),
            todo=t(
                "Check the gateway probe target separately from WAN. "
                "Gateway loss → LAN issue (cable, AP overload). WAN "
                "loss only → ISP / upstream issue."
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

def render(report: Report) -> str:
    """Format the report as a multi-line string suitable for
    plain stdout. Keeps to ASCII art so it stays grep-friendly
    in pipes; no terminal-specific colour codes.
    """
    lines: list[str] = []
    lines.append(t("wifiscope analyse {path}", path=report.path or "(stdin)"))
    lines.append("=" * 60)

    # Time span
    if report.span_start and report.span_end:
        delta = report.span_end - report.span_start
        lines.append(t(
            "Time range: {start} → {end}  ({mins} min)",
            start=report.span_start.astimezone().strftime("%Y-%m-%d %H:%M:%S"),
            end=report.span_end.astimezone().strftime("%H:%M:%S"),
            mins=int(delta.total_seconds() // 60) or 1,
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
        lines.append(f"  modes:       {modes}")
        lines.append(f"  confidence:  {confs}")
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
            lines.append(f"  locations:   {joined}")
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
            lines.append(t(
                "Loss bursts: {n}  peak {pct}%",
                n=report.loss_burst_count,
                pct=f"{report.loss_burst_max_pct:.0f}"
                if report.loss_burst_max_pct else "?",
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
