"""Command-line entry point.

The CLI is the agent-facing surface: every read command is JSON-first
(pure JSON on stdout, prose + errors on stderr) and exits cleanly.

    diting                 launch the TUI (default; human-facing)
    diting status          one-shot connection + permission snapshot
    diting scan            one-shot sensor snapshot (Wi-Fi and/or BLE)
    diting stream          headless canonical-JSONL event stream
    diting calibrate       record an "empty room" RSSI baseline
    diting analyze         post-process a JSONL log into a report
    diting companion       manage diting-mobile pairing
    diting capabilities    machine-readable manifest of the CLI surface

`once` / `watch` / `monitor` survive as deprecation aliases that forward
to `status` / `stream` / `stream` with a one-line stderr notice.
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
from .event_log import EventLogger
from .environment import write_calibration
from .i18n import t
from .macos_backend import MacOSWiFiBackend
from .models import Connection
from .network import (
    NetworkInventory,
    format_bssid,
    load_inventory,
)
from .poller import (
    ConnectionUpdate,
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


def _run_status(args: list[str] | None = None) -> None:
    args = args or []
    if "--help" in args or "-h" in args:
        print(_render_help("status"), end="")
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


# ---------- scan (one-shot sensor snapshot) ----------

def _scan_result_to_dict(r) -> dict:
    """Serialize a `ScanResult` to a JSON-safe dict (datetime → ISO)."""
    from dataclasses import asdict
    d = asdict(r)
    ts = d.get("timestamp")
    if hasattr(ts, "isoformat"):
        d["timestamp"] = ts.isoformat()
    return d


def _scan_wifi() -> list[dict]:
    """One-shot Wi-Fi scan via the Swift helper. Raises on hard failure
    (no helper) so the caller can shape a per-sensor structured error."""
    from . import _helper
    binary = _helper.find_helper()
    if binary is None:
        raise RuntimeError(
            "diting-tianer helper not found; cannot scan Wi-Fi"
        )
    results, _iface = _helper.scan(binary)
    return [_scan_result_to_dict(r) for r in results]


def _ble_device_to_dict(d, decode_all) -> dict:
    """JSON-safe view of a `BLEDevice` plus any decoded payload fields."""
    out: dict = {
        "identifier": d.identifier,
        "name": d.name,
        "vendor": d.vendor,
        "vendor_id": d.vendor_id,
        "rssi_dbm": d.rssi_dbm,
        "services": list(d.services),
        "type": d.type,
        "is_connected": d.is_connected,
        "first_seen": d.first_seen.isoformat() if d.first_seen else None,
        "last_seen": d.last_seen.isoformat() if d.last_seen else None,
    }
    try:
        decoded = decode_all(d)
    except Exception:
        decoded = None
    if decoded:
        out["decoded"] = decoded
    return out


async def _scan_ble(duration_s: float) -> list[dict]:
    """Collect BLE adverts for ``duration_s`` via the helper's ble-scan,
    then decode. Raises when the sensor is unreachable so the caller can
    shape a per-sensor structured error."""
    from . import _helper
    from .ble import BLEPoller
    from .decoders import decode_all
    binary = _helper.find_helper()
    if binary is None:
        raise RuntimeError(
            "diting-tianer helper not found; cannot scan BLE"
        )
    poller = BLEPoller(binary, presence_gate_s=0.0)
    latest: dict = {"devices": [], "perm": "unknown"}

    async def consume() -> None:
        async for update in poller.events():
            latest["perm"] = update.permission_state
            latest["devices"] = list(update.devices) + list(update.connected)

    task = asyncio.create_task(consume(), name="scan-ble")
    try:
        await asyncio.wait_for(task, timeout=max(0.5, duration_s))
    except asyncio.TimeoutError:
        pass  # task is cancelled by wait_for; we keep what we collected
    perm = latest["perm"]
    if perm in ("denied", "unavailable") and not latest["devices"]:
        raise RuntimeError(f"BLE unavailable (permission: {perm})")
    return [_ble_device_to_dict(d, decode_all) for d in latest["devices"]]


def _dataclass_snapshot_to_dict(obj) -> dict:
    """JSON-safe dict for a frozen snapshot dataclass (LANHost /
    BonjourDevice): `asdict` + top-level datetime → ISO-8601."""
    from dataclasses import asdict
    d = asdict(obj)
    for k, v in list(d.items()):
        if hasattr(v, "isoformat"):
            d[k] = v.isoformat()
    return d


async def _collect_latest(poller, attr: str, duration_s: float, *, name: str):
    """Drive ``poller.events()`` for ``duration_s`` and return the latest
    snapshot's ``attr`` list. Stops the poller afterwards."""
    latest: dict = {"items": []}

    async def consume() -> None:
        async for update in poller.events():
            latest["items"] = list(getattr(update, attr))

    task = asyncio.create_task(consume(), name=name)
    try:
        await asyncio.wait_for(task, timeout=max(0.5, duration_s))
    except asyncio.TimeoutError:
        pass
    finally:
        try:
            poller.stop()
        except Exception:  # noqa: BLE001
            pass
    return latest["items"]


async def _scan_lan(duration_s: float) -> list[dict]:
    """One-shot LAN host snapshot. Raises when the host is not associated
    (no subnet to enumerate)."""
    from .lan import LANInventoryPoller
    try:
        conn = MacOSWiFiBackend().get_connection()
    except Exception:
        conn = None
    if conn is None or not conn.router_ip:
        raise RuntimeError("not associated; cannot enumerate the LAN")
    poller = LANInventoryPoller(connection_provider=lambda: conn)
    hosts = await _collect_latest(poller, "hosts", duration_s, name="scan-lan")
    return [_dataclass_snapshot_to_dict(h) for h in hosts]


async def _scan_mdns(duration_s: float) -> list[dict]:
    """One-shot mDNS/Bonjour service snapshot."""
    from .mdns import BonjourPoller
    poller = BonjourPoller()
    devices = await _collect_latest(poller, "devices", duration_s, name="scan-mdns")
    return [_dataclass_snapshot_to_dict(d) for d in devices]


async def _run_scan(args: list[str]) -> None:
    if "--help" in args or "-h" in args:
        print(_render_help("scan"), end="")
        return
    json_mode = "--json" in args
    want_wifi = "--wifi" in args
    want_ble = "--ble" in args
    want_lan = "--lan" in args
    want_mdns = "--mdns" in args
    if not any((want_wifi, want_ble, want_lan, want_mdns)):
        # Default to the always-available pair; LAN/mDNS are opt-in (slower,
        # and LAN may active-probe).
        want_wifi = want_ble = True
    duration_s = 4.0
    raw = _arg_value(args, "--duration")
    if raw is not None:
        try:
            duration_s = _parse_duration_seconds(raw)
        except ValueError as exc:
            print(t("diting scan: invalid --duration value: {exc}", exc=str(exc)),
                  file=sys.stderr)
            sys.exit(2)

    result: dict = {}
    any_ok = False
    if want_wifi:
        try:
            result["wifi"] = _scan_wifi()
            any_ok = True
        except Exception as exc:  # noqa: BLE001 — per-sensor structured error
            result["wifi"] = {"error": str(exc), "code": 1}
    if want_ble:
        try:
            result["ble"] = await _scan_ble(duration_s)
            any_ok = True
        except Exception as exc:  # noqa: BLE001 — per-sensor structured error
            result["ble"] = {"error": str(exc), "code": 1}
    if want_lan:
        try:
            result["lan"] = await _scan_lan(duration_s)
            any_ok = True
        except Exception as exc:  # noqa: BLE001 — per-sensor structured error
            result["lan"] = {"error": str(exc), "code": 1}
    if want_mdns:
        try:
            result["mdns"] = await _scan_mdns(duration_s)
            any_ok = True
        except Exception as exc:  # noqa: BLE001 — per-sensor structured error
            result["mdns"] = {"error": str(exc), "code": 1}

    if json_mode:
        print(json.dumps(result, ensure_ascii=False))
    else:
        chrome = sys.stdout
        for sensor in ("wifi", "ble", "lan", "mdns"):
            if sensor not in result:
                continue
            val = result[sensor]
            print(f"== {sensor} ==", file=chrome)
            if isinstance(val, dict) and "error" in val:
                print(t("  error: {msg}", msg=val["error"]), file=chrome)
            else:
                print(t("  {n} result(s)", n=len(val)), file=chrome)
                for row in val:
                    label = (
                        row.get("ssid") or row.get("name")
                        or row.get("hostname") or row.get("ip")
                        or row.get("identifier") or "?"
                    )
                    rssi = row.get("rssi_dbm")
                    suffix = f"  {_fmt(rssi, ' dBm')}" if "rssi_dbm" in row else ""
                    print(f"  {label}{suffix}", file=chrome)
    sys.exit(0 if any_ok else 1)


# ---------- capabilities (machine-readable manifest) ----------

def _run_capabilities(args: list[str]) -> None:
    if "--help" in args or "-h" in args:
        print(_render_help("capabilities"), end="")
        return
    manifest = _capabilities_manifest()
    if "--json" in args:
        print(json.dumps(manifest, ensure_ascii=False))
        return
    # Pretty form — the same data, human-readable.
    print(f"diting capabilities (schema_version {manifest['schema_version']})")
    print()
    print("exit codes: " + " · ".join(
        f"{k} {v}" for k, v in manifest["exit_code_convention"].items()
    ))
    if manifest["deprecated_aliases"]:
        print("deprecated aliases: " + ", ".join(
            f"{k} → {v}" for k, v in manifest["deprecated_aliases"].items()
        ))
    print()
    for c in manifest["commands"]:
        flags = " ".join(f["name"] for f in c["flags"])
        print(f"  {c['name']:<14} {c['summary']}")
        if flags:
            print(f"  {'':<14}   flags: {flags}  [output: {c['output']}]")


# ---------- stream (headless JSONL) ----------

async def _run_stream(
    args: list[str],
    *,
    scene_source: str = "default",
    ble_presence_gate_s: float = 5.0,
    lan_active_probe: bool = False,
    lan_upnp_fetch: bool = True,
) -> None:
    """Long-running headless event stream, driven by `CaptureEngine`.

    Emits canonical event-log JSONL to stdout (or ``--out path.jsonl``).
    ``--sensors`` selects which sensors the engine drives (default
    ``wifi,latency,rf``); ``--duration D`` bounds the run; ``--notify``
    raises macOS alerts. ``scene_source`` / the scene-derived gate + LAN
    knobs are threaded from ``main()`` so the engine wires the same
    sensitivity the TUI would.
    """
    if "--help" in args or "-h" in args:
        print(_render_help("stream"), end="")
        return
    out_path = _arg_value(args, "--out")
    notify = "--notify" in args
    gateway_override = _arg_value(args, "--gateway")
    wan_override = _arg_value(args, "--wan")
    duration_s: float | None = None
    raw = _arg_value(args, "--duration")
    if raw is not None:
        try:
            duration_s = _parse_duration_seconds(raw)
        except ValueError as exc:
            print(t("diting stream: invalid --duration value: {exc}", exc=str(exc)),
                  file=sys.stderr)
            sys.exit(2)

    sensors = _parse_sensors(_arg_value(args, "--sensors"))

    from .capture import CaptureEngine

    backend = MacOSWiFiBackend()
    inv = load_inventory()
    logger = (
        EventLogger.to_path(out_path) if out_path
        else EventLogger.to_stdout()
    )
    # Resolve a BLE-capable helper only when BLE is actually requested, so
    # the common no-BLE stream never pays the lookup. find_helper() does not
    # trigger a LaunchServices permission prompt (that is the TUI's job).
    ble_helper_path: str | None = None
    if "ble" in sensors:
        from . import _helper
        cand = _helper.find_helper()
        if cand is not None and _helper.has_ble_scan_subcommand(cand):
            ble_helper_path = cand

    engine = CaptureEngine(
        backend, inv,
        logger=logger,
        sensors=sensors,
        scene_source=scene_source,
        ble_helper_path=ble_helper_path,
        ble_presence_gate_s=ble_presence_gate_s,
        lan_active_probe=lan_active_probe,
        lan_upnp_fetch=lan_upnp_fetch,
        scan_interval=_scan_interval(),
        gateway_override=gateway_override,
        wan_override=wan_override,
        notify=notify,
    )
    # Run the engine in a task so a SIGTERM (e.g. `diting capture stop`)
    # cancels it cleanly — the engine's teardown then flushes + closes the
    # logger, producing a COMPLETE capture rather than a truncated one.
    # SIGINT (Ctrl+C) is left to the default KeyboardInterrupt path.
    import signal as _signal
    loop = asyncio.get_running_loop()
    run_task = asyncio.create_task(engine.run(duration_s=duration_s))
    try:
        loop.add_signal_handler(_signal.SIGTERM, run_task.cancel)
    except (NotImplementedError, RuntimeError):
        pass  # signal handlers unavailable (non-main thread / platform)
    try:
        await run_task
    except asyncio.CancelledError:
        pass
    finally:
        try:
            loop.remove_signal_handler(_signal.SIGTERM)
        except (NotImplementedError, ValueError, RuntimeError):
            pass


def _parse_sensors(raw: str | None) -> set[str]:
    """Parse ``--sensors a,b,…`` into a set. ``all`` expands to every
    sensor; default (flag absent) is the historical ``wifi,latency,rf``.
    An unknown token is a usage error (exit 2)."""
    from .capture import ALL_SENSORS
    if raw is None:
        return {"wifi", "latency", "rf"}
    out: set[str] = set()
    for tok in raw.split(","):
        tok = tok.strip().lower()
        if not tok:
            continue
        if tok == "all":
            out.update(ALL_SENSORS)
            continue
        if tok not in ALL_SENSORS:
            print(t(
                "diting stream: unknown sensor {tok!r}; valid: {valid}",
                tok=tok, valid=", ".join((*ALL_SENSORS, "all")),
            ), file=sys.stderr)
            sys.exit(2)
        out.add(tok)
    return out or {"wifi", "latency", "rf"}

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
    if "--help" in args or "-h" in args:
        print(_render_help("calibrate"), end="")
        return
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

def _copy_to_clipboard(text: str) -> bool:
    """Put ``text`` on the macOS clipboard via ``pbcopy``. Returns True on
    success. Best-effort: if pbcopy is missing or fails (non-macOS, no GUI
    session), degrade silently — the written file is the fallback. Patched
    in tests so they never touch the real clipboard."""
    try:
        proc = subprocess.run(
            ["pbcopy"], input=text.encode("utf-8"),
            check=True, capture_output=True,
        )
        return proc.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


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
        print(_render_help("analyze"), end="")
        return
    paths: list[Path] = []
    since: timedelta | None = None
    for_llm: bool = False
    for_llm_outdir: Path | None = None
    anonymize: bool = False
    raw: bool = False
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
                    "diting analyze: {flag} requires a path argument",
                    flag=a,
                ), file=sys.stderr)
                sys.exit(2)
            for_llm_outdir = Path(args[i + 1]).expanduser()
            for_llm = True  # giving an output path means "write the file"
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
        if a == "--raw":
            raw = True
            for_llm = True  # --raw only makes sense with the briefing
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
        # One self-contained file (prompt + report) + clipboard by default,
        # so the workflow is: run → paste into any AI chat.
        ts = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
        default_name = f"diting-analysis-for-llm-{ts}.md"
        if for_llm_outdir is None:
            out_path = Path(default_name)
        elif for_llm_outdir.suffix == ".md":
            out_path = for_llm_outdir           # -o names the file
        elif for_llm_outdir.exists() and not for_llm_outdir.is_dir():
            # -o points at an existing non-.md file — ambiguous; don't
            # mkdir over it. (Use a .md suffix to name an output file.)
            print(t(
                "diting analyze: output path is not a directory: {path}",
                path=str(for_llm_outdir),
            ), file=sys.stderr)
            sys.exit(2)
        else:
            out_path = for_llm_outdir / default_name  # -o names a directory
        if out_path.exists() and out_path.is_dir():
            print(t(
                "diting analyze: output path is a directory: {path}",
                path=str(out_path),
            ), file=sys.stderr)
            sys.exit(2)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        anonymizer = analyze.Anonymizer() if anonymize else None
        doc = analyze.build_llm_document(
            report, anonymizer=anonymizer, raw_attached=raw,
        )
        out_path.write_text(doc)
        size_kb = out_path.stat().st_size / 1024.0
        # Skip clipboard under --json (an agent run shouldn't hijack the
        # human's clipboard). The mapping is never copied.
        copied = (not json_mode) and _copy_to_clipboard(doc)

        # --raw: the AI also gets the raw event log. Reference the user's
        # existing input file(s) — no rewrite — UNLESS --anonymize, where the
        # original carries real identifiers so we write a scrubbed copy that
        # reuses the briefing's handles (same anonymizer instance).
        raw_files: list[Path] = []
        if raw:
            if anonymizer is not None:
                raw_out = out_path.parent / f"diting-raw-anonymized-{ts}.jsonl"
                with raw_out.open("w") as fh:
                    for ev in all_events:
                        fh.write(json.dumps(
                            analyze.scrub_event(ev, anonymizer),
                            ensure_ascii=False,
                        ) + "\n")
                raw_files = [raw_out]
            else:
                raw_files = list(paths)

        print(t(
            "✓ wrote {path}  ({kb:.1f} KB{suffix})",
            path=str(out_path),
            kb=size_kb,
            suffix=t(", anonymized") if anonymize else "",
        ), file=chrome)
        if copied:
            print(t("✓ copied to clipboard"), file=chrome)
        print(file=chrome)
        print(t(
            "paste into any AI chat (it already has the prompt + the data):",
        ) if copied else t(
            "paste this file into any AI chat (it has the prompt + the data):",
        ), file=chrome)
        # Brand + URL lines are language-neutral — not run through t().
        print("  Claude    https://claude.ai", file=chrome)
        print("  ChatGPT   https://chat.openai.com", file=chrome)
        print("  DeepSeek  https://chat.deepseek.com", file=chrome)
        print("  Gemini    https://gemini.google.com", file=chrome)
        print("  Kimi      https://www.kimi.com", file=chrome)
        print(t("  … or any other capable chat — submit and read back."),
              file=chrome)
        if raw_files:
            print(file=chrome)
            print(t(
                "also attach the raw event log to the same chat "
                "(too big for the clipboard):",
            ), file=chrome)
            for rf in raw_files:
                kb = rf.stat().st_size / 1024.0
                print(f"  {rf}  ({kb:.0f} KB)", file=chrome)
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
        "  status        print the current connection snapshot and exit  [--json]\n"
        "  scan          one-shot Wi-Fi / BLE sensor snapshot  [--wifi --ble --json]\n"
        "  stream        headless canonical-JSONL event stream (long-runs)\n"
        "                  flags: --duration D  --out FILE  --notify  --gateway IP\n"
        "  calibrate     record an empty-room RSSI baseline (default 300 s)\n"
        "  analyze       read a JSONL log, print rule-based insights  [--json]\n"
        "                  (newest diting-*.jsonl in cwd when no PATH given)\n"
        "  companion     manage diting-mobile pairing (pair / status / unpair)\n"
        "  capabilities  machine-readable manifest of the CLI surface  [--json]\n"
        "\n"
        "Automation: status / scan / analyze / capabilities accept --json for\n"
        "machine-readable output (JSON keys are stable English; chrome goes to\n"
        "stderr); stream emits canonical JSONL. Run `diting capabilities --json`\n"
        "to discover the full surface. Exit codes: 0 ok · 1 runtime error (incl.\n"
        "status when not associated) · 2 usage error.\n"
        "Deprecated aliases: once → status · watch → stream · monitor → stream\n"
        "\n"
        "Global options:\n"
        "  --lang L                interface language: en or zh\n"
        "                          (env: DITING_LANG; else system locale)\n"
        "  --log [PATH]            also write JSONL while TUI runs; no path =\n"
        "                          ./diting-YYYYMMDD-HHMMSS.jsonl in cwd. Same\n"
        "                          schema as `diting stream`; append-mode +\n"
        "                          line-flushed so events survive Ctrl+C\n"
        "                          (env: DITING_LOG=PATH or =auto)\n"
        "  --notify                raise OS banners on anomaly events while\n"
        "                          TUI runs (also accepted by `stream`)\n"
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


# ---------- agent-facing command surface (single source of truth) ----------
#
# This declarative table backs BOTH the per-subcommand `--help` text and
# the `capabilities` manifest, so the two can never drift. Each flag's
# `type` is one of bool / duration / seconds / string / path; `output`
# is one of json-object / json-lines / text. Keep entries data-only —
# no behaviour lives here, just description.

CAPABILITIES_SCHEMA_VERSION = 1

# Deprecated verb → canonical verb. Forwarded with a one-line stderr
# notice, and advertised in the manifest's `deprecated_aliases`.
_DEPRECATED_ALIASES = {
    "once": "status",
    "watch": "stream",
    "monitor": "stream",
}
# Spelling alias — forwarded silently, not advertised in the manifest.
_SILENT_ALIASES = {"analyse": "analyze"}

_COMMANDS: list[dict] = [
    {
        "name": "status",
        "summary": "print the current connection + permission snapshot and exit",
        "output": "json-object",
        "flags": [
            {"name": "--json", "type": "bool", "default": False, "repeatable": False,
             "help": "emit one JSON object (backend, permission_state, associated, connection)"},
        ],
        "exit_codes": {"0": "associated", "1": "not associated", "2": "usage error"},
        "examples": ["diting status", "diting status --json | jq .connection.rssi_dbm"],
    },
    {
        "name": "scan",
        "summary": "one-shot sensor snapshot (Wi-Fi and/or BLE) and exit",
        "output": "json-object",
        "flags": [
            {"name": "--wifi", "type": "bool", "default": False, "repeatable": False,
             "help": "include the Wi-Fi scan list (default: both sensors)"},
            {"name": "--ble", "type": "bool", "default": False, "repeatable": False,
             "help": "include the BLE advertisement list (default: wifi+ble)"},
            {"name": "--lan", "type": "bool", "default": False, "repeatable": False,
             "help": "include a LAN host snapshot"},
            {"name": "--mdns", "type": "bool", "default": False, "repeatable": False,
             "help": "include an mDNS/Bonjour service snapshot"},
            {"name": "--duration", "type": "duration", "default": "4s", "repeatable": False,
             "help": "collection window for streaming sensors (Ns/Nm/Nh or bare seconds)"},
            {"name": "--json", "type": "bool", "default": False, "repeatable": False,
             "help": "emit one JSON object keyed by sensor (wifi, ble, lan, mdns)"},
        ],
        "exit_codes": {"0": "at least one sensor returned data",
                       "1": "no sensor returned data", "2": "usage error"},
        "examples": ["diting scan --json",
                     "diting scan --wifi --json | jq '.wifi | length'"],
    },
    {
        "name": "stream",
        "summary": "headless canonical-JSONL event stream (long-runs / pipelines)",
        "output": "json-lines",
        "flags": [
            {"name": "--sensors", "type": "string", "default": "wifi,latency,rf", "repeatable": False,
             "help": "comma list from wifi,latency,rf,ble,lan,mdns (or all); default wifi,latency,rf"},
            {"name": "--duration", "type": "duration", "default": None, "repeatable": False,
             "help": "bound the run (Ns/Nm/Nh or bare seconds); unbounded until Ctrl+C when omitted"},
            {"name": "--out", "type": "path", "default": None, "repeatable": False,
             "help": "write JSONL to FILE instead of stdout"},
            {"name": "--notify", "type": "bool", "default": False, "repeatable": False,
             "help": "raise macOS notifications on anomaly events"},
            {"name": "--gateway", "type": "string", "default": None, "repeatable": False,
             "help": "override the gateway IP for latency probing"},
            {"name": "--wan", "type": "string", "default": None, "repeatable": False,
             "help": "override the WAN target for latency probing"},
        ],
        "exit_codes": {"0": "clean exit", "2": "usage error"},
        "examples": ["diting stream | jq 'select(.type==\"roam\")'",
                     "diting stream --duration 5m --out /tmp/cap.jsonl"],
    },
    {
        "name": "calibrate",
        "summary": "record an empty-room RSSI baseline (default 300 s)",
        "output": "text",
        "flags": [
            {"name": "--duration", "type": "seconds", "default": "300", "repeatable": False,
             "help": "sampling window in seconds (minimum 10)"},
        ],
        "exit_codes": {"0": "baseline saved or cancelled", "2": "usage error"},
        "examples": ["diting calibrate --duration 120"],
    },
    {
        "name": "analyze",
        "summary": "read a JSONL log and print rule-based insights",
        "output": "json-object",
        "flags": [
            {"name": "--since", "type": "duration", "default": None, "repeatable": False,
             "help": "keep only events within the last DUR (7d/24h/90m)"},
            {"name": "--json", "type": "bool", "default": False, "repeatable": False,
             "help": "emit the full report as one JSON object to stdout"},
            {"name": "--for-llm", "type": "bool", "default": False, "repeatable": False,
             "help": "write ONE .md briefing (prompt + report) and copy it to the clipboard"},
            {"name": "--out-dir", "type": "path", "default": None, "repeatable": False,
             "help": "(-o) output .md file or directory for --for-llm; implies --for-llm"},
            {"name": "--anonymize", "type": "bool", "default": False, "repeatable": False,
             "help": "replace identifiers with stable handles in the briefing"},
            {"name": "--raw", "type": "bool", "default": False, "repeatable": False,
             "help": "also hand the AI the raw event log (implies --for-llm)"},
        ],
        "exit_codes": {"0": "report produced", "2": "usage error"},
        "examples": ["diting analyze",
                     "diting analyze diting-20260608.jsonl --json | jq .insights",
                     "diting analyze *.jsonl --since 7d --for-llm"],
    },
    {
        "name": "companion",
        "summary": "manage diting-mobile pairing (pair / status / unpair)",
        "output": "text",
        "flags": [
            {"name": "--relay", "type": "string", "default": None, "repeatable": False,
             "help": "relay URL for `companion pair` (env: DITING_COMPANION_RELAY)"},
        ],
        "exit_codes": {"0": "ok", "2": "unknown action"},
        "examples": ["diting companion pair", "diting companion status"],
    },
    {
        "name": "capture",
        "summary": "manage detached capture sessions (start / list / status / stop / tail)",
        "output": "text",
        "flags": [
            {"name": "--name", "type": "string", "default": None, "repeatable": False,
             "help": "session name (start / status / stop / tail)"},
            {"name": "--sensors", "type": "string", "default": None, "repeatable": False,
             "help": "sensors for the spawned stream (see `stream --sensors`)"},
            {"name": "--out", "type": "path", "default": None, "repeatable": False,
             "help": "capture file for start (default under the state dir)"},
            {"name": "--duration", "type": "duration", "default": None, "repeatable": False,
             "help": "bounded run for start (Ns/Nm/Nh)"},
            {"name": "--all", "type": "bool", "default": False, "repeatable": False,
             "help": "stop: stop every running session"},
            {"name": "-n", "type": "string", "default": "20", "repeatable": False,
             "help": "tail: number of lines"},
            {"name": "-f", "type": "bool", "default": False, "repeatable": False,
             "help": "tail: follow the capture"},
            {"name": "--json", "type": "bool", "default": False, "repeatable": False,
             "help": "machine-readable output for list / status / start"},
        ],
        "exit_codes": {"0": "ok", "1": "unknown session", "2": "usage error"},
        "examples": [
            "diting capture start --name nightwatch --sensors all",
            "diting capture list --json",
            "diting capture tail --name nightwatch -n 50 -f",
            "diting capture stop --name nightwatch",
        ],
    },
    {
        "name": "setup",
        "summary": "drive + verify the macOS TCC grants the helper needs",
        "output": "text",
        "flags": [
            {"name": "--json", "type": "bool", "default": False, "repeatable": False,
             "help": "probe once and emit a per-permission JSON state (non-blocking)"},
        ],
        "exit_codes": {"0": "required grants present", "1": "a required grant missing",
                       "2": "usage error"},
        "examples": ["diting setup", "diting setup --json | jq .ready"],
    },
    {
        "name": "capabilities",
        "summary": "emit a machine-readable manifest of the CLI surface",
        "output": "json-object",
        "flags": [
            {"name": "--json", "type": "bool", "default": False, "repeatable": False,
             "help": "emit the manifest as one JSON object (else pretty-print)"},
        ],
        "exit_codes": {"0": "ok"},
        "examples": ["diting capabilities --json | jq '.commands[].name'"],
    },
]

# Canonical verb names, in declared order.
_CANONICAL_VERBS = [c["name"] for c in _COMMANDS]


def _resolve_alias(cmd: str) -> str:
    """Map a subcommand token to its canonical verb. Deprecation and
    spelling aliases resolve; canonical / unknown tokens pass through."""
    return _DEPRECATED_ALIASES.get(cmd, _SILENT_ALIASES.get(cmd, cmd))


def _command(name: str) -> dict:
    for c in _COMMANDS:
        if c["name"] == name:
            return c
    raise KeyError(name)


def _parse_duration_seconds(raw: str) -> float:
    """Shared `--duration` / `--since` grammar: a bare `<int>` (seconds),
    or `<int>` suffixed with `s`/`m`/`h` (and `d`, inherited from the
    analyze grammar). Raises ValueError on anything else."""
    s = raw.strip()
    if s.isdigit():
        return float(int(s))
    from . import analyze
    return analyze.parse_since(s).total_seconds()


def _flag_usage(flag: dict) -> str:
    if flag["type"] == "bool":
        return f"[{flag['name']}]"
    placeholder = {
        "duration": "D", "seconds": "SECS", "path": "PATH",
    }.get(flag["type"], "VALUE")
    return f"[{flag['name']} {placeholder}]"


def _render_help(name: str) -> str:
    """Build a subcommand's `--help` text from its descriptor so help and
    the `capabilities` manifest stay in lock-step."""
    desc = _command(name)
    positional = " [PATH ...]" if name == "analyze" else ""
    usage_flags = " ".join(_flag_usage(f) for f in desc["flags"])
    lines = [
        f"usage: diting {name}{positional}"
        + (f" {usage_flags}" if usage_flags else ""),
        "",
        desc["summary"] + ".",
    ]
    if desc["flags"]:
        lines.append("")
        width = max(len(f["name"]) for f in desc["flags"])
        for f in desc["flags"]:
            lines.append(f"  {f['name']:<{width}}  {f['help']}")
    if desc.get("examples"):
        lines.append("")
        lines.append("Examples:")
        lines.extend(f"  {ex}" for ex in desc["examples"])
    lines.append("")
    lines.append("Exit codes: " + " · ".join(
        f"{k} {v}" for k, v in desc["exit_codes"].items()
    ))
    return "\n".join(lines) + "\n"


def _capabilities_manifest() -> dict:
    """The self-describing surface manifest. Built from `_COMMANDS` so it
    can never drift from actual parsing / help."""
    return {
        "schema_version": CAPABILITIES_SCHEMA_VERSION,
        "exit_code_convention": {
            "0": "success",
            "1": "runtime error",
            "2": "usage error",
        },
        "deprecated_aliases": dict(_DEPRECATED_ALIASES),
        "commands": [
            {
                "name": c["name"],
                "summary": c["summary"],
                "output": c["output"],
                "exit_codes": c["exit_codes"],
                "flags": [
                    {
                        "name": f["name"],
                        "type": f["type"],
                        "default": f["default"],
                        "repeatable": f["repeatable"],
                    }
                    for f in c["flags"]
                ],
            }
            for c in _COMMANDS
        ],
    }


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

# Every dispatchable subcommand token: canonical verbs + deprecation
# aliases + the spelling alias. Used to detect "is the next argv token a
# subcommand or a --log path" and to gate the default-TUI flag extraction.
_KNOWN_SUBCOMMANDS = (
    set(_CANONICAL_VERBS) | set(_DEPRECATED_ALIASES) | set(_SILENT_ALIASES)
)


def _run_companion(argv: list[str]) -> None:
    """`diting companion {pair|status|unpair}` — manage mobile pairing.

    Companion modules are imported lazily so the crypto/QR dependencies
    do not load on the hot TUI / stream path."""
    if argv and argv[0] in ("--help", "-h"):
        print(_render_help("companion"), end="")
        return
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
    print(t("Forwarding runs while `diting` or `diting stream` is active."))


def _companion_unpair() -> None:
    from .companion import state as cstate

    if cstate.clear_state():
        print(t("Unpaired."))
    else:
        print(t("Not paired; nothing to remove."))


# ---------- capture sessions ----------

def _run_capture(argv: list[str]) -> None:
    """`diting capture {start|list|status|stop|tail}` — manage detached
    capture sessions backed by the CaptureEngine."""
    if not argv or argv[0] in ("-h", "--help"):
        print(_render_help("capture"), end="")
        return
    from .sessions import SessionStore, SessionError

    action, rest = argv[0], argv[1:]
    store = SessionStore()
    json_mode = "--json" in rest

    if action == "start":
        name = _arg_value(rest, "--name")
        if not name:
            print(t("capture start: --name is required"), file=sys.stderr)
            sys.exit(2)
        try:
            rec = store.start(
                name=name,
                sensors=_arg_value(rest, "--sensors"),
                out=_arg_value(rest, "--out"),
                duration=_arg_value(rest, "--duration"),
            )
        except SessionError as exc:
            print(t("capture: {msg}", msg=str(exc)), file=sys.stderr)
            sys.exit(2)
        if json_mode:
            print(json.dumps(store.view(rec), ensure_ascii=False))
        else:
            print(t("started session {name} (pid {pid})",
                    name=rec["name"], pid=rec["pid"]))
            print(t("  capture: {path}", path=rec["capture_path"]))
        return

    if action == "list":
        views = [store.view(r) for r in store.list_records()]
        if json_mode:
            print(json.dumps(views, ensure_ascii=False))
        elif not views:
            print(t("(no capture sessions)"))
        else:
            for v in views:
                print(f"  {v['name']:<16} {v['status']:<8} "
                      f"pid={v.get('pid')}  {v['capture_path']}")
        return

    if action == "status":
        name = _arg_value(rest, "--name")
        if not name:
            print(t("capture status: --name is required"), file=sys.stderr)
            sys.exit(2)
        rec = store.read_record(name)
        if rec is None:
            msg = f"no such session {name!r}"
            if json_mode:
                print(json.dumps({"error": msg, "code": 1}), file=sys.stderr)
            else:
                print(t("capture: {msg}", msg=msg), file=sys.stderr)
            sys.exit(1)
        v = store.view(rec)
        if json_mode:
            print(json.dumps(v, ensure_ascii=False))
        else:
            for k in ("name", "status", "pid", "sensors",
                      "capture_path", "started_at", "duration"):
                print(f"  {k}: {v.get(k)}")
        return

    if action == "stop":
        if "--all" in rest:
            stopped = store.stop_all()
            if json_mode:
                print(json.dumps(
                    [{"name": n, "status": s} for n, s in stopped],
                    ensure_ascii=False,
                ))
            elif not stopped:
                print(t("(nothing running to stop)"))
            else:
                for n, _s in stopped:
                    print(t("stopped {name}", name=n))
            return
        name = _arg_value(rest, "--name")
        if not name:
            print(t("capture stop: --name or --all is required"), file=sys.stderr)
            sys.exit(2)
        try:
            result = store.stop(name)
        except SessionError as exc:
            print(t("capture: {msg}", msg=str(exc)), file=sys.stderr)
            sys.exit(1)
        if json_mode:
            print(json.dumps({"name": name, "status": result}, ensure_ascii=False))
        else:
            print(t("session {name}: {status}", name=name, status=result))
        return

    if action == "tail":
        name = _arg_value(rest, "--name")
        if not name:
            print(t("capture tail: --name is required"), file=sys.stderr)
            sys.exit(2)
        n = 20
        nraw = _arg_value(rest, "-n") or _arg_value(rest, "--lines")
        if nraw is not None:
            try:
                n = int(nraw)
            except ValueError:
                print(t("capture tail: -n expects an integer"), file=sys.stderr)
                sys.exit(2)
        try:
            lines = store.tail_lines(name, n)
        except SessionError as exc:
            print(t("capture: {msg}", msg=str(exc)), file=sys.stderr)
            sys.exit(1)
        for ln in lines:
            print(ln)
        if "-f" in rest or "--follow" in rest:
            _follow_capture(store, name)
        return

    print(t("capture: unknown action {action!r} "
            "(use start / list / status / stop / tail)", action=action) + "\n",
          file=sys.stderr)
    sys.exit(2)


# ---------- setup (drive + verify TCC grants) ----------

_SETUP_LABELS = {
    "location": "Location Services",
    "bluetooth": "Bluetooth",
    "notifications": "Notifications",
}


def _setup_state_json(state: dict) -> dict:
    from . import permission as _perm
    notif = state["notifications"]
    return {
        "location": _perm.is_authorized(state["location"]),
        "bluetooth": _perm.is_authorized(state["bluetooth"]),
        "notifications": None if notif is None else bool(notif),
        "ready": _perm.is_ready(state),
    }


def _setup_word(v) -> str:
    """Human status word for a grant value (status string for
    location/bluetooth; bool/None for notifications)."""
    from . import permission as _perm
    if _perm.is_authorized(v):
        return t("granted")
    if v is None or v == "unknown":
        return t("unknown")
    if v is False or _perm.is_denied(v):
        return t("not granted")
    return t("waiting")  # not_determined — the prompt is pending


def _print_setup_human(state: dict) -> None:
    for k in ("location", "bluetooth", "notifications"):
        print(f"  {_SETUP_LABELS[k]:<20} {_setup_word(state[k])}")


def _maybe_report_notifications(state: dict) -> None:
    n = state["notifications"]
    if n is True:
        return
    if n is None:
        print(t("note: Notifications grant could not be verified (older helper)."))
    else:
        print(t("note: Notifications not granted — `--notify` alerts stay silent "
                "until you enable it."))


def _route_denied_to_settings(key: str) -> None:
    from . import permission as _perm
    label = _SETUP_LABELS.get(key, key)
    _perm.open_settings_pane(key)
    print()
    print(t("{label} looks denied — macOS will not prompt again.", label=label))
    print(t("Opening System Settings → Privacy & Security → {label}.", label=label))
    print(t("Enable diting-tianer there, then re-run `diting setup`."))


def _run_setup(args: list[str]) -> None:
    """`diting setup` — drive + verify the macOS TCC grants the helper
    needs (Location / Bluetooth required, Notifications best-effort), so
    the user grants once instead of re-prompting at first launch."""
    if "--help" in args or "-h" in args:
        print(_render_help("setup"), end="")
        return
    from . import _helper
    from . import permission as _perm

    json_mode = "--json" in args
    noninteractive = (
        json_mode
        or not sys.stdout.isatty()
        or bool(os.environ.get("DITING_SETUP_NONINTERACTIVE"))
    )

    binary = _helper.find_helper() or _helper.try_build()
    if binary is None:
        msg = (
            "diting-tianer helper not found and could not be built; "
            "install it (see the README) or build helper/ with the Swift toolchain"
        )
        if json_mode:
            print(json.dumps({"error": msg, "code": 1}), file=sys.stderr)
        else:
            print(t("diting setup: {msg}", msg=msg), file=sys.stderr)
        sys.exit(1)

    # Detect which read-only status probes this helper supports ONCE, so
    # the verification poll uses non-prompting checks (no stacked prompts)
    # and doesn't re-grep `--help` every tick.
    caps = _perm.detect_caps(binary)
    state = _perm.probe(binary, caps=caps)

    # Non-interactive (non-TTY / CI / --json): probe once, report, no
    # bundle open, no blocking.
    if noninteractive:
        if json_mode:
            print(json.dumps(_setup_state_json(state), ensure_ascii=False))
            sys.exit(0)
        _print_setup_human(state)
        if not _perm.is_ready(state):
            print(t("Run `diting setup` in an interactive terminal to grant the "
                    "missing permissions."), file=sys.stderr)
        sys.exit(0 if _perm.is_ready(state) else 1)

    # Interactive drive-and-verify.
    if _helper.bundle_path(binary) is None:
        print(t("diting setup: the helper is not in an .app bundle, so the macOS "
                "prompts cannot be triggered. Reinstall the helper bundle."),
              file=sys.stderr)
        _print_setup_human(state)
        sys.exit(1)

    if _perm.is_ready(state):
        print(t("All required permissions are already granted."))
        _maybe_report_notifications(state)
        sys.exit(0)

    print(t("Setting up macOS permissions for diting's helper."))
    print(t("Click Allow on each prompt as it appears (one at a time)."))
    print(t("(Ctrl+C to stop.)"))
    print()
    _perm.open_bundle(binary, lang=i18n.get_lang())

    # Read-only probes are fast and prompt-free, so poll snappily.
    interval, timeout = 1.0, 180.0
    waited = 0.0
    opened_panes: set[str] = set()
    last = {k: state[k] for k in _perm.REQUIRED}
    try:
        while waited < timeout:
            time.sleep(interval)
            waited += interval
            state = _perm.probe(binary, caps=caps)
            current = {k: state[k] for k in _perm.REQUIRED}
            if current != last:
                print(t("  Location: {loc}    Bluetooth: {bt}",
                        loc=_setup_word(state["location"]),
                        bt=_setup_word(state["bluetooth"])))
                last = current
            if _perm.is_ready(state):
                print(t("✓ all required permissions granted."))
                _maybe_report_notifications(state)
                return
            # Route to Settings ONLY on a settled denial (macOS won't
            # re-prompt). A `not_determined` grant means the helper's prompt
            # is still pending — keep waiting for the user, don't mislabel it.
            for key in _perm.REQUIRED:
                if _perm.is_denied(state[key]) and key not in opened_panes:
                    opened_panes.add(key)
                    _route_denied_to_settings(key)
    except KeyboardInterrupt:
        print()
        print(t("Stopped. Re-run `diting setup` to finish granting."))
        sys.exit(1)
    print()
    print(t("Timed out waiting for grants. Current state:"))
    _print_setup_human(state)
    print(t("Re-run `diting setup` after granting, or use the System Settings "
            "steps above."))
    sys.exit(1)


def _follow_capture(store, name: str) -> None:
    """Poll the session's capture file and print newly-appended lines until
    interrupted (the `-f` follow path)."""
    rec = store.read_record(name)
    if rec is None:
        return
    path = Path(rec["capture_path"])
    pos = path.stat().st_size if path.is_file() else 0
    try:
        while True:
            if path.is_file():
                size = path.stat().st_size
                if size > pos:
                    with path.open() as fh:
                        fh.seek(pos)
                        chunk = fh.read()
                        pos = fh.tell()
                    for ln in chunk.splitlines():
                        if ln.strip():
                            print(ln, flush=True)
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass


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
    # The scene-detection banner is irrelevant noise for `setup` (the
    # install / permission flow) — suppress it so that output stays
    # focused on the grant steps.
    if not (args and _resolve_alias(args[0]) == "setup"):
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
    if cmd in ("-h", "--help"):
        print(_usage(), end="")
        return

    # Resolve deprecation / spelling aliases to a canonical verb. A
    # deprecated alias prints exactly one stderr notice (never stdout,
    # so `--json` stays pure); a spelling alias forwards silently.
    canonical = _resolve_alias(cmd)
    if cmd in _DEPRECATED_ALIASES:
        print(f"diting: {cmd!r} is deprecated; use {canonical!r}",
              file=sys.stderr)

    rest = args[1:]
    if canonical == "status":
        _run_status(rest)
        return
    if canonical == "scan":
        try:
            asyncio.run(_run_scan(rest))
        except KeyboardInterrupt:
            pass
        return
    if canonical == "stream":
        try:
            asyncio.run(_run_stream(
                rest,
                scene_source=scene_source,
                # Thread the scene-derived gate + LAN knobs so a full-sensor
                # capture honours the same sensitivity the TUI would. The BLE
                # gate resolves env > scene default (no per-stream CLI flag).
                ble_presence_gate_s=_resolve_ble_presence_gate(
                    None, scene_default=scene_gate_default,
                ),
                lan_active_probe=lan_active_probe,
                lan_upnp_fetch=lan_upnp_fetch,
            ))
        except KeyboardInterrupt:
            pass
        return
    if canonical == "calibrate":
        try:
            asyncio.run(_run_calibrate(rest))
        except KeyboardInterrupt:
            print(t("Calibration cancelled."))
        return
    if canonical == "analyze":
        _run_analyze(rest)
        return
    if canonical == "companion":
        _run_companion(rest)
        return
    if canonical == "capture":
        _run_capture(rest)
        return
    if canonical == "setup":
        _run_setup(rest)
        return
    if canonical == "capabilities":
        _run_capabilities(rest)
        return
    print(t("diting: unknown subcommand {cmd!r}", cmd=cmd) + "\n",
          file=sys.stderr)
    print(_usage(), end="", file=sys.stderr)
    sys.exit(2)
