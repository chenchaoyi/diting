"""macOS TCC permission primitives shared by `diting setup` and the
TUI's helper-readiness flow.

macOS TCC grants (Location, Bluetooth, Notifications) cannot be set
programmatically — the user must click "Allow" in the system dialog.
This module only DRIVES the prompts (by opening the helper bundle) and
VERIFIES the outcome (by probing the helper), plus routes a settled
denial to the right System Settings pane. It never claims to grant.
"""

from __future__ import annotations

import subprocess

from . import _helper

# Required grants gate core function; notifications is best-effort
# (only `--notify`). Order matches the helper's prompt sequence.
REQUIRED = ("location", "bluetooth")
OPTIONAL = ("notifications",)
ALL = REQUIRED + OPTIONAL

# System Settings → Privacy & Security pane anchors per permission.
_SETTINGS_PANE = {
    "location": "Privacy_LocationServices",
    "bluetooth": "Privacy_Bluetooth",
    "notifications": "Privacy_Notifications",
}


def detect_caps(binary: str) -> dict:
    """Which read-only status probes the (possibly older) helper supports.
    Detected once so the poll doesn't re-grep `--help` every tick."""
    return {
        "location_status": _helper.has_location_status_subcommand(binary),
        "bluetooth_auth": _helper.has_bluetooth_authorization_subcommand(binary),
        "notification_status": _helper.has_notification_status_subcommand(binary),
    }


def is_authorized(value) -> bool:
    """A grant value (status string, or bool/None for notifications) is
    granted when it is True or the `authorized` status."""
    return value is True or value == "authorized"


def probe(binary: str, *, caps: dict | None = None,
          settle: float | None = None) -> dict:
    """Probe each grant. `location`/`bluetooth` are STATUS strings —
    `authorized` / `denied` / `not_determined` / `restricted` / `unknown`
    — so the caller can tell a pending prompt from a settled denial.
    `notifications` is True/False, or None when the helper can't verify it.

    Prefers the READ-ONLY status probes (`location-status` /
    `bluetooth-authorization`) which never prompt, so a verification poll
    doesn't stack TCC prompts on the helper GUI's one-at-a-time flow.
    Falls back to the functional probes (`scan` / `bluetooth-status`,
    which DO prompt) only against an older helper that lacks them — those
    can't distinguish pending from denied, so they map to `authorized` /
    `unknown`.

    `settle` overrides the Location probe's registration-settle bound
    (seconds). `setup`'s prompt-launch pre-check passes a short value so a
    not-yet-granted system is recognized quickly and the helper window is
    not held back; leave None for the accurate default."""
    if caps is None:
        caps = detect_caps(binary)

    def _loc():
        return (
            _helper.location_status(binary, settle=settle) if caps["location_status"]
            else ("authorized" if _helper.has_permission(binary) else "unknown")
        )

    def _bt():
        return (
            _helper.bluetooth_authorization_status(binary) if caps["bluetooth_auth"]
            else ("authorized" if _helper.has_bluetooth_permission(binary) else "unknown")
        )

    def _notif():
        return (
            _helper.has_notification_permission(binary)
            if caps["notification_status"] else None
        )

    # Each probe is a separate disclaimed subprocess (~2 s of re-exec
    # overhead, and location waits up to its registration timeout), so run
    # the three concurrently — the poll's wall-clock becomes the slowest
    # single probe instead of their sum.
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=3) as pool:
        f_loc = pool.submit(_loc)
        f_bt = pool.submit(_bt)
        f_notif = pool.submit(_notif)
        return {
            "location": f_loc.result(),
            "bluetooth": f_bt.result(),
            "notifications": f_notif.result(),
        }


def is_ready(state: dict) -> bool:
    """All REQUIRED grants authorized (notifications is best-effort)."""
    return all(is_authorized(state.get(k)) for k in REQUIRED)


def is_denied(value) -> bool:
    """A settled refusal macOS won't re-prompt (vs a pending prompt)."""
    return value in ("denied", "restricted")


def open_bundle(binary: str, *, lang: str) -> bool:
    """`open` the helper `.app` so macOS surfaces the prompts, in the
    user's locale. Returns False when the binary is not inside a bundle
    (no UI to trigger prompts). Best-effort: a failed `open` returns
    False rather than raising."""
    bundle = _helper.bundle_path(binary)
    if bundle is None:
        return False
    tag = "zh-Hans" if lang == "zh" else "en"
    try:
        subprocess.Popen(
            ["/usr/bin/open", "--env", f"DITING_LANG={lang}",
             bundle, "--args", "-AppleLanguages", f"({tag})"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except OSError:
        return False
    return True


def settings_pane_url(key: str) -> str:
    return (
        "x-apple.systempreferences:com.apple.preference.security?"
        + _SETTINGS_PANE[key]
    )


def open_settings_pane(key: str) -> bool:
    """Open System Settings to the Privacy pane for `key`. Best-effort —
    returns False on failure so the caller can still print instructions."""
    try:
        subprocess.Popen(
            ["/usr/bin/open", settings_pane_url(key)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except OSError:
        return False
    return True
