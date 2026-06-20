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


def probe(binary: str) -> dict:
    """Probe each grant. `location`/`bluetooth` are bools; `notifications`
    is True/False, or None when the helper can't verify it (too old)."""
    loc = _helper.has_permission(binary)
    bt = _helper.has_bluetooth_permission(binary)
    if _helper.has_notification_status_subcommand(binary):
        notif: bool | None = _helper.has_notification_permission(binary)
    else:
        notif = None  # unverifiable on an older helper — report unknown
    return {"location": loc, "bluetooth": bt, "notifications": notif}


def is_ready(state: dict) -> bool:
    """All REQUIRED grants present (notifications is best-effort)."""
    return all(bool(state.get(k)) for k in REQUIRED)


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
