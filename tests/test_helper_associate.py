"""Tests for `_helper.associate` JSON / exit-code parsing.

The Swift helper binary itself is not exercised here — same pattern as
`test_helper.py`. We mock `subprocess.run` and verify every documented
outcome (success with + without Keychain save, every named error code,
malformed JSON, OS-level subprocess failures) lands as the right
`AssociateResult`.
"""
from __future__ import annotations

import json
import subprocess
from unittest.mock import patch

from diting import _helper
from diting.backend import AssociateResult


def _proc(stdout: str | bytes = b"", *, returncode: int = 0, stderr: bytes = b""):
    """Minimal stand-in for `CompletedProcess` — same shape as test_helper.py's _mock_run."""
    class _P:
        pass
    p = _P()
    p.stdout = stdout if isinstance(stdout, bytes) else stdout.encode()
    p.stderr = stderr
    p.returncode = returncode
    return p


def test_associate_ok_zero_exit():
    payload = json.dumps({
        "schema": 1, "ok": True,
        "bssid": "aa:bb:cc:dd:ee:ff", "keychain_saved": False,
    })
    with patch("diting._helper.subprocess.run", return_value=_proc(payload)):
        result = _helper.associate("/fake/binary", "cafe-guest")
    assert isinstance(result, AssociateResult)
    assert result.ok is True
    assert result.bssid == "aa:bb:cc:dd:ee:ff"
    assert result.keychain_saved is False
    assert result.error_code is None


def test_associate_ok_with_keychain_saved():
    payload = json.dumps({
        "schema": 1, "ok": True,
        "bssid": "00:11:22:33:44:55", "keychain_saved": True,
    })
    with patch("diting._helper.subprocess.run", return_value=_proc(payload)):
        result = _helper.associate("/fake/binary", "home-5G")
    assert result.ok is True
    assert result.keychain_saved is True


def test_associate_enterprise_exits_5():
    payload = json.dumps({
        "schema": 1, "error": "Enterprise / 802.1X",
        "code": "enterprise_unsupported",
    })
    with patch(
        "diting._helper.subprocess.run", return_value=_proc(payload, returncode=5)
    ):
        result = _helper.associate("/fake/binary", "eduroam")
    assert result.ok is False
    assert result.error_code == "enterprise_unsupported"
    assert result.error_message == "Enterprise / 802.1X"


def test_associate_cancelled_exits_6():
    payload = json.dumps({"schema": 1, "error": "user cancelled", "code": "cancelled"})
    with patch(
        "diting._helper.subprocess.run", return_value=_proc(payload, returncode=6)
    ):
        result = _helper.associate("/fake/binary", "cafe-guest")
    assert result.ok is False
    assert result.error_code == "cancelled"


def test_associate_auth_failed_exits_7():
    payload = json.dumps({"schema": 1, "error": "authentication failed", "code": "auth_failed"})
    with patch(
        "diting._helper.subprocess.run", return_value=_proc(payload, returncode=7)
    ):
        result = _helper.associate("/fake/binary", "cafe-guest")
    assert result.ok is False
    assert result.error_code == "auth_failed"


def test_associate_ssid_not_found_exits_8():
    payload = json.dumps({"schema": 1, "error": "SSID not in scan range", "code": "ssid_not_found"})
    with patch(
        "diting._helper.subprocess.run", return_value=_proc(payload, returncode=8)
    ):
        result = _helper.associate("/fake/binary", "ghost-ap")
    assert result.ok is False
    assert result.error_code == "ssid_not_found"


def test_associate_malformed_json_falls_back_to_unknown():
    """Helper produced something other than JSON (corrupted output, crash
    mid-write, etc.) — we still return a usable AssociateResult instead
    of letting the JSONDecodeError bubble."""
    with patch(
        "diting._helper.subprocess.run",
        return_value=_proc("not json at all", returncode=1, stderr=b"boom"),
    ):
        result = _helper.associate("/fake/binary", "cafe-guest")
    assert result.ok is False
    assert result.error_code == "unknown"
    assert result.error_message == "boom"


def test_associate_unmapped_exit_code_is_unknown():
    """Future helper might add new exit codes; the Python side must
    degrade to `unknown` rather than crash."""
    with patch(
        "diting._helper.subprocess.run",
        return_value=_proc(b"{}", returncode=99),
    ):
        result = _helper.associate("/fake/binary", "cafe-guest")
    assert result.ok is False
    assert result.error_code == "unknown"


def test_associate_subprocess_oserror_returns_unknown():
    """Binary not executable, permission denied at the OS level, etc."""
    with patch(
        "diting._helper.subprocess.run",
        side_effect=OSError("permission denied"),
    ):
        result = _helper.associate("/fake/binary", "cafe-guest")
    assert result.ok is False
    assert result.error_code == "unknown"
    assert result.error_message == "permission denied"


def test_associate_timeout_returns_unknown():
    """User left the AppKit password sheet sitting too long, or the
    helper itself hung — Python should not let `subprocess.TimeoutExpired`
    escape `_helper.associate`."""
    with patch(
        "diting._helper.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="...", timeout=90),
    ):
        result = _helper.associate("/fake/binary", "cafe-guest")
    assert result.ok is False
    assert result.error_code == "unknown"
    assert result.error_message == "helper timed out"


def test_associate_passes_bssid_through_when_supplied():
    """The BSSID flag is plumbed onto argv when provided — caller intent
    is recorded even if CoreWLAN picks a different BSSID on the new ESS."""
    captured: dict = {}

    def _spy(argv, **kwargs):
        captured["argv"] = argv
        return _proc(json.dumps({"schema": 1, "ok": True, "bssid": "x", "keychain_saved": False}))

    with patch("diting._helper.subprocess.run", side_effect=_spy):
        _helper.associate("/fake/binary", "cafe-guest", bssid="aa:bb:cc:dd:ee:ff")
    assert captured["argv"] == [
        "/fake/binary", "associate", "--ssid", "cafe-guest",
        "--bssid", "aa:bb:cc:dd:ee:ff",
    ]


def test_associate_omits_bssid_when_not_supplied():
    captured: dict = {}

    def _spy(argv, **kwargs):
        captured["argv"] = argv
        return _proc(json.dumps({"schema": 1, "ok": True, "bssid": "x", "keychain_saved": False}))

    with patch("diting._helper.subprocess.run", side_effect=_spy):
        _helper.associate("/fake/binary", "cafe-guest")
    assert captured["argv"] == ["/fake/binary", "associate", "--ssid", "cafe-guest"]


def test_associate_pipes_empty_stdin_never_password_on_argv():
    """Security guard: the password must NEVER appear on argv. The
    public `associate(...)` doesn't accept a password kwarg, so the
    only way it could leak would be a future regression. Pin it."""
    captured: dict = {}

    def _spy(argv, *, input=None, **kwargs):
        captured["argv"] = argv
        captured["input"] = input
        return _proc(json.dumps({"schema": 1, "ok": True, "bssid": "x", "keychain_saved": False}))

    with patch("diting._helper.subprocess.run", side_effect=_spy):
        _helper.associate("/fake/binary", "cafe-guest")
    assert captured["input"] == b""
    assert "--password" not in captured["argv"]
