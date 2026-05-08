"""Command-line entry point.

Subcommands:

    wifiscope             launch the TUI (default)
    wifiscope once        one-shot snapshot of the current connection
    wifiscope watch       streaming event log (Ctrl+C to quit)
    wifiscope monitor     headless JSONL events for long-runs / Home Assistant
    wifiscope calibrate   record an "empty room" RSSI baseline
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from . import i18n
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


def _run_once() -> None:
    backend = MacOSWiFiBackend()
    inv = load_inventory()
    conn = backend.get_connection()
    print(t("backend:    {name}", name=backend.name))
    if conn is None:
        print(t("status:     not associated"))
        sys.exit(1)
    print(t("timestamp:  {ts}", ts=conn.timestamp.isoformat(timespec="seconds")))
    print()
    _print_connection(conn, inv)
    state = backend.permission_state()
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


async def _run_watch() -> None:
    backend = MacOSWiFiBackend()
    inv = load_inventory()
    print(t("backend: {name}  (Ctrl+C to quit)", name=backend.name))
    if inv.aps or inv.radio_overrides:
        print(t(
            "inventory: {n_aps} APs, {n_overrides} overrides — {path}",
            n_aps=len(inv.aps),
            n_overrides=len(inv.radio_overrides),
            path=resolve_config_path(),
        ))
    perm = backend.permission_state()
    if perm == "denied":
        print()
        print(_denied_hint(), end="")
    elif perm == "fallback":
        print(_fallback_hint(), end="")
    print()

    poller = WiFiPoller(backend)
    state: dict = {"last_key": None, "last_rssi": None, "last_print_at": 0.0}

    async for event in poller.events():
        line = _render(event, state, inv)
        if line is not None:
            now_str = datetime.now().strftime("%H:%M:%S")
            print(f"{now_str}  {line}", flush=True)


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

async def _run_monitor(args: list[str]) -> None:
    """Long-running headless event stream.

    Spawns WiFiPoller + LatencyPoller + EnvironmentMonitor and emits
    one JSONL document per event to stdout (or ``--out path.jsonl``
    when set), with ``--notify`` raising a macOS Notification Centre
    alert for high-confidence events.
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

    async def maybe_notify(payload: dict) -> None:
        """Raise a macOS Notification Centre alert for high-confidence
        events. The logger handles the log line itself; this is the
        side-effect monitor adds on top."""
        if notify and payload.get("confidence") == "high":
            await _macos_notify(
                title="wifiscope",
                message=_notify_message(payload),
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
                    monitor.ingest(conn.bssid, conn.rssi_dbm, now)
                    for stir in monitor.fire_events(now):
                        logger.emit_rf_stir(stir)
                        await maybe_notify({
                            "type": "rf_stir",
                            "confidence": stir.confidence,
                            "location": stir.location,
                        })
            elif isinstance(event, ScanUpdate):
                for r in event.results:
                    if r.bssid is not None and r.rssi_dbm is not None:
                        monitor.ingest(r.bssid, r.rssi_dbm, now)
                for stir in monitor.fire_events(now):
                    logger.emit_rf_stir(stir)
                    await maybe_notify({
                        "type": "rf_stir",
                        "confidence": stir.confidence,
                        "location": stir.location,
                    })
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
                    logger.emit_latency_spike(LatencySpikeEvent(
                        timestamp=sample.ts,
                        target=sample.target,
                        target_ip=sample.target_ip,
                        rtt_ms=round(sample.rtt_ms or 0.0, 1),
                        loss_pct=round(agg.loss_pct or 0.0, 1),
                    ))
            if sample.lost and detect_loss_burst(history):
                if should_fire("loss_burst", sample.target):
                    agg = lp.aggregate(sample.target)
                    logger.emit_loss_burst(LossBurstEvent(
                        timestamp=sample.ts,
                        target=sample.target,
                        target_ip=sample.target_ip,
                        loss_pct=round(agg.loss_pct or 0.0, 1),
                        lost_in_window=sum(1 for s in history[-5:] if s.lost),
                    ))

    try:
        await wifi_consumer()
    finally:
        logger.close()


def _iso(ts: datetime) -> str:
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _notify_message(payload: dict) -> str:
    """Compose a short macOS notification body from an event dict."""
    kind = payload.get("type")
    if kind == "rf_stir":
        return (
            f"RF stir at {payload.get('location', '?')} — "
            f"σ {payload.get('magnitude_db', '?')} dB"
        )
    if kind == "latency_spike":
        return (
            f"Latency spike on {payload.get('target', '?')}: "
            f"{payload.get('rtt_ms', '?')} ms"
        )
    if kind == "loss_burst":
        return (
            f"Loss burst on {payload.get('target', '?')}: "
            f"{payload.get('loss_pct', '?')}%"
        )
    return f"event {kind}"


async def _macos_notify(*, title: str, message: str) -> None:
    """Fire ``osascript -e 'display notification ...'`` non-blocking."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "/usr/bin/osascript", "-e",
            f'display notification "{message}" with title "{title}"',
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()
    except (FileNotFoundError, OSError):
        pass


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
    persist the result to ``./wifiscope-baseline.json``.

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

def _run_selftest(args: list[str]) -> None:
    """TUI self-test runner. Drives the dashboard through a designed
    set of scenarios using Textual's pilot, captures one screenshot
    per state, and surfaces both regression assertions and product-
    opportunity findings.

    Usage::
        wifiscope selftest                       # all scenarios → ./selftest-output/
        wifiscope selftest --out-dir /tmp/x      # custom directory
        wifiscope selftest --scenarios id1,id2   # subset
        wifiscope selftest --json                # JSON to stdout (no console summary)
    """
    from . import selftest as _selftest

    out_dir_str = _arg_value(args, "--out-dir") or "selftest-output"
    out_dir = Path(out_dir_str).expanduser().resolve()
    scenarios_arg = _arg_value(args, "--scenarios")
    scenario_ids = (
        [s.strip() for s in scenarios_arg.split(",") if s.strip()]
        if scenarios_arg else None
    )
    json_only = "--json" in args

    report = _selftest.run(out_dir, scenario_ids=scenario_ids)

    # Write the JSON report alongside the screenshots regardless of
    # the --json flag so users have a structured record to grep
    # across runs.
    report_path = out_dir / "selftest-report.json"
    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    )

    if json_only:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(_selftest.render_console(report))
        print()
        print(t("note: full report at {path}", path=str(report_path)))


def _run_analyze(args: list[str]) -> None:
    """Read a JSONL log and print rule-based insights.

    With no arg, picks the newest ``wifiscope-*.jsonl`` in the
    current directory — convenient for "I just ran wifiscope here,
    tell me what happened" without having to remember the
    timestamped filename. Explicit path always wins.
    """
    from . import analyze

    if args:
        path = Path(args[0]).expanduser()
    else:
        candidates = sorted(
            Path(".").glob("wifiscope-*.jsonl"),
            key=lambda p: p.stat().st_mtime if p.exists() else 0,
            reverse=True,
        )
        if not candidates:
            print(t(
                "wifiscope analyze: no log file given and no "
                "wifiscope-*.jsonl found in the current directory.\n"
                "Pass a path: wifiscope analyze ~/wifi-20260507.jsonl",
            ), file=sys.stderr)
            sys.exit(2)
        path = candidates[0]

    if not path.is_file():
        print(t("wifiscope analyze: file not found: {path}",
                path=str(path)), file=sys.stderr)
        sys.exit(2)

    events = analyze.parse_jsonl(path)
    report = analyze.analyze(events, source_path=str(path))
    print(analyze.render(report), end="")


# ---------- entry ----------

def _usage() -> str:
    """Compose the --help text using the active language. Resolved at
    print time, not at module import, so ``--lang zh --help`` sees the
    Chinese version after :func:`main` has applied the language."""
    return t(
        "usage: wifiscope [--lang en|zh] [--log [PATH]] [SUBCOMMAND]\n"
        "\n"
        "  (no args)   launch the TUI dashboard (default)\n"
        "  once        print the current connection and exit\n"
        "  watch       stream events as plain text until Ctrl+C\n"
        "  monitor     headless JSONL events (long-runs / Home Assistant)\n"
        "              flags: --out FILE  --notify  --gateway IP  --wan IP\n"
        "  calibrate   record an empty-room RSSI baseline (default 300 s)\n"
        "              flags: --duration SECONDS\n"
        "  analyze     read a JSONL log and print rule-based insights.\n"
        "              With no PATH, uses the newest wifiscope-*.jsonl in cwd.\n"
        "  selftest    drive the TUI through designed scenarios + capture\n"
        "              screenshots + run inspector heuristics.\n"
        "              flags: --out-dir DIR  --scenarios id1,id2  --json\n"
        "  --lang L    interface language: en, zh. Defaults to WIFISCOPE_LANG,\n"
        "              then to the system locale (zh_* → zh, anything else → en).\n"
        "  --log[PATH] also write JSONL events while the TUI runs. With no\n"
        "              path, writes ./wifiscope-YYYYMMDD-HHMMSS.jsonl in cwd.\n"
        "              Same schema as `wifiscope monitor`; append-mode + line-\n"
        "              flushed so already-emitted events survive Ctrl+C / kill /\n"
        "              traceback. Env: WIFISCOPE_LOG=PATH (or =auto for default).\n"
        "  -h, --help  show this message\n"
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
    "once", "watch", "monitor", "calibrate", "analyze", "analyse",
    "selftest",
}


def _extract_log_arg(argv: list[str]) -> str | object | None:
    """Pop ``--log`` and (optionally) its value from ``argv`` in place.

    Three return shapes:

    * ``None`` — flag absent.
    * ``_LOG_DEFAULT`` sentinel — flag present without an explicit
      value (``wifiscope --log``, or ``--log`` followed by a
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
    return f"wifiscope-{stamp}.jsonl"


def _resolve_log_path(cli_value: str | object | None) -> str | None:
    """Materialise the final log path string.

    Resolution order:
      1. CLI flag with explicit path → that path.
      2. CLI flag with no value (sentinel) → timestamped default.
      3. WIFISCOPE_LOG env var matching ``auto`` (any case) →
         timestamped default. Useful in shells that do not pass
         positional flags easily (cron, launchd plist).
      4. WIFISCOPE_LOG env var with a path → that path.
      5. Otherwise → None (logging disabled).

    A blank env var is treated as "off" so a parent shell can
    disable logging with ``WIFISCOPE_LOG= wifiscope`` even when
    the profile sets it globally.
    """
    if isinstance(cli_value, str) and cli_value:
        return cli_value
    if cli_value is _LOG_DEFAULT:
        return _default_log_path()
    env = (os.environ.get("WIFISCOPE_LOG") or "").strip()
    if not env:
        return None
    if env.lower() == "auto":
        return _default_log_path()
    return env


def _run_tui(*, log_path: str | None = None) -> None:
    # Imported lazily so `wifiscope once` and `wifiscope watch` do not
    # pull in textual / rich on every invocation.
    from .tui import WifiScopeApp

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
    WifiScopeApp(
        backend, inv,
        scan_interval=_scan_interval(),
        ble_helper_path=ble_binary,
        event_log_path=log_path,
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
            "       wifiscope analyze {path}",
            path=abs_log_path,
        ))


def _scan_interval() -> float:
    """Resolve scan interval from the WIFISCOPE_SCAN_INTERVAL env var.

    Default is 7 s, which empirically sits above CoreWLAN's ~5 s
    throttle window — going below it just produces alternating empty
    scans (silent because of the panel's last-non-empty cache, but
    wasteful). Hard floor 3 s is the documented absolute minimum from
    the platform; smaller values are clamped.
    """
    import os
    raw = os.environ.get("WIFISCOPE_SCAN_INTERVAL")
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
            "note: wifiscope-helper not found and could not be built.\n"
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
    location_ok = _helper.has_permission(binary)
    bluetooth_ok = _helper.has_bluetooth_permission(binary)
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
        subprocess.Popen(
            ["/usr/bin/open", bundle],
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
            " permissions did land. Rerun wifiscope after granting to\n"
            " unlock the remaining views.)",
            n=int(timeout),
        ))
    except KeyboardInterrupt:
        print()
        print(t("Skipped; starting TUI with whatever permissions are in place."))
    return binary


def main() -> None:
    args = sys.argv[1:]
    cli_lang = _extract_lang_arg(args)
    cli_log = _extract_log_arg(args)
    i18n.set_lang(i18n.resolve_lang(cli_lang))
    log_path = _resolve_log_path(cli_log)
    if not args:
        _run_tui(log_path=log_path)
        return
    cmd = args[0]
    if cmd == "once":
        _run_once()
        return
    if cmd == "watch":
        try:
            asyncio.run(_run_watch())
        except KeyboardInterrupt:
            pass
        return
    if cmd == "monitor":
        try:
            asyncio.run(_run_monitor(args[1:]))
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
    if cmd == "selftest":
        _run_selftest(args[1:])
        return
    if cmd in ("-h", "--help"):
        print(_usage(), end="")
        return
    print(t("wifiscope: unknown subcommand {cmd!r}", cmd=cmd) + "\n",
          file=sys.stderr)
    print(_usage(), end="", file=sys.stderr)
    sys.exit(2)
