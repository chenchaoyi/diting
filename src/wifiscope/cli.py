"""Command-line entry point.

Two modes (no argparse — keep step-6 surface minimal):

    wifiscope         one-shot snapshot of the current connection
    wifiscope watch   streaming event log (Ctrl+C to quit)

The TUI lands in step 8 and will replace `watch` as the default.
"""

from __future__ import annotations

import asyncio
import sys
import time
from datetime import datetime

from . import i18n
from .i18n import t
from .macos_backend import MacOSWiFiBackend
from .models import Connection
from .network import (
    NetworkInventory,
    band_label,
    format_bssid,
    load_inventory,
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


# ---------- entry ----------

def _usage() -> str:
    """Compose the --help text using the active language. Resolved at
    print time, not at module import, so ``--lang zh --help`` sees the
    Chinese version after :func:`main` has applied the language."""
    return t(
        "usage: wifiscope [--lang en|zh] [SUBCOMMAND]\n"
        "\n"
        "  (no args)   launch the TUI dashboard (default)\n"
        "  once        print the current connection and exit\n"
        "  watch       stream events as plain text until Ctrl+C\n"
        "  --lang L    interface language: en, zh. Defaults to WIFISCOPE_LANG,\n"
        "              then to the system locale (zh_* → zh, anything else → en).\n"
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


def _run_tui() -> None:
    # Imported lazily so `wifiscope once` and `wifiscope watch` do not
    # pull in textual / rich on every invocation.
    from .tui import WifiScopeApp

    _ensure_helper_ready()
    backend = MacOSWiFiBackend()
    inv = load_inventory()
    # Resolve the helper bundle's binary so the BLE poller can spawn
    # `wifiscope-helper ble-scan` directly. find_helper() returns the
    # same path the Wi-Fi scan path uses, so a single TCC grant covers
    # both.
    from . import _helper
    ble_binary = _helper.find_helper()
    WifiScopeApp(
        backend, inv,
        scan_interval=_scan_interval(),
        ble_helper_path=ble_binary,
    ).run()


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


def _ensure_helper_ready() -> None:
    """Ensure the Swift helper exists and has Location Services permission
    before the TUI launches.

    Steps, each silent unless something needs the user's attention:
    1. Locate the helper. Build it from `helper/build.sh` if not found
       and the Swift toolchain is available (works for the editable /
       cloned install, where the source ships next to the package).
    2. Probe permission with a one-shot helper scan.
    3. If permission is missing, `open` the .app so macOS shows its
       Location Services prompt, then poll every 2 s until permission
       lands. The helper's window auto-closes on grant. Ctrl+C skips
       the wait and the TUI launches with redacted scan rows — useful
       when the user wants to inspect cached state without granting.
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
        return

    if _helper.has_permission(binary):
        return

    bundle = _helper.bundle_path(binary)
    if bundle is None:
        # Standalone binary outside a bundle — no UI to launch.
        print(t(
            "note: helper found but not in an .app bundle; cannot trigger\n"
            "      Location Services prompt. Scan list will be redacted."
        ))
        print()
        return

    print(t("Launching helper {bundle}", bundle=bundle))
    print(t("to grant Location Services. Click Allow when macOS asks."))
    print(t("(Ctrl+C to skip and start the TUI with redacted scan rows.)"))
    print()
    try:
        subprocess.Popen(
            ["/usr/bin/open", bundle],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except OSError as e:
        print(t("  failed to open helper: {err}", err=e))
        return

    waited = 0.0
    interval = 2.0
    timeout = 120.0
    try:
        while waited < timeout:
            time.sleep(interval)
            waited += interval
            if _helper.has_permission(binary):
                print(t("Permission granted — starting TUI."))
                # Brief pause lets the helper window show its
                # confirmation message before auto-quitting.
                time.sleep(0.5)
                return
            sys.stdout.write(".")
            sys.stdout.flush()
        print()
        print(t(
            "(no grant after {n}s; starting TUI anyway.\n"
            " rerun wifiscope after granting to see unredacted scan.)",
            n=int(timeout),
        ))
    except KeyboardInterrupt:
        print()
        print(t("Skipped; starting TUI with redacted scan."))


def main() -> None:
    args = sys.argv[1:]
    cli_lang = _extract_lang_arg(args)
    i18n.set_lang(i18n.resolve_lang(cli_lang))
    if not args:
        _run_tui()
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
    if cmd in ("-h", "--help"):
        print(_usage(), end="")
        return
    print(t("wifiscope: unknown subcommand {cmd!r}", cmd=cmd) + "\n",
          file=sys.stderr)
    print(_usage(), end="", file=sys.stderr)
    sys.exit(2)
