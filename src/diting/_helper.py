"""Discover and call the diting-tianer Swift sidecar.

The helper is a tiny `.app` bundle (sources at <repo>/helper/) that owns
Location Services permission and, when invoked as a subprocess with
`scan`, prints one JSON document of unredacted scan results. When the
helper is missing or unreachable, callers fall back to direct CoreWLAN
(which still works for RSSI / channel but leaves SSID / BSSID
redacted on macOS 26 without permission).

Search order for the bundle:

1. ``DITING_HELPER`` env var — full path to either the bundle or
   the binary inside it
2. ``<repo>/helper/diting-tianer.app`` — picks up a developer build
   without copying anywhere (pinned first so contributors running
   ``uv run diting`` from a checkout always pick up their freshly-
   ``make helper``ed bundle, even if they also have the one-line
   installer's copy in place)
3. ``/Applications/diting-tianer.app``
4. ``~/Applications/diting-tianer.app``
5. ``~/Library/Application Support/diting/diting-tianer.app`` —
   where the curl-bash one-line installer drops the bundle
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from .backend import AssociateResult
from .models import ScanResult

# Mirrors CoreWLAN enum values; the helper passes the raw integers
# straight through so we can decode them once on this side.
_BAND = {0: None, 1: "2.4 GHz", 2: "5 GHz", 3: "6 GHz"}
_WIDTH_MHZ = {0: None, 1: 20, 2: 40, 3: 80, 4: 160}
_SECURITY = {
    -1: None,
    0: "Open",
    1: "WEP",
    2: "WPA Personal",
    4: "WPA2 Personal",
    7: "WPA Enterprise",
    9: "WPA2 Enterprise",
    11: "WPA3 Personal",
    12: "WPA3 Enterprise",
}


def find_helper() -> str | None:
    """Return the path to a runnable diting-tianer binary, or None."""
    override = os.environ.get("DITING_HELPER")
    if override:
        return _resolve(Path(override).expanduser())
    candidates = [
        # In-place developer build inside this repo — the recommended
        # install location since 0.7.0. ``diting`` is typically
        # installed editable so __file__ traces back to the source
        # tree; ``build.sh`` produces the bundle here, the user grants
        # once with ``open helper/diting-tianer.app``, and we pick
        # it up automatically. Listed first so an old leftover bundle
        # in /Applications cannot shadow a freshly-rebuilt local one,
        # and so a contributor with both a repo checkout and the
        # one-line installer's drop in Application Support always
        # picks up the local rebuild.
        Path(__file__).resolve().parents[2] / "helper" / "diting-tianer.app",
        # Back-compat for users who moved the bundle into /Applications
        # before the in-place flow was recommended; still works.
        Path("/Applications/diting-tianer.app"),
        Path("~/Applications/diting-tianer.app").expanduser(),
        # Where the curl-bash one-line installer (``install.sh`` at
        # the repo root) drops the bundle. Last in the list so a dev
        # build always shadows the installer copy on contributor
        # machines that happen to have both.
        Path(
            "~/Library/Application Support/diting/diting-tianer.app"
        ).expanduser(),
    ]
    for c in candidates:
        resolved = _resolve(c)
        if resolved is not None:
            return resolved
    return None


def _resolve(path: Path) -> str | None:
    if path.is_file() and os.access(path, os.X_OK):
        return str(path)
    if path.suffix == ".app" and path.is_dir():
        binary = path / "Contents" / "MacOS" / "diting-tianer"
        if binary.is_file() and os.access(binary, os.X_OK):
            return str(binary)
    return None


def scan(binary: str, timeout: float = 12.0) -> tuple[list[ScanResult], dict]:
    """Run `<binary> scan` and decode the JSON payload.

    Returns ([], {}) if the helper exits non-zero or its output is
    malformed; callers can then fall back to a direct CoreWLAN scan.
    The second element is the interface metadata dict (may contain
    'name', 'country_code', 'hardware_address') from helper schema v2;
    schema v1 returned a plain string and is treated as missing meta.
    """
    try:
        proc = subprocess.run(
            [binary, "scan"],
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        return [], {}
    if proc.returncode != 0:
        return [], {}
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return [], {}
    iface_meta = payload.get("interface")
    if not isinstance(iface_meta, dict):
        iface_meta = {}
    nets = payload.get("networks") or []
    ts = datetime.now()
    out: list[ScanResult] = []
    for net in nets:
        bssid = net.get("bssid")
        if isinstance(bssid, str):
            bssid = bssid.lower() or None
        else:
            bssid = None
        out.append(
            ScanResult(
                ssid=net.get("ssid") or None,
                bssid=bssid,
                rssi_dbm=_or_none_zero(net.get("rssi_dbm")),
                noise_dbm=_or_none_zero(net.get("noise_dbm")),
                channel=net.get("channel"),
                channel_width_mhz=_WIDTH_MHZ.get(net.get("channel_width_raw") or 0),
                channel_band=_BAND.get(net.get("channel_band_raw") or 0),
                phy_mode=None,   # CWNetwork does not expose activePHYMode
                security=_SECURITY.get(net.get("security_raw", -1)),
                timestamp=ts,
                country_code=net.get("country_code") or None,
                bss_load_pct=_safe_int(net.get("bss_load_pct")),
                bss_station_count=_safe_int(net.get("bss_station_count")),
                supports_802_11r=_safe_bool(net.get("supports_802_11r")),
                supports_802_11k=_safe_bool(net.get("supports_802_11k")),
                supports_802_11v=_safe_bool(net.get("supports_802_11v")),
            )
        )
    return out, iface_meta


def _safe_int(value) -> int | None:
    """Pass through int values that fit a signed range, otherwise None.

    Defensive against malformed helper output (string instead of int,
    float, None) — we never want a typed Python field to surface a
    value the dataclass slot rejects with a downstream TypeError.
    """
    if isinstance(value, bool):
        # bool is a subclass of int; explicit check keeps a stray
        # `true` from being passed through as 1.
        return None
    if isinstance(value, int):
        return value
    return None


def _safe_bool(value) -> bool | None:
    """Boolean-or-None coercion. Anything other than a true bool
    (including 1, 0, "yes", None) becomes None so callers can rely on
    the field being a clean three-state."""
    if isinstance(value, bool):
        return value
    return None


def _or_none_zero(value):
    if value is None:
        return None
    v = int(value)
    return v if v != 0 else None


# ---------- one-shot setup helpers ----------

def has_permission(binary: str) -> bool:
    """Quick liveness check: did the helper return at least one BSSID?

    A redacted scan returns networks with all BSSIDs as None. Seeing
    even one populated BSSID proves Location Services is granted to
    the helper bundle.
    """
    try:
        proc = subprocess.run(
            [binary, "scan"], capture_output=True, timeout=12, check=False
        )
    except (subprocess.TimeoutExpired, OSError):
        return False
    if proc.returncode != 0:
        return False
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return False
    return any(net.get("bssid") for net in (data.get("networks") or []))


def has_bluetooth_permission(binary: str) -> bool:
    """Probe whether ``binary`` has Bluetooth TCC granted.

    Runs the helper's ``bluetooth-status`` subcommand, which exits 0
    only when ``CBCentralManager.state`` resolves to ``.poweredOn``.
    Every other outcome (``.unauthorized`` / ``.poweredOff`` /
    ``.unsupported`` / 2 s timeout / SIGABRT-on-TCC-violation) becomes
    a non-zero exit and we report False — the launcher then prompts
    the user via the GUI helper bundle.

    The timeout is 8 s here (the helper itself caps at 2 s on the
    state wait, plus disclaim re-spawn / process boot overhead).
    """
    try:
        proc = subprocess.run(
            [binary, "bluetooth-status"],
            capture_output=True, timeout=8, check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        return False
    return proc.returncode == 0


def has_ble_scan_subcommand(binary: str) -> bool:
    """Probe whether ``binary`` understands ``ble-scan``.

    A 0.4.0-era helper bundle that the user installed via the README's
    recommended ``mv diting-tianer.app /Applications/`` step will
    still be found by :func:`find_helper` after upgrading to 0.5.0 and
    happily answers the ``scan`` subcommand — but it has no
    ``ble-scan``, so spawning it for the BLE poller produces a silent
    rc=64 and the BLE panel wedges on "scanning…" forever. We probe by
    running ``--help`` (cheap, no permissions needed) and looking for
    the subcommand in the output. The 0.5.0+ helper lists ``ble-scan``
    in its --help text; older builds do not.
    """
    try:
        proc = subprocess.run(
            [binary, "--help"], capture_output=True, timeout=5, check=False
        )
    except (subprocess.TimeoutExpired, OSError):
        return False
    blob = (proc.stdout or b"") + (proc.stderr or b"")
    return b"ble-scan" in blob


def bundle_path(binary: str) -> str | None:
    """Resolve the .app directory enclosing a helper binary, or None."""
    p = Path(binary).resolve()
    for ancestor in [p, *p.parents]:
        if ancestor.suffix == ".app":
            return str(ancestor)
    return None


_ASSOCIATE_EXIT_TO_CODE: dict[int, str] = {
    5: "enterprise_unsupported",
    6: "cancelled",
    7: "auth_failed",
    8: "ssid_not_found",
}


def associate(
    binary: str,
    ssid: str,
    *,
    bssid: str | None = None,
    timeout: float = 90.0,
) -> AssociateResult:
    """Run `<binary> associate --ssid <SSID> [--bssid <BSSID>]` and
    decode the JSON status.

    Stdin is closed empty: this implementation only drives the
    helper's Keychain-or-AppKit-sheet path. A future caller that
    wants to pass a password in directly would extend this API
    with an explicit ``password`` kwarg piped on stdin — the
    helper already supports it.

    The timeout is generous (90 s) because the helper may sit on
    its AppKit password sheet waiting for the user. A subprocess
    crash, JSON-decode failure, or non-mapped exit code degrades
    to ``error_code="unknown"`` so callers always get an
    `AssociateResult`.
    """
    argv = [binary, "associate", "--ssid", ssid]
    if bssid:
        argv += ["--bssid", bssid]
    try:
        proc = subprocess.run(
            argv,
            input=b"",
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return AssociateResult(
            ok=False,
            error_code="unknown",
            error_message="helper timed out",
        )
    except OSError as exc:
        return AssociateResult(
            ok=False,
            error_code="unknown",
            error_message=str(exc),
        )
    payload: dict = {}
    if proc.stdout:
        try:
            decoded = json.loads(proc.stdout)
            if isinstance(decoded, dict):
                payload = decoded
        except json.JSONDecodeError:
            payload = {}
    if proc.returncode == 0 and payload.get("ok") is True:
        return AssociateResult(
            ok=True,
            bssid=(payload.get("bssid") or None),
            keychain_saved=bool(payload.get("keychain_saved")),
        )
    code = _ASSOCIATE_EXIT_TO_CODE.get(proc.returncode, "unknown")
    message = payload.get("error") if isinstance(payload.get("error"), str) else None
    if message is None and proc.stderr:
        message = proc.stderr.decode(errors="replace").strip() or None
    return AssociateResult(
        ok=False,
        error_code=code,  # type: ignore[arg-type]
        error_message=message,
    )


def try_build() -> str | None:
    """Run helper/build.sh if the source tree is reachable.

    Returns the binary path on success, None if Swift isn't installed,
    the source isn't reachable (e.g. diting was pip-installed without
    the Swift sources), or the build fails.
    """
    # Walk up from this module to find the repo root that ships the
    # `helper/` directory. diting is normally installed editable
    # via `uv sync`, so __file__ points inside the repo's src/.
    repo_root = Path(__file__).resolve().parents[2]
    helper_dir = repo_root / "helper"
    build_script = helper_dir / "build.sh"
    if not build_script.is_file():
        return None
    if shutil.which("swift") is None:
        return None
    try:
        subprocess.run(
            ["/bin/bash", str(build_script)],
            cwd=helper_dir, check=True,
            capture_output=True, timeout=300,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        return None
    return find_helper()
