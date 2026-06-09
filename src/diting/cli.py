"""Command-line entry point.

Subcommands:

    diting             launch the TUI (default)
    diting once        one-shot snapshot of the current connection
    diting watch       streaming event log (Ctrl+C to quit)
    diting monitor     headless JSONL events for long-runs / Home Assistant
    diting calibrate   record an "empty room" RSSI baseline
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import i18n
from . import familiarity as _familiarity
from ._watchdog import SilenceClock, WatchdogConfig, maybe_notify
from .event_log import EventLogger
from .environment import (
    EnvironmentMonitor,
    load_calibration,
    write_calibration,
)
from .events import (
    EventRing,
    LatencySpikeEvent,
    LinkStateEvent,
    LossBurstEvent,
    event_to_jsonl,
)
from .i18n import t
from .latency import (
    LatencyPoller,
    detect_latency_spike,
    detect_loss_burst,
)
from .macos_backend import MacOSWiFiBackend
from .models import Connection
from .network import (
    NetworkInventory,
    band_label,
    format_bssid,
    load_inventory,
    lookup_ap_vendor,
    resolve_config_path,
)
from .poller import (
    ConnectionUpdate,
    Event,
    RoamEvent,
    ScanUpdate,
    WiFiPoller,
)

def _denied_hint() -> str:
    return t(
        "WARNING: SSID and BSSID are hidden. CoreWLAN is redacted by Location\n"
        "         Services and the SCDynamicStore fallback also returned\n"
        "         nothing. Grant Location Services to your terminal app, or\n"
        "         see README's macOS 26 caveats section.\n"
    )


def _fallback_hint() -> str:
    return t("note: SSID/BSSID via SCDynamicStore fallback (CoreWLAN is redacted).\n")


def _fmt(value: object, suffix: str = "") -> str:
    if value is None:
        return "n/a"
    return f"{value}{suffix}"


# ---------- one-shot mode ----------

def _print_connection(c: Connection, inv: NetworkInventory) -> None:
    # Acronyms that mean the same thing in both languages keep their
    # English form (SSID / BSSID / RSSI / MCS / NSS / IP / Tx Rate /
    # Max Link / PHY Mode); only the descriptive labels translate.
    rows: list[tuple[str, str]] = [
        ("SSID", _fmt(c.ssid)),
        ("BSSID", format_bssid(c.bssid, c.channel, inv)),
        ("RSSI", _fmt(c.rssi_dbm, " dBm")),
        (t("Noise"), _fmt(c.noise_dbm, " dBm")),
        ("Tx Rate", _fmt(c.tx_rate_mbps, " Mbps")),
        ("Max Link", _fmt(c.max_link_speed_mbps, " Mbps")),
        (t("Channel"), _fmt(c.channel)),
        (t("Width"), _fmt(c.channel_width_mhz, " MHz")),
        (t("Band"), _fmt(c.channel_band)),
        ("PHY Mode", _fmt(c.phy_mode)),
        (t("Security"), _fmt(c.security)),
        ("MCS", _fmt(c.mcs_index)),
        ("NSS", _fmt(c.nss)),
        (t("Country"), _fmt(c.country_code)),
        (t("This Mac"), _fmt(c.interface_mac)),
        ("IP", _fmt(c.ip_address)),
        (t("Router"), _fmt(c.router_ip)),
    ]
    # cell-aware width so a Chinese label like "本机 MAC" (8 cells)
    # lines up with an ASCII label like "Tx Rate" (7 cells) in the
    # same column instead of the byte-counting str.ljust default.
    from .i18n import pad_cells
    from rich.cells import cell_len
    label_w = max(cell_len(label) for label, _ in rows)
    for label, value in rows:
        print(f"  {pad_cells(label, label_w)}  {value}")


def _run_once(args: list[str] | None = None) -> None:
    args = args or []
    if "--help" in args or "-h" in args:
        print(_once_help(), end="")
        return
    json_mode = "--json" in args
    backend = MacOSWiFiBackend()
    inv = load_inventory()
    conn = backend.get_connection()
    state = backend.permission_state()
    if json_mode:
        from .models import connection_to_dict
        payload = {
            "backend": backend.name,
            "permission_state": state,
            "associated": conn is not None,
            "connection": connection_to_dict(conn) if conn else None,
        }
        print(json.dumps(payload, ensure_ascii=False))
        sys.exit(0 if conn is not None else 1)
    print(t("backend:    {name}", name=backend.name))
    if conn is None:
        print(t("status:     not associated"))
        sys.exit(1)
    print(t("timestamp:  {ts}", ts=conn.timestamp.isoformat(timespec="seconds")))
    print()
    _print_connection(conn, inv)
    if state == "denied":
        print()
        print(_denied_hint(), end="")
    elif state == "fallback":
        print()
        print(_fallback_hint(), end="")


# ---------- watch mode ----------

# Identity tuple — the parts of a Connection that, if any change, mean
# something a human would care about. RSSI / noise / tx rate are noisy
# fluctuating fields handled with a separate threshold.
_IDENTITY_FIELDS = (
    "ssid",
    "bssid",
    "channel",
    "channel_width_mhz",
    "channel_band",
    "phy_mode",
    "security",
)
_RSSI_DELTA_THRESHOLD_DB = 5
_HEARTBEAT_SECONDS = 10.0


def _identity_key(c: Connection | None) -> tuple:
    if c is None:
        return ("disconnected",)
    return tuple(getattr(c, f) for f in _IDENTITY_FIELDS)


def _format_conn_line(c: Connection | None, inv: NetworkInventory) -> str:
    if c is None:
        return "conn   <not associated>"
    return (
        f"conn   ssid={_fmt(c.ssid)}  bssid={format_bssid(c.bssid, c.channel, inv)}  "
        f"rssi={_fmt(c.rssi_dbm, 'dBm')}  "
        f"ch{c.channel or 0}/{c.channel_band or '?'}/{_fmt(c.channel_width_mhz, 'MHz')}  "
        f"{c.phy_mode or '?'}  {c.security or '?'}"
    )


def _format_scan_line(results: list) -> str:
    return f"scan   {len(results)} APs visible"


def _format_roam_line(event: RoamEvent, inv: NetworkInventory) -> str:
    same = inv.is_same_ap(event.previous_bssid, event.new_bssid)
    prev = format_bssid(event.previous_bssid, event.previous_channel, inv)
    new = format_bssid(event.new_bssid, event.new_channel, inv)
    if same:
        prev_band = band_label(event.previous_channel) or "?"
        new_band = band_label(event.new_channel) or "?"
        ap_name = inv.resolve(event.new_bssid) or "same AP"
        tag = f"[band switch on {ap_name}: {prev_band} -> {new_band}]"
    else:
        tag = "[inter-AP roam]"
    return f"ROAM   {prev}  ->  {new}   {tag}"


async def _run_watch(args: list[str] | None = None) -> None:
    args = args or []
    if "--help" in args or "-h" in args:
        print(_watch_help(), end="")
        return
    json_mode = "--json" in args
    # In --json mode the change-event line-stream is the stdout output;
    # all the human chrome (backend / inventory / hints) goes to stderr.
    chrome = sys.stderr if json_mode else sys.stdout
    backend = MacOSWiFiBackend()
    inv = load_inventory()
    print(t("backend: {name}  (Ctrl+C to quit)", name=backend.name),
          file=chrome)
    if inv.aps or inv.radio_overrides:
        print(t(
            "inventory: {n_aps} APs, {n_overrides} overrides — {path}",
            n_aps=len(inv.aps),
            n_overrides=len(inv.radio_overrides),
            path=resolve_config_path(),
        ), file=chrome)
    perm = backend.permission_state()
    if perm == "denied":
        print(file=chrome)
        print(_denied_hint(), end="", file=chrome)
    elif perm == "fallback":
        print(_fallback_hint(), end="", file=chrome)
    print(file=chrome)

    poller = WiFiPoller(backend)
    state: dict = {"last_key": None, "last_rssi": None, "last_print_at": 0.0}

    async for event in poller.events():
        if json_mode:
            obj = _watch_event_to_json(event, state, inv)
            if obj is not None:
                print(json.dumps(obj, ensure_ascii=False), flush=True)
            continue
        line = _render(event, state, inv)
        if line is not None:
            now_str = datetime.now().strftime("%H:%M:%S")
            print(f"{now_str}  {line}", flush=True)


def _watch_event_to_json(
    event: Event, state: dict, inv: NetworkInventory,
) -> dict | None:
    """One JSON object per surfaced watch event, or None to skip — the
    same dedup decision `_render` makes, shaped as data instead of prose.
    Locale-stable English keys; ts is ISO-8601 with offset."""
    ts = datetime.now().astimezone().isoformat()
    if isinstance(event, ScanUpdate):
        return {
            "ts": ts, "kind": "scan",
            "bssid_count": len(event.results),
        }
    if isinstance(event, RoamEvent):
        return {
            "ts": ts, "kind": "roam",
            "previous_bssid": event.previous_bssid,
            "new_bssid": event.new_bssid,
            "previous_channel": event.previous_channel,
            "new_channel": event.new_channel,
        }
    assert isinstance(event, ConnectionUpdate)
    c = event.connection
    key = _identity_key(c)
    rssi = c.rssi_dbm if c is not None else None
    now = time.monotonic()
    identity_changed = key != state["last_key"]
    rssi_jumped = (
        rssi is not None and state["last_rssi"] is not None
        and abs(rssi - state["last_rssi"]) >= _RSSI_DELTA_THRESHOLD_DB
    )
    heartbeat_due = now - state["last_print_at"] >= _HEARTBEAT_SECONDS
    first_print = state["last_print_at"] == 0.0
    if not (identity_changed or rssi_jumped or heartbeat_due or first_print):
        return None
    state["last_key"] = key
    state["last_rssi"] = rssi
    state["last_print_at"] = now
    from .models import connection_to_dict
    return {
        "ts": ts, "kind": "connection",
        "associated": c is not None,
        "connection": connection_to_dict(c) if c is not None else None,
    }


def _render(event: Event, state: dict, inv: NetworkInventory) -> str | None:
    """Decide whether and how to render this event.

    Mutates `state` to track last-printed identity / RSSI / timestamp
    for connection dedup. Returns the formatted line, or None to skip.
    """
    if isinstance(event, ScanUpdate):
        return _format_scan_line(event.results)
    if isinstance(event, RoamEvent):
        return _format_roam_line(event, inv)
    assert isinstance(event, ConnectionUpdate)

    c = event.connection
    key = _identity_key(c)
    rssi = c.rssi_dbm if c is not None else None
    now = time.monotonic()

    identity_changed = key != state["last_key"]
    rssi_jumped = (
        rssi is not None
        and state["last_rssi"] is not None
        and abs(rssi - state["last_rssi"]) >= _RSSI_DELTA_THRESHOLD_DB
    )
    heartbeat_due = now - state["last_print_at"] >= _HEARTBEAT_SECONDS
    first_print = state["last_print_at"] == 0.0

    if not (identity_changed or rssi_jumped or heartbeat_due or first_print):
        return None

    state["last_key"] = key
    state["last_rssi"] = rssi
    state["last_print_at"] = now
    return _format_conn_line(c, inv)


# ---------- monitor (headless JSONL) ----------

async def _run_monitor(
    args: list[str], *, scene_source: str = "default",
) -> None:
    """Long-running headless event stream.

    Spawns WiFiPoller + LatencyPoller + EnvironmentMonitor and emits
    one JSONL document per event to stdout (or ``--out path.jsonl``
    when set), with ``--notify`` raising a macOS Notification Centre
    alert for high-confidence events.

    ``scene_source`` is threaded from ``main()`` (where ``--scene`` /
    ``DITING_SCENE`` were resolved) so the session_meta line written
    here can record HOW the scene was picked.
    """
    out_path = _arg_value(args, "--out")
    notify = "--notify" in args
    gateway_override = _arg_value(args, "--gateway")
    wan_override = _arg_value(args, "--wan")

    backend = MacOSWiFiBackend()
    inv = load_inventory()
    monitor = EnvironmentMonitor(
        inventory=inv, calibration=load_calibration(),
    )

    logger = (
        EventLogger.to_path(out_path) if out_path
        else EventLogger.to_stdout()
    )
    # Companion forwarding (opt-in via `diting companion pair`). When
    # paired, every emitted payload is also offered to the sink via the
    # logger's observer tap — the exact dict the JSONL line carries.
    companion_sink = None
    try:
        from .companion import runtime as _companion_runtime
        companion_sink = _companion_runtime.build_sink()
    except Exception:
        companion_sink = None
    if companion_sink is not None:
        logger.set_observer(companion_sink.offer)
    # Familiarity / baseline store — classifies seen events against the
    # persisted history. Always-on so the baseline accrues across sessions.
    familiarity_store = None
    try:
        familiarity_store = _familiarity.FamiliarityStore(
            _familiarity.default_store_path(),
        )
        logger.set_familiarity_store(familiarity_store)
    except Exception:
        familiarity_store = None
    # Session header — must be the first line emitted, byte-identical
    # to the TUI's --log path so downstream readers don't branch on
    # source. Scene was resolved by main() before dispatching; we
    # only thread the source through here.
    #
    # Synchronously fetch the connection ONCE before emitting so
    # session_meta carries the at-launch SSID + gateway_ip rather
    # than null. Pre-v1.7.1 this call ran before any poll
    # completed and every session_meta line reported `ssid: null`
    # even when the host was associated. Failure (no Wi-Fi yet,
    # helper not ready) is absorbed as None so the disassociated-
    # at-launch path keeps working.
    from . import scene as _scene_mod
    try:
        startup_conn = backend.get_connection()
    except Exception:
        startup_conn = None
    logger.emit_session_meta(
        scene=_scene_mod.get_scene(),
        scene_source=scene_source,
        ssid=startup_conn.ssid if startup_conn else None,
        gateway_ip=startup_conn.router_ip if startup_conn else None,
    )

    poller = WiFiPoller(backend)

    # The latency target list is a moving target — we can only start
    # the LatencyPoller once we have a gateway. Spin up a small
    # waiting loop instead of blocking the WiFi consumer with a long
    # one-shot probe.
    latency_state: dict = {
        "poller": None,
        "wan_override": wan_override,
        "gateway_override": gateway_override,
    }

    watchdog_cfg = WatchdogConfig.from_env() if notify else None
    silence_clock = (
        SilenceClock(watchdog_cfg.silence_window_s) if notify else None
    )

    async def _notify(payload: dict, target: str) -> None:
        if not notify:
            return
        await maybe_notify(
            payload,
            target=target,
            clock=silence_clock,
            config=watchdog_cfg,
        )

    last_ssid: dict[str, str | None] = {"value": None}

    async def wifi_consumer() -> None:
        async for event in poller.events():
            now = datetime.now(timezone.utc)
            if isinstance(event, ConnectionUpdate):
                conn = event.connection
                if conn is not None:
                    last_ssid["value"] = conn.ssid
                logger.emit_connection_update(
                    conn, now=now,
                    vendor=lookup_ap_vendor(
                        conn.bssid if conn else None
                    ),
                )
                if conn is None:
                    continue
                # Late-bind LatencyPoller once we know the gateway.
                if latency_state["poller"] is None and (
                    latency_state["gateway_override"] or conn.router_ip
                ):
                    gateway_ip = (
                        latency_state["gateway_override"] or conn.router_ip
                    )
                    latency_state["poller"] = LatencyPoller(
                        gateway_ip=gateway_ip,
                        wan_ip=latency_state["wan_override"],
                    )
                    asyncio.get_running_loop().create_task(
                        latency_consumer(latency_state["poller"]),
                        name="latency-consumer",
                    )
                if conn.bssid is not None and conn.rssi_dbm is not None:
                    monitor.ingest(
                        conn.bssid, conn.rssi_dbm, now,
                        ssid=conn.ssid,
                    )
                    for stir in monitor.fire_events(now):
                        logger.emit_rf_stir(stir)
                        await _notify(
                            {
                                "type": "rf_stir",
                                "confidence": stir.confidence,
                                "location": stir.location,
                            },
                            target=stir.location,
                        )
            elif isinstance(event, ScanUpdate):
                for r in event.results:
                    if r.bssid is not None and r.rssi_dbm is not None:
                        monitor.ingest(
                            r.bssid, r.rssi_dbm, now,
                            ssid=r.ssid,
                        )
                for stir in monitor.fire_events(now):
                    logger.emit_rf_stir(stir)
                    await _notify(
                        {
                            "type": "rf_stir",
                            "confidence": stir.confidence,
                            "location": stir.location,
                        },
                        target=stir.location,
                    )
            elif isinstance(event, RoamEvent):
                kind = (
                    "band_switch"
                    if inv.is_same_ap(event.previous_bssid, event.new_bssid)
                    else "inter_ap"
                )
                logger.emit_roam(
                    event, kind=kind,
                    ssid=last_ssid["value"],
                    previous_vendor=lookup_ap_vendor(event.previous_bssid),
                    new_vendor=lookup_ap_vendor(event.new_bssid),
                )

    last_event_at: dict[tuple[str, str], float] = {}

    def should_fire(kind: str, target: str, cooldown_s: float = 30.0) -> bool:
        now = time.monotonic()
        last = last_event_at.get((kind, target))
        if last is not None and (now - last) < cooldown_s:
            return False
        last_event_at[(kind, target)] = now
        return True

    async def latency_consumer(lp: LatencyPoller) -> None:
        async for sample in lp.events():
            history = list(lp._history.get(sample.target, ()))
            if not history:
                continue
            spike = detect_latency_spike(history)
            if spike is not None and sample is spike:
                if should_fire("latency_spike", sample.target):
                    agg = lp.aggregate(sample.target)
                    rtt_ms = round(sample.rtt_ms or 0.0, 1)
                    logger.emit_latency_spike(LatencySpikeEvent(
                        timestamp=sample.ts,
                        target=sample.target,
                        target_ip=sample.target_ip,
                        rtt_ms=rtt_ms,
                        loss_pct=round(agg.loss_pct or 0.0, 1),
                    ))
                    await _notify(
                        {
                            "type": "latency_spike",
                            "target": sample.target,
                            "rtt_ms": rtt_ms,
                        },
                        target=sample.target,
                    )
            if sample.lost and detect_loss_burst(history):
                if should_fire("loss_burst", sample.target):
                    agg = lp.aggregate(sample.target)
                    loss_pct = round(agg.loss_pct or 0.0, 1)
                    logger.emit_loss_burst(LossBurstEvent(
                        timestamp=sample.ts,
                        target=sample.target,
                        target_ip=sample.target_ip,
                        loss_pct=loss_pct,
                        lost_in_window=sum(1 for s in history[-5:] if s.lost),
                    ))
                    await _notify(
                        {
                            "type": "loss_burst",
                            "target": sample.target,
                            "loss_pct": loss_pct,
                        },
                        target=sample.target,
                    )

    flush_task = (
        asyncio.create_task(
            _companion_runtime.flush_loop(companion_sink),
            name="companion-flush",
        )
        if companion_sink is not None
        else None
    )
    try:
        await wifi_consumer()
    finally:
        if flush_task is not None:
            flush_task.cancel()
            try:
                await flush_task
            except asyncio.CancelledError:
                pass
        if familiarity_store is not None:
            familiarity_store.flush()
        logger.close()


def _iso(ts: datetime) -> str:
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _arg_value(args: list[str], flag: str) -> str | None:
    """Pop ``--flag value`` from ``args`` in place; return the value or None."""
    for i, a in enumerate(args):
        if a == flag:
            if i + 1 < len(args):
                value = args[i + 1]
                del args[i:i + 2]
                return value
            del args[i]
            return None
        if a.startswith(flag + "="):
            value = a.split("=", 1)[1]
            del args[i]
            return value
    return None


# ---------- calibrate ----------

async def _run_calibrate(args: list[str]) -> None:
    """Record ``duration_s`` of RSSI samples per visible BSSID and
    persist the result to ``./diting-baseline.json``.

    Used by EnvironmentMonitor to override the adaptive baseline
    with a fixed "empty-room" σ, which makes the ``stable`` /
    ``active`` / ``quiet`` qualifier on the diagnostic line
    meaningful.
    """
    duration_s = 300
    raw = _arg_value(args, "--duration")
    if raw is not None:
        try:
            duration_s = max(10, int(raw))
        except ValueError:
            print(f"--duration expects an integer (got {raw!r})", file=sys.stderr)
            sys.exit(2)

    backend = MacOSWiFiBackend()
    poller = WiFiPoller(backend)
    samples: dict[str, list[int]] = defaultdict(list)
    deadline = time.monotonic() + duration_s
    print(t("Calibrating environment baseline ({n}s remaining)...", n=duration_s),
          flush=True)
    last_print = time.monotonic()

    try:
        async for event in poller.events():
            if time.monotonic() >= deadline:
                break
            if isinstance(event, ConnectionUpdate):
                conn = event.connection
                if conn is not None and conn.bssid and conn.rssi_dbm is not None:
                    samples[conn.bssid.lower()].append(int(conn.rssi_dbm))
            elif isinstance(event, ScanUpdate):
                for r in event.results:
                    if r.bssid and r.rssi_dbm is not None:
                        samples[r.bssid.lower()].append(int(r.rssi_dbm))
            now = time.monotonic()
            if now - last_print >= 30:
                last_print = now
                remaining = max(0, int(deadline - now))
                print(t(
                    "Calibrating environment baseline ({n}s remaining)...",
                    n=remaining,
                ), flush=True)
    except (KeyboardInterrupt, asyncio.CancelledError):
        print(t("Calibration cancelled."))
        return

    if not samples:
        print(t("No samples captured — leave the radio on a single network and retry."))
        return
    path = write_calibration(samples)
    print(t("Baseline saved to {path}", path=path))


# ---------- analyze (rule-based JSONL log reader) ----------

def _run_analyze(args: list[str]) -> None:
    """Read JSONL log(s) and print rule-based insights.

    Accepts one or more paths (shell globs expand before this
    function sees them). With no path arg, picks the newest
    ``diting-*.jsonl`` in the current directory — convenient for
    "I just ran diting here, tell me what happened" without having
    to remember the timestamped filename.

    Optional `--since DURATION` (e.g. `--since 7d` / `--since 24h` /
    `--since 90m`) filters the merged event stream to events whose
    timestamp falls within the last DURATION before "now".
    """
    from . import analyze

    if "--help" in args or "-h" in args:
        print(_analyze_help(), end="")
        return
    paths: list[Path] = []
    since: timedelta | None = None
    for_llm: bool = False
    for_llm_outdir: Path | None = None
    anonymize: bool = False
    json_mode: bool = False
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--json":
            json_mode = True
            i += 1
            continue
        if a == "--since":
            if i + 1 >= len(args):
                print(t(
                    "diting analyze: --since requires a duration "
                    "argument (e.g. --since 7d)",
                ), file=sys.stderr)
                sys.exit(2)
            try:
                since = analyze.parse_since(args[i + 1])
            except ValueError as exc:
                print(t(
                    "diting analyze: invalid --since value: {exc}",
                    exc=str(exc),
                ), file=sys.stderr)
                sys.exit(2)
            i += 2
            continue
        if a.startswith("--since="):
            try:
                since = analyze.parse_since(a.split("=", 1)[1])
            except ValueError as exc:
                print(t(
                    "diting analyze: invalid --since value: {exc}",
                    exc=str(exc),
                ), file=sys.stderr)
                sys.exit(2)
            i += 1
            continue
        if a == "--for-llm":
            # Boolean only — the out-dir lives in -o / --out-dir, so a
            # bare `--for-llm <log>` no longer swallows the input log
            # (the old footgun: it became the out-dir and mkdir crashed).
            for_llm = True
            i += 1
            continue
        if a.startswith("--for-llm="):  # back-compat: --for-llm=DIR
            for_llm = True
            for_llm_outdir = Path(a.split("=", 1)[1]).expanduser()
            i += 1
            continue
        if a in ("-o", "--out-dir"):
            if i + 1 >= len(args):
                print(t(
                    "diting analyze: {flag} requires a directory argument",
                    flag=a,
                ), file=sys.stderr)
                sys.exit(2)
            for_llm_outdir = Path(args[i + 1]).expanduser()
            for_llm = True  # giving an out-dir means "write the bundle"
            i += 2
            continue
        if a.startswith("--out-dir="):
            for_llm_outdir = Path(a.split("=", 1)[1]).expanduser()
            for_llm = True
            i += 1
            continue
        if a == "--anonymize":
            anonymize = True
            i += 1
            continue
        if a.startswith("-"):
            print(t("diting analyze: unknown flag {flag!r}", flag=a),
                  file=sys.stderr)
            sys.exit(2)
        paths.append(Path(a).expanduser())
        i += 1

    if not paths:
        candidates = sorted(
            Path(".").glob("diting-*.jsonl"),
            key=lambda p: p.stat().st_mtime if p.exists() else 0,
            reverse=True,
        )
        if not candidates:
            print(t(
                "diting analyze: no log file given and no "
                "diting-*.jsonl found in the current directory.\n"
                "Pass a path: diting analyze ~/wifi-20260507.jsonl",
            ), file=sys.stderr)
            sys.exit(2)
        paths = [candidates[0]]

    missing = [p for p in paths if not p.is_file()]
    if missing:
        for p in missing:
            print(t("diting analyze: file not found: {path}",
                    path=str(p)), file=sys.stderr)
        sys.exit(2)

    all_events: list[dict] = []
    for p in paths:
        all_events.extend(analyze.parse_jsonl(p))
    all_events.sort(key=lambda e: e.get("ts", ""))

    if since is not None:
        all_events = analyze.filter_since(all_events, since)

    report = analyze.analyze(
        all_events,
        source_paths=[str(p) for p in paths],
        since=since,
    )

    # In --json mode the structured report is the stdout output; the LLM
    # bundle (if also requested) is still written, but its human summary
    # goes to stderr so stdout stays pure JSON. `chrome` is the stream
    # for any human prose.
    chrome = sys.stderr if json_mode else sys.stdout

    if for_llm:
        # Build the bundle: report.md + prompt.txt under outdir.
        if for_llm_outdir is None:
            ts = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
            for_llm_outdir = Path(f"diting-llm-{ts}")
        if for_llm_outdir.exists() and not for_llm_outdir.is_dir():
            print(t(
                "diting analyze: output path is not a directory: {path}",
                path=str(for_llm_outdir),
            ), file=sys.stderr)
            sys.exit(2)
        for_llm_outdir.mkdir(parents=True, exist_ok=True)
        anonymizer = analyze.Anonymizer() if anonymize else None
        md = analyze.render_markdown(report, anonymizer=anonymizer)
        prompt = analyze.build_llm_prompt(report)
        report_path = for_llm_outdir / "report.md"
        prompt_path = for_llm_outdir / "prompt.txt"
        report_path.write_text(md)
        prompt_path.write_text(prompt)
        report_size_kb = report_path.stat().st_size / 1024.0
        prompt_size_kb = prompt_path.stat().st_size / 1024.0
        print(t(
            "✓ wrote {path}  ({kb:.1f} KB{suffix})",
            path=str(report_path),
            kb=report_size_kb,
            suffix=", anonymized" if anonymize else "",
        ), file=chrome)
        print(t(
            "✓ wrote {path}  ({kb:.1f} KB)",
            path=str(prompt_path),
            kb=prompt_size_kb,
        ), file=chrome)
        print(file=chrome)
        print(t("to analyze with an LLM:"), file=chrome)
        print(t("  1. open https://claude.ai or chat.openai.com"), file=chrome)
        print(t("  2. drag-drop the report.md file into the chat"), file=chrome)
        print(t("  3. paste the contents of prompt.txt"), file=chrome)
        print(t("  4. submit"), file=chrome)
        if anonymizer is not None:
            mapping = anonymizer.mapping()
            if mapping:
                print(file=chrome)
                print(t(
                    "anonymization mapping "
                    "(keep this private — do NOT paste):",
                ), file=chrome)
                for handle, original in mapping:
                    print(f"  {handle} ↔ {original}", file=chrome)
        else:
            print(file=chrome)
            print(t(
                "(if you're pasting into a public LLM and want to "
                "scrub identifiers, re-run with --anonymize)",
            ), file=chrome)
        if not json_mode:
            return

    if json_mode:
        import json as _json
        print(_json.dumps(
            analyze.report_to_dict(report), ensure_ascii=False,
        ))
        return

    print(analyze.render(report), end="")


# ---------- entry ----------

def _usage() -> str:
    """The top-level `--help` text.

    CLI usage / help is English-only by design: it is developer- and
    agent-facing (CLI help and `--json` output are conventionally
    English), and a previous bilingual version had silently drifted to
    English-only. Runtime user-facing prose and error messages remain
    fully localized via ``t()``."""
    return (
        "usage: diting [GLOBAL OPTS] [SUBCOMMAND [SUBCOMMAND OPTS]]\n"
        "\n"
        "Default (no SUBCOMMAND): launch the TUI dashboard.\n"
        "\n"
        "Subcommands (run `diting SUBCOMMAND --help` for details):\n"
        "  once         print the current connection and exit  [--json]\n"
        "  watch        stream connection / scan / roam events  [--json]\n"
        "  monitor      headless JSONL events (long-runs / Home Assistant)\n"
        "                 flags: --out FILE  --notify  --gateway IP  --wan IP\n"
        "  calibrate    record an empty-room RSSI baseline (default 300 s)\n"
        "                 flags: --duration SECONDS\n"
        "  analyze      read a JSONL log, print rule-based insights  [--json]\n"
        "                 (newest diting-*.jsonl in cwd when no PATH given)\n"
        "                 flags: --since DUR · --anonymize ·\n"
        "                        --for-llm [-o DIR]  (write an LLM bundle;\n"
        "                        -o sets its dir, default diting-llm-<ts>/)\n"
        "\n"
        "Automation: once / watch / analyze accept --json for machine-\n"
        "readable output (JSON keys are stable English; chrome goes to\n"
        "stderr). monitor already streams JSONL. Exit codes: 0 ok · 1\n"
        "runtime error (incl. once when not associated) · 2 usage error.\n"
        "\n"
        "Global options:\n"
        "  --lang L                interface language: en or zh\n"
        "                          (env: DITING_LANG; else system locale)\n"
        "  --log [PATH]            also write JSONL while TUI runs; no path =\n"
        "                          ./diting-YYYYMMDD-HHMMSS.jsonl in cwd. Same\n"
        "                          schema as `diting monitor`; append-mode +\n"
        "                          line-flushed so events survive Ctrl+C\n"
        "                          (env: DITING_LOG=PATH or =auto)\n"
        "  --notify                raise OS banners on anomaly events while\n"
        "                          TUI runs (also accepted by `monitor`)\n"
        "  --no-companion          don't forward events to a paired phone this\n"
        "                          run — self-test without push spam (same as\n"
        "                          env DITING_COMPANION=0). Pairing is untouched\n"
        "  --scene SCENE           home / office / public / audit (default home)\n"
        "                          sets sensitivity defaults for the environment;\n"
        "                          tags JSONL session_meta + LLM bundle context\n"
        "                          (env: DITING_SCENE)\n"
        "  --ble-presence-gate D   override the scene's BLE presence gate.\n"
        "                          Anonymous BLE adverts must be observed for at\n"
        "                          least D (e.g. 5s, 30s, 2m) before emitting\n"
        "                          events; 0 disables the gate. Wins over scene\n"
        "                          default (home=5s / office=15s / public=30s /\n"
        "                          audit=0s). Named + connected peripherals\n"
        "                          bypass. (env: DITING_BLE_PRESENCE_GATE)\n"
        "  DITING_LAN_PROBE=0|1    override scene's LAN active-probe default.\n"
        "                          1 forces NBNS / SSDP / mDNS-meta probes on;\n"
        "                          0 forces them off. Scene defaults: home /\n"
        "                          office / audit on, public off. Public-scene\n"
        "                          one-shot consent (uppercase P in LAN view)\n"
        "                          ignores this var. Env-only.\n"
        "  DITING_LAN_UPNP_FETCH=0|1\n"
        "                          gate the optional HTTP fetch of UPnP LOCATION\n"
        "                          URLs (for friendlyName / modelName). Default\n"
        "                          1; M-SEARCH still runs when 0. Env-only.\n"
        "  --version, -V           print the running version and exit\n"
        "  -h, --help              show this message\n"
    )


def _once_help() -> str:
    return (
        "usage: diting once [--json]\n"
        "\n"
        "Print the current Wi-Fi connection snapshot and exit.\n"
        "\n"
        "  --json    emit one JSON object (backend, permission_state,\n"
        "            associated, connection) to stdout; keys are stable\n"
        "            English. Exit 0 associated, 1 not associated.\n"
        "\n"
        "Examples:\n"
        "  diting once\n"
        "  diting once --json | jq .connection.rssi_dbm\n"
    )


def _watch_help() -> str:
    return (
        "usage: diting watch [--json]\n"
        "\n"
        "Stream connection / scan / roam change-events until Ctrl+C.\n"
        "\n"
        "  --json    emit one JSON object per event, newline-delimited\n"
        "            (tailable); chrome goes to stderr so stdout is a\n"
        "            clean JSON line-stream.\n"
        "\n"
        "Examples:\n"
        "  diting watch\n"
        "  diting watch --json | jq -c 'select(.kind==\"roam\")'\n"
    )


def _analyze_help() -> str:
    return (
        "usage: diting analyze [PATH ...] [--since DUR] [--json]\n"
        "                      [--for-llm [-o DIR]] [--anonymize]\n"
        "\n"
        "Read a JSONL log and print rule-based insights. With no PATH,\n"
        "uses the newest diting-*.jsonl in the current directory.\n"
        "\n"
        "  --since DUR     keep only events within the last DUR (7d/24h/90m)\n"
        "  --json          emit the full report as one JSON object to stdout\n"
        "                  (stable English keys); chrome goes to stderr\n"
        "  --for-llm       write an LLM bundle (report.md + prompt.txt)\n"
        "  -o, --out-dir   bundle directory (default diting-llm-<timestamp>/);\n"
        "                  implies --for-llm\n"
        "  --anonymize     replace identifiers with stable handles in the bundle\n"
        "\n"
        "Examples:\n"
        "  diting analyze\n"
        "  diting analyze diting-20260608.jsonl --json | jq .insights\n"
        "  diting analyze *.jsonl --since 7d --for-llm -o /tmp/bundle\n"
    )


def _extract_lang_arg(argv: list[str]) -> str | None:
    """Pop ``--lang`` and its value from ``argv`` in place.

    Supports both ``--lang zh`` and ``--lang=zh`` forms. Returns the
    value, or ``None`` if the flag is absent. An invalid value triggers
    SystemExit so the caller does not have to repeat the validation.
    """
    for i, arg in enumerate(argv):
        if arg == "--lang":
            if i + 1 >= len(argv):
                print("--lang requires a value (en|zh)", file=sys.stderr)
                sys.exit(2)
            value = argv[i + 1]
            del argv[i:i + 2]
            return _validate_lang(value)
        if arg.startswith("--lang="):
            value = arg.split("=", 1)[1]
            del argv[i]
            return _validate_lang(value)
    return None


def _validate_lang(value: str) -> str:
    if value not in (i18n.EN, i18n.ZH):
        print(f"unknown language {value!r}; expected en or zh", file=sys.stderr)
        sys.exit(2)
    return value


# Sentinel for "user said --log but did not supply a path → use a
# timestamped default in the current directory". Distinct from None
# (flag absent) and from a regular path string.
_LOG_DEFAULT = object()

_KNOWN_SUBCOMMANDS = {
    "once", "watch", "monitor", "calibrate", "analyze", "analyse", "companion",
}


def _run_companion(argv: list[str]) -> None:
    """`diting companion {pair|status|unpair}` — manage mobile pairing.

    Companion modules are imported lazily so the crypto/QR dependencies
    do not load on the hot TUI / monitor path."""
    action = argv[0] if argv else "status"
    if action == "pair":
        _companion_pair(argv[1:])
    elif action == "status":
        _companion_status()
    elif action == "unpair":
        _companion_unpair()
    else:
        print(
            t("companion: unknown action {action!r} (use pair / status / unpair)",
              action=action) + "\n",
            file=sys.stderr,
        )
        sys.exit(2)


def _companion_relay_url(argv: list[str]) -> str:
    for i, a in enumerate(argv):
        if a == "--relay" and i + 1 < len(argv):
            return argv[i + 1]
        if a.startswith("--relay="):
            return a.split("=", 1)[1]
    env = os.environ.get("DITING_COMPANION_RELAY")
    if env:
        return env
    from . import companion
    return companion.DEFAULT_RELAY_URL


def _companion_pair(argv: list[str]) -> None:
    from .companion import state as cstate

    relay = _companion_relay_url(argv)
    existing = cstate.load_state()
    st = cstate.PairingState.generate(relay)
    path = st.save()
    if existing is not None:
        print(t("Replaced the existing pairing."))
    print(t("Companion pairing — scan this in diting-mobile:"))
    print()
    print(cstate.render_qr(st.qr_uri()))
    print(t("relay:   {url}", url=relay))
    print(t("channel: {channel}", channel=st.channel))
    print(t("Saved to {path} (git-ignored — keep it secret).", path=path))


def _companion_status() -> None:
    from .companion import state as cstate

    st = cstate.load_state()
    if st is None:
        print(t("Not paired. Run `diting companion pair` to begin."))
        return
    print(t("Paired — channel {channel}", channel=st.channel))
    print(t("relay:   {url}", url=st.relay_url))
    print(t("last sequence: {n}", n=st.last_seq))
    print(t("Forwarding runs while `diting` or `diting monitor` is active."))


def _companion_unpair() -> None:
    from .companion import state as cstate

    if cstate.clear_state():
        print(t("Unpaired."))
    else:
        print(t("Not paired; nothing to remove."))


def _extract_log_arg(argv: list[str]) -> str | object | None:
    """Pop ``--log`` and (optionally) its value from ``argv`` in place.

    Three return shapes:

    * ``None`` — flag absent.
    * ``_LOG_DEFAULT`` sentinel — flag present without an explicit
      value (``diting --log``, or ``--log`` followed by a
      subcommand / another flag). Caller resolves to a timestamped
      default file in the cwd.
    * ``str`` — explicit ``--log path`` or ``--log=path``.

    Heuristic for "is the next token a path or a subcommand": if it
    begins with ``-`` (another flag) or matches one of the known
    subcommands we recognise, treat ``--log`` as no-value. Anything
    else is taken as a path. This is the same trick argparse uses
    for ``nargs='?'`` and works for the cases the CLI actually
    sees.
    """
    for i, arg in enumerate(argv):
        if arg == "--log":
            nxt = argv[i + 1] if i + 1 < len(argv) else None
            takes_value = (
                nxt is not None
                and not nxt.startswith("-")
                and nxt not in _KNOWN_SUBCOMMANDS
            )
            if takes_value:
                value: str | object = argv[i + 1]
                del argv[i:i + 2]
            else:
                value = _LOG_DEFAULT
                del argv[i]
            return value
        if arg.startswith("--log="):
            value = arg.split("=", 1)[1]
            del argv[i]
            return value or _LOG_DEFAULT
    return None


def _default_log_path() -> str:
    """Filesystem-safe timestamped default in the current directory.

    Uses local time (the user reads filenames in their own
    timezone) and replaces colons with hyphens so the file works
    on macOS / Linux / case-insensitive shares without quoting.
    """
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"diting-{stamp}.jsonl"


def _resolve_log_path(cli_value: str | object | None) -> str | None:
    """Materialise the final log path string.

    Resolution order:
      1. CLI flag with explicit path → that path.
      2. CLI flag with no value (sentinel) → timestamped default.
      3. DITING_LOG env var matching ``auto`` (any case) →
         timestamped default. Useful in shells that do not pass
         positional flags easily (cron, launchd plist).
      4. DITING_LOG env var with a path → that path.
      5. Otherwise → None (logging disabled).

    A blank env var is treated as "off" so a parent shell can
    disable logging with ``DITING_LOG= diting`` even when
    the profile sets it globally.
    """
    if isinstance(cli_value, str) and cli_value:
        return cli_value
    if cli_value is _LOG_DEFAULT:
        return _default_log_path()
    env = (os.environ.get("DITING_LOG") or "").strip()
    if not env:
        return None
    if env.lower() == "auto":
        return _default_log_path()
    return env


def _extract_ble_presence_gate_arg(argv: list[str]) -> float | None:
    """Pop ``--ble-presence-gate <duration>`` from ``argv`` in place.

    Returns seconds (float), or ``None`` if the flag is absent (caller
    then falls back to ``DITING_BLE_PRESENCE_GATE`` env var, then to
    the BLEPoller default of 5.0 s).

    Accepts both ``--ble-presence-gate 5s`` and
    ``--ble-presence-gate=5s`` forms. Duration syntax is the same
    ``<int><unit>`` shape ``diting analyze --since`` accepts (``5s``,
    ``30s``, ``2m``, ``1h``); ``0`` (no unit) is also accepted as a
    shortcut for ``0s`` since "disable the gate" is a common ask.

    Invalid input triggers SystemExit so the caller does not have to
    repeat the validation.
    """
    from . import analyze
    raw: str | None = None
    for i, arg in enumerate(argv):
        if arg == "--ble-presence-gate":
            if i + 1 >= len(argv):
                print(t(
                    "--ble-presence-gate requires a duration "
                    "(e.g. --ble-presence-gate 5s)",
                ), file=sys.stderr)
                sys.exit(2)
            raw = argv[i + 1]
            del argv[i:i + 2]
            break
        if arg.startswith("--ble-presence-gate="):
            raw = arg.split("=", 1)[1]
            del argv[i]
            break
    if raw is None:
        return None
    if raw == "0":
        return 0.0
    try:
        return analyze.parse_since(raw).total_seconds()
    except ValueError as exc:
        print(t(
            "--ble-presence-gate: invalid duration {raw!r}: {exc}",
            raw=raw, exc=str(exc),
        ), file=sys.stderr)
        sys.exit(2)


def _gateway_mac_for_router_ip(router_ip: str | None) -> str | None:
    """Look up the gateway MAC by reading ``arp -an``. Used at scene
    resolution time to match a ``scenes.yaml`` `gateway_mac` entry.

    Best-effort: returns None if the ARP cache doesn't know the
    gateway (which is normal right after boot, before any traffic
    flows). The caller falls back to SSID-only matching.
    """
    if not router_ip:
        return None
    try:
        from .lan import _read_arp_cache
        for ip, mac, _iface in _read_arp_cache():
            if ip == router_ip:
                return mac
    except Exception:
        # ARP subprocess may fail (no permissions / no /usr/sbin/arp).
        # Scene resolution must not crash startup over this.
        return None
    return None


def _resolve_scene_at_startup(
    cli_value: str | None,
) -> tuple[str, str, str | None]:
    """Run the full 5-tier scene resolution at process startup.

    Returns ``(scene_name, scene_source, banner_text_or_none)``.
    Banner text is non-None only when scene was resolved by yaml or
    auto — explicit user choices (cli / env) are silent.

    Tiers, highest-priority first:

    1. CLI `--scene` flag.
    2. `DITING_SCENE` env var.
    3. `scenes.yaml` SSID / gateway_mac match.
    4. Auto-detect heuristic on the current connection.
    5. Default `home`.

    Steps 3-4 require a synchronous ``MacOSWiFiBackend.get_connection()``
    call. If no Wi-Fi is associated, both tiers are skipped and
    resolution falls straight to step 5.
    """
    from . import scene as _scene_mod
    # Step 1+2+5 — pure-function pass through scene.resolve_scene.
    scene_name, source = _scene_mod.resolve_scene(cli_value)
    if source != _scene_mod.SOURCE_DEFAULT:
        # cli or env decided; skip yaml + heuristic.
        return scene_name, source, None

    # Step 3+4: sync read of current Wi-Fi connection.
    try:
        from .macos_backend import MacOSWiFiBackend
        backend = MacOSWiFiBackend()
        connection = backend.get_connection()
    except Exception:
        # CoreWLAN unavailable (rare on a Mac) — fall to default.
        return scene_name, source, None
    if connection is None or not connection.ssid:
        # Step 5: no connection → home (default), no banner.
        return scene_name, source, None

    # Step 3: scenes.yaml lookup.
    from . import scenes_config
    registry = scenes_config.load_scenes_registry()
    gateway_mac = _gateway_mac_for_router_ip(
        getattr(connection, "router_ip", None),
    )
    hit = registry.lookup(ssid=connection.ssid, gateway_mac=gateway_mac)
    if hit is not None:
        match_key = (
            f"gateway MAC {hit.gateway_mac}" if hit.gateway_mac
            else f"\"{hit.ssid}\""
        )
        banner = t(
            "pinned scene: {scene} (matched {key} in scenes.yaml)",
            scene=t(hit.scene), key=match_key,
        )
        return hit.scene, _scene_mod.SOURCE_YAML, banner

    # Step 4: heuristic.
    bssid_count = 0
    try:
        # get_scan_results returns the most recent scan from the
        # CoreWLAN cache without forcing a fresh probe (it's the
        # synchronous read of `wifi.cachedScanResults()` in macOS).
        bssid_count = len(backend.get_scan_results() or [])
    except Exception:
        bssid_count = 0
    inferred, reason = _scene_mod.classify_environment(
        connection.security, bssid_count, connection.ssid,
    )
    banner = t(
        "auto-detected scene: {scene} ({reason})",
        scene=t(inferred), reason=reason,
    )
    return inferred, _scene_mod.SOURCE_AUTO, banner


def _emit_scene_banner(banner_text: str | None) -> None:
    """Print the resolution banner to stderr — unless suppressed.

    `DITING_SCENE_QUIET=1` silences the banner (for users / scripts
    that want clean startup). Source `cli` / `env` never produce a
    banner; this function is a no-op when `banner_text` is None.
    """
    if not banner_text:
        return
    if os.environ.get("DITING_SCENE_QUIET", "").strip():
        return
    print(banner_text, file=sys.stderr)


def _extract_scene_arg(argv: list[str]) -> str | None:
    """Pop ``--scene SCENE`` from ``argv`` in place.

    Returns the value, or ``None`` if the flag is absent (caller then
    falls back to ``DITING_SCENE`` env var, then to ``home`` default
    via :func:`diting.scene.resolve_scene`).

    Supports both ``--scene office`` and ``--scene=office`` forms.
    Invalid values trigger SystemExit so the caller does not have to
    repeat the validation.
    """
    from . import scene as _scene_mod
    raw: str | None = None
    for i, arg in enumerate(argv):
        if arg == "--scene":
            if i + 1 >= len(argv):
                print(t(
                    "--scene requires a value ({names})",
                    names=" / ".join(_scene_mod.valid_scenes()),
                ), file=sys.stderr)
                sys.exit(2)
            raw = argv[i + 1]
            del argv[i:i + 2]
            break
        if arg.startswith("--scene="):
            raw = arg.split("=", 1)[1]
            del argv[i]
            break
    if raw is None:
        return None
    if raw not in _scene_mod.valid_scenes():
        print(t(
            "unsupported scene: {raw!r}; must be one of {names}",
            raw=raw, names=" / ".join(_scene_mod.valid_scenes()),
        ), file=sys.stderr)
        sys.exit(2)
    return raw


def _resolve_ble_presence_gate(
    cli_value: float | None,
    scene_default: float = 5.0,
) -> float:
    """Pick the active presence-gate seconds:
    CLI value > DITING_BLE_PRESENCE_GATE env var > scene_default.

    ``scene_default`` is the value from
    ``scene_defaults(active_scene)["ble_presence_gate_s"]`` — the CLI
    layer resolves the scene first and passes that value in. With
    the four canonical scenes that resolves to home=5.0, office=15.0,
    public=30.0, audit=0.0; an explicit ``--ble-presence-gate D``
    overrides whichever scene is active. The scene name itself is
    independent — used by session_meta and the LLM prompt — even
    when the gate value comes from a flag override.

    A blank env var is treated as absent so a parent shell can leave
    the scene default in place with ``DITING_BLE_PRESENCE_GATE= diting``.
    """
    if cli_value is not None:
        return cli_value
    from . import analyze
    env = (os.environ.get("DITING_BLE_PRESENCE_GATE") or "").strip()
    if not env:
        return scene_default
    if env == "0":
        return 0.0
    try:
        return analyze.parse_since(env).total_seconds()
    except ValueError:
        # Env var with bad shape: warn once on stderr, fall back to
        # scene default rather than refusing to launch.
        print(t(
            "warning: DITING_BLE_PRESENCE_GATE={env!r} is not a "
            "valid duration; using scene default {default}s",
            env=env, default=scene_default,
        ), file=sys.stderr)
        return scene_default


def _resolve_lan_active_probe_with_warning(
    *,
    scene_default: bool,
) -> bool:
    """Resolve LAN active-probe flag at startup with stderr warning.

    Delegates the parse to ``lan_probes.resolve_lan_active_probe``;
    additionally prints a single stderr warning when
    ``DITING_LAN_PROBE`` is set to a non-empty value other than
    ``0`` or ``1``, then falls through to the scene default. Blank
    env var is treated as absent and is NOT a warning condition.
    """
    from . import lan_probes as _lan_probes

    raw = os.environ.get("DITING_LAN_PROBE")
    if raw is not None:
        stripped = raw.strip()
        if stripped not in ("", "0", "1"):
            print(t(
                "warning: DITING_LAN_PROBE={raw!r} is not '0' or '1'; "
                "using scene default ({default})",
                raw=raw, default="on" if scene_default else "off",
            ), file=sys.stderr)
    return _lan_probes.resolve_lan_active_probe(
        scene_default=scene_default,
    )


def _extract_notify_arg(argv: list[str]) -> bool:
    """Pop ``--notify`` from ``argv`` in place; return True if present.

    Boolean flag; takes no value. Recognised on the default TUI
    subcommand (where this is called from main()) and on the
    ``monitor`` subcommand (parsed inside ``_run_monitor`` via the
    legacy ``"--notify" in args`` pattern, which keeps working
    because we only strip the flag from the default-subcommand
    path).
    """
    for i, arg in enumerate(argv):
        if arg == "--notify":
            del argv[i]
            return True
    return False


def _extract_no_companion_arg(argv: list[str]) -> bool:
    """Pop ``--no-companion`` from ``argv`` in place; return True if present.

    When present, disable companion forwarding for this process by setting
    ``DITING_COMPANION=0`` so :func:`companion.runtime.build_sink` returns
    None — the TUI / monitor runs normally but never offers events to the
    relay. For self-testing against a paired phone without push spam;
    pairing state on disk is untouched. Applies to both the default TUI
    subcommand and ``monitor`` (the env is read at sink-build time).
    """
    for i, arg in enumerate(argv):
        if arg == "--no-companion":
            del argv[i]
            os.environ["DITING_COMPANION"] = "0"
            return True
    return False


def _run_tui(
    *,
    log_path: str | None = None,
    notify: bool = False,
    ble_presence_gate_s: float = 5.0,
    scene: str = "home",
    scene_source: str = "default",
    lan_active_probe: bool = True,
    lan_upnp_fetch: bool = True,
) -> None:
    # Imported lazily so `diting once` and `diting watch` do not
    # pull in textual / rich on every invocation.
    from .tui import DitingApp

    # _ensure_helper_ready resolves the binary path AND, when the
    # detected helper predates 0.5.0 (no `ble-scan` subcommand),
    # falls back to a freshly-built in-repo bundle. We pass the
    # path it returns through so the BLE poller does not re-pick
    # whichever stale older copy find_helper() may still see.
    ble_binary = _ensure_helper_ready()
    abs_log_path = os.path.abspath(log_path) if log_path else None
    if abs_log_path:
        # Surface the resolved path BEFORE entering the alt-screen
        # so the user can see where their data is going. Especially
        # useful for the timestamped default case where the user
        # passed --log without a value and won't otherwise know the
        # filename.
        print(t("note: writing JSONL events to {path}", path=abs_log_path))
    backend = MacOSWiFiBackend()
    inv = load_inventory()
    DitingApp(
        backend, inv,
        scan_interval=_scan_interval(),
        ble_helper_path=ble_binary,
        ble_presence_gate_s=ble_presence_gate_s,
        scene=scene,
        scene_source=scene_source,
        event_log_path=log_path,
        notify=notify,
        lan_active_probe=lan_active_probe,
        lan_upnp_fetch=lan_upnp_fetch,
        familiarity_store_path=str(_familiarity.default_store_path()),
    ).run()
    # Post-exit hint pointing at the analyze command. Prints AFTER
    # the alt-screen tears down so the user sees it on the same
    # terminal scroll-back where they read the start-up note. We
    # only print when a log was actually written; otherwise the
    # hint would suggest analysing an empty path.
    if abs_log_path and os.path.isfile(abs_log_path):
        print()
        print(t(
            "tip: summarise this session with\n"
            "       diting analyze {path}",
            path=abs_log_path,
        ))


def _scan_interval() -> float:
    """Resolve scan interval from the DITING_SCAN_INTERVAL env var.

    Default is 7 s, which empirically sits above CoreWLAN's ~5 s
    throttle window — going below it just produces alternating empty
    scans (silent because of the panel's last-non-empty cache, but
    wasteful). Hard floor 3 s is the documented absolute minimum from
    the platform; smaller values are clamped.
    """
    import os
    raw = os.environ.get("DITING_SCAN_INTERVAL")
    if not raw:
        return 7.0
    try:
        return max(3.0, float(raw))
    except ValueError:
        return 7.0


def _ensure_helper_ready() -> str | None:
    """Ensure the Swift helper exists, supports the BLE subcommand, and
    has Location Services permission before the TUI launches.

    Steps, each silent unless something needs the user's attention:

    1. Locate the helper. Build it from `helper/build.sh` if not found
       and the Swift toolchain is available (works for the editable /
       cloned install, where the source ships next to the package).
    2. Detect a stale 0.4.0-era bundle (no `ble-scan` subcommand) and
       prefer a freshly-built in-repo helper instead, so the BLE
       poller does not silently die against an old binary that only
       answers ``scan``.
    3. Probe Location Services with a one-shot ``scan`` call. If
       missing, ``open`` the .app so macOS shows the prompt, then
       poll every 2 s until permission lands.

    Returns the binary path that the caller should use for both Wi-Fi
    and BLE pollers, or ``None`` when no helper could be resolved
    (the TUI then runs with redacted scan rows / disabled BLE view).
    """
    import json as _json  # avoid import-cycle hint at module top
    from . import _helper

    binary = _helper.find_helper()
    if binary is None:
        binary = _helper.try_build()
    if binary is None:
        print(t(
            "note: diting-tianer not found and could not be built.\n"
            "      Scan list will be TCC-redacted. To fix, install the\n"
            "      Swift toolchain (Xcode CLT) and rerun, or build helper/\n"
            "      manually. See README's helper section."
        ))
        print()
        return None

    # 0.7.0 prefers the in-repo bundle, but a 0.4.0-era copy left in
    # /Applications by older docs is still a valid fallback target.
    # Such a bundle answers `scan` correctly but has no `ble-scan`
    # subcommand, so spawning it for the BLE poller dies with rc=64
    # and the panel wedges. Detect the staleness up front and rebuild
    # the in-repo bundle when available.
    if not _helper.has_ble_scan_subcommand(binary):
        bundle = _helper.bundle_path(binary)
        print(t(
            "note: installed helper at {bundle} predates 0.5.0 (no\n"
            "      ble-scan subcommand). The BLE view would wedge\n"
            "      forever. Rebuilding the in-repo helper to use\n"
            "      instead — replace the installed copy at your\n"
            "      convenience.",
            bundle=bundle or binary,
        ))
        rebuilt = _helper.try_build()
        if rebuilt is not None and _helper.has_ble_scan_subcommand(rebuilt):
            binary = rebuilt
            print(t("Using freshly-built helper at {path}.", path=binary))
        else:
            print(t(
                "warning: could not build a 0.5.0-capable helper. The\n"
                "         BLE view will show an 'incompatible helper'\n"
                "         placeholder; remove the old bundle from\n"
                "         /Applications and run `make helper` to fix."
            ))
        print()

    # Probe BOTH grants up front rather than letting the user discover
    # mid-session that the BLE view is dead. Each probe is independent
    # — granting one without the other is a real (and historically
    # common) state, so we report them per-permission rather than as
    # a single boolean.
    #
    # The probes are wrapped in a startup splash so the multi-second
    # CoreWLAN + CoreBluetooth blocking work is *legible* to the user
    # rather than reading as a frozen terminal. The splash adds no
    # measurable latency vs the bare probes; see `splash.py`.
    from . import splash as _splash
    helper_label = t("helper located")
    location_label = t("checking Location Services")
    bluetooth_label = t("checking Bluetooth")
    steps = [
        # Step 1 is a confirmation that we already have the helper —
        # always succeeds at this point because the `find_helper` /
        # `try_build` / version-rebuild prose above returned the
        # binary path. Surfacing it as a step gives the splash three
        # rows to render instead of two, and confirms to the user
        # that the helper-locate phase already completed.
        (helper_label, lambda: True),
        (location_label, lambda: _helper.has_permission(binary)),
        (bluetooth_label, lambda: _helper.has_bluetooth_permission(binary)),
    ]
    probe_results = _splash.run_with_splash(steps)
    location_ok = probe_results[1]
    bluetooth_ok = probe_results[2]
    if location_ok and bluetooth_ok:
        return binary

    bundle = _helper.bundle_path(binary)
    if bundle is None:
        # Standalone binary outside a bundle — no UI to launch the
        # macOS prompts. The TUI will run but with degraded data
        # surfaces (redacted scan + empty BLE).
        print(t(
            "note: helper found but not in an .app bundle; cannot trigger\n"
            "      macOS permission prompts. Scan list will be redacted\n"
            "      and BLE view will be empty."
        ))
        print()
        return binary

    # Tell the user exactly which grants are missing so they know what
    # to expect when the bundle window opens.
    missing: list[str] = []
    if not location_ok:
        missing.append(t("Location Services (Wi-Fi scan list)"))
    if not bluetooth_ok:
        missing.append(t("Bluetooth (BLE devices view)"))
    print(t("Permissions required:"))
    for item in missing:
        print(f"  - {item}")
    print()
    print(t("Launching helper {bundle}", bundle=bundle))
    print(t("Click Allow on each macOS prompt that appears."))
    print(t("(Ctrl+C to skip and start the TUI with degraded views.)"))
    print()
    try:
        # `open --env KEY=VALUE` bridges our process env into the
        # LaunchServices-spawned bundle. Without this, the bundle would
        # inherit the user's login session env, which doesn't know
        # anything about diting's --lang flag, and the popup window
        # would show English even when the user is running
        # `diting --lang zh`. We pass DITING_LANG explicitly so the
        # Swift HelperAppDelegate's HelperStrings struct picks the
        # right localisation.
        #
        # `--args -AppleLanguages '(<tag>)'` additionally forces
        # Cocoa's NSUserDefaults for the launched process to pick
        # the matching `.lproj`, so the macOS TCC prompt headers
        # and prompt bodies render in the same language as the
        # status window. Without this, Bundle.preferredLocalizations
        # can disagree with Locale.preferredLanguages and the user
        # sees a mixed-language stack (the screenshot that motivated
        # the helper-install-flow-and-branding change).
        bundle_tag = "zh-Hans" if i18n.get_lang() == i18n.ZH else "en"
        open_argv = [
            "/usr/bin/open",
            "--env", f"DITING_LANG={i18n.get_lang()}",
            bundle,
            "--args", "-AppleLanguages", f"({bundle_tag})",
        ]
        subprocess.Popen(
            open_argv,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except OSError as e:
        print(t("  failed to open helper: {err}", err=e))
        return binary

    waited = 0.0
    interval = 2.0
    timeout = 180.0
    last_status: tuple[bool, bool] = (location_ok, bluetooth_ok)
    try:
        while waited < timeout:
            time.sleep(interval)
            waited += interval
            location_ok = _helper.has_permission(binary)
            bluetooth_ok = _helper.has_bluetooth_permission(binary)
            # Print a status line whenever something flips, so the user
            # gets feedback as each Allow lands rather than staring at
            # silent dots until the second grant arrives.
            current = (location_ok, bluetooth_ok)
            if current != last_status:
                last_status = current
                print()
                print(t(
                    "  Location: {loc}    Bluetooth: {bt}",
                    loc=t("granted") if location_ok else t("waiting"),
                    bt=t("granted") if bluetooth_ok else t("waiting"),
                ))
            if location_ok and bluetooth_ok:
                print(t("All permissions granted — starting TUI."))
                # Brief pause lets the helper window show its
                # confirmation message before auto-quitting.
                time.sleep(0.5)
                return binary
            sys.stdout.write(".")
            sys.stdout.flush()
        print()
        print(t(
            "(no full grant after {n}s; starting TUI anyway with whatever\n"
            " permissions did land. Rerun diting after granting to\n"
            " unlock the remaining views.)",
            n=int(timeout),
        ))
    except KeyboardInterrupt:
        print()
        print(t("Skipped; starting TUI with whatever permissions are in place."))
    return binary


def main() -> None:
    """Top-level entry — a safety net so an agent (or a frozen binary)
    never sees a Python traceback.

    Deliberate `SystemExit` codes propagate unchanged (usage = 2,
    runtime = 1, ok = 0); `KeyboardInterrupt` exits 130 quietly; any
    other uncaught exception becomes a single `diting: <message>` line
    on stderr (or a JSON error object under `--json`) and exits 1.
    `DITING_DEBUG=1` re-raises so developers still get the traceback.
    """
    try:
        _dispatch()
    except SystemExit:
        raise
    except KeyboardInterrupt:
        sys.exit(130)
    except BaseException as exc:  # noqa: BLE001 — top-level safety net
        if os.environ.get("DITING_DEBUG"):
            raise
        msg = str(exc) or exc.__class__.__name__
        if "--json" in sys.argv:
            import json as _json
            print(_json.dumps({"error": msg, "code": 1}), file=sys.stderr)
        else:
            print(f"diting: {msg}", file=sys.stderr)
        sys.exit(1)


def _dispatch() -> None:
    args = sys.argv[1:]
    # --version short-circuits before any locale / log / TUI work.
    # We deliberately do NOT pass it through to subcommand parsers;
    # `diting once --version` etc. are not supported.
    if "--version" in args or "-V" in args:
        from . import __version__
        print(f"diting {__version__}")
        return
    cli_lang = _extract_lang_arg(args)
    cli_log = _extract_log_arg(args)
    i18n.set_lang(i18n.resolve_lang(cli_lang))
    log_path = _resolve_log_path(cli_log)
    # `--notify` on the default TUI subcommand: strip the flag here so
    # an otherwise-empty argv falls into the default branch. We only
    # strip when no known subcommand follows — if the user wrote
    # `diting monitor --notify`, leave it in args for `_run_monitor`
    # to parse.
    has_subcommand = any(a in _KNOWN_SUBCOMMANDS for a in args)
    tui_notify = _extract_notify_arg(args) if not has_subcommand else False
    ble_gate_cli = (
        _extract_ble_presence_gate_arg(args) if not has_subcommand else None
    )
    # --scene is global — applies to the default TUI subcommand AND
    # to `monitor` (which writes session_meta to stdout / --out). We
    # extract it unconditionally so it gets stripped from args before
    # subcommand parsers see it, and so the resolved scene is set in
    # the scene module before any poller / logger touches it.
    scene_cli = _extract_scene_arg(args)
    # `--no-companion` is global (applies to the default TUI subcommand AND
    # `monitor`): strip it and set DITING_COMPANION=0 before any sink build,
    # so a self-test run never forwards to a paired phone.
    _extract_no_companion_arg(args)
    from . import scene as _scene_mod
    scene_name, scene_source, scene_banner = _resolve_scene_at_startup(
        scene_cli,
    )
    _scene_mod.set_scene(scene_name)
    _emit_scene_banner(scene_banner)
    scene_gate_default = _scene_mod.scene_defaults(scene_name).get(
        "ble_presence_gate_s", 5.0,
    )
    scene_lan_probe_default = _scene_mod.scene_defaults(scene_name).get(
        "lan_active_probe", True,
    )
    from . import lan_probes as _lan_probes
    lan_active_probe = _resolve_lan_active_probe_with_warning(
        scene_default=scene_lan_probe_default,
    )
    lan_upnp_fetch = _lan_probes.resolve_upnp_fetch_enabled()
    if not args:
        _run_tui(
            log_path=log_path,
            notify=tui_notify,
            ble_presence_gate_s=_resolve_ble_presence_gate(
                ble_gate_cli, scene_default=scene_gate_default,
            ),
            scene=scene_name,
            scene_source=scene_source,
            lan_active_probe=lan_active_probe,
            lan_upnp_fetch=lan_upnp_fetch,
        )
        return
    cmd = args[0]
    if cmd == "once":
        _run_once(args[1:])
        return
    if cmd == "watch":
        try:
            asyncio.run(_run_watch(args[1:]))
        except KeyboardInterrupt:
            pass
        return
    if cmd == "monitor":
        try:
            asyncio.run(_run_monitor(args[1:], scene_source=scene_source))
        except KeyboardInterrupt:
            pass
        return
    if cmd == "calibrate":
        try:
            asyncio.run(_run_calibrate(args[1:]))
        except KeyboardInterrupt:
            print(t("Calibration cancelled."))
        return
    if cmd == "analyze" or cmd == "analyse":
        _run_analyze(args[1:])
        return
    if cmd == "companion":
        _run_companion(args[1:])
        return
    if cmd in ("-h", "--help"):
        print(_usage(), end="")
        return
    print(t("diting: unknown subcommand {cmd!r}", cmd=cmd) + "\n",
          file=sys.stderr)
    print(_usage(), end="", file=sys.stderr)
    sys.exit(2)
