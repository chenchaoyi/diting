"""Regenerate Bluetooth SIG-derived JSON tables from upstream.

Fetches three assigned-numbers YAML files from the public Bluetooth
SIG repository:

  * ``company_identifiers.yaml``   — manufacturer-data company IDs
  * ``service_uuids.yaml``         — 16-bit GATT service UUIDs
  * ``member_uuids.yaml``          — 16-bit member-assigned service
                                     UUIDs (one per company)

Each becomes its own JSON file under ``src/wifiscope/data/``. Every
output ships a ``_meta`` block recording the source commit and fetch
date so we can audit drift.

Run via ``make update-vendors`` rather than directly so the
source-of-truth URLs stay in one place.
"""
from __future__ import annotations

import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import yaml

REPO = "bluetooth-SIG/public"
BRANCH = "main"
COMMITS_URL = (
    f"https://api.bitbucket.org/2.0/repositories/{REPO}/commits/?pagelen=1"
)
DATA_DIR = (
    Path(__file__).resolve().parents[1] / "src" / "wifiscope" / "data"
)


def _yaml_url(path: str) -> str:
    return f"https://bitbucket.org/{REPO}/raw/{BRANCH}/{path}"


def _fetch(url: str) -> bytes:
    req = urllib.request.Request(
        url, headers={"User-Agent": "wifiscope-vendor-sync"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def _latest_commit() -> str:
    try:
        body = _fetch(COMMITS_URL)
        payload = json.loads(body)
        return str(payload["values"][0]["hash"])
    except Exception as exc:
        print(
            f"warning: could not fetch source commit hash: {exc}",
            file=sys.stderr,
        )
        return "unknown"


def _write_json(out_path: Path, payload: dict, *, label: str) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
    )
    body_count = sum(1 for k in payload if k != "_meta")
    print(f"==> wrote {out_path} ({body_count} {label})")


def _meta(commit: str, source_url: str) -> dict[str, str]:
    return {
        "source_commit": commit,
        "fetched_at": datetime.now(timezone.utc).date().isoformat(),
        "source_url": source_url,
    }


def _fetch_yaml_list(yaml_path: str, list_key: str) -> list[dict]:
    url = _yaml_url(yaml_path)
    print(f"==> fetching {url}")
    raw = _fetch(url)
    doc = yaml.safe_load(raw)
    entries = doc.get(list_key) or []
    if not isinstance(entries, list):
        raise RuntimeError(f"{list_key} is not a list in {yaml_path}")
    return [e for e in entries if isinstance(e, dict)]


def _company_identifiers(commit: str) -> dict[str, object]:
    """company_identifiers.yaml → ``{"<decimal id>": "<name>"}``."""
    yaml_path = (
        "assigned_numbers/company_identifiers/company_identifiers.yaml"
    )
    entries = _fetch_yaml_list(yaml_path, "company_identifiers")
    body: dict[str, str] = {}
    for entry in entries:
        value = entry.get("value")
        name = entry.get("name")
        if value is None or not isinstance(name, str):
            continue
        try:
            cid = int(value)
        except (TypeError, ValueError):
            continue
        body[str(cid)] = name
    payload: dict[str, object] = {"_meta": _meta(commit, _yaml_url(yaml_path))}
    for key in sorted(body, key=int):
        payload[key] = body[key]
    return payload


def _uuid_table(yaml_path: str, list_key: str, commit: str) -> dict[str, object]:
    """service_uuids.yaml or member_uuids.yaml → ``{"FDAA": "Name"}``.

    Keys are 4-char upper-case hex (the 16-bit short form). Long-form
    UUIDs from the source are not preserved — every entry in these
    SIG files is by definition a short 16-bit assignment.
    """
    entries = _fetch_yaml_list(yaml_path, list_key)
    body: dict[str, str] = {}
    for entry in entries:
        value = entry.get("uuid")
        name = entry.get("name")
        if value is None or not isinstance(name, str):
            continue
        # YAML hex literals (0xFDAA) → Python int. Normalise to 4-char hex.
        try:
            n = int(value)
        except (TypeError, ValueError):
            continue
        if n < 0 or n > 0xFFFF:
            continue
        body[f"{n:04X}"] = name
    payload: dict[str, object] = {"_meta": _meta(commit, _yaml_url(yaml_path))}
    for key in sorted(body):
        payload[key] = body[key]
    return payload


def main() -> int:
    commit = _latest_commit()
    print(f"==> source commit: {commit}")

    vendors = _company_identifiers(commit)
    _write_json(DATA_DIR / "bluetooth_vendors.json", vendors, label="vendors")

    gatt = _uuid_table(
        "assigned_numbers/uuids/service_uuids.yaml",
        "uuids", commit,
    )
    _write_json(
        DATA_DIR / "bluetooth_gatt_services.json", gatt,
        label="GATT services",
    )

    members = _uuid_table(
        "assigned_numbers/uuids/member_uuids.yaml",
        "uuids", commit,
    )
    _write_json(
        DATA_DIR / "bluetooth_member_uuids.json", members,
        label="member UUIDs",
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
