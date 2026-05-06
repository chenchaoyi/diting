"""Regenerate src/wifiscope/data/bluetooth_vendors.json from upstream.

Fetches the Bluetooth SIG public assigned-numbers YAML (one file at the
URL in TARGET_URL), parses out the company_identifiers list, and
writes a flat decimal-keyed JSON map plus a `_meta` block recording the
source commit and fetch date.

Run via `make update-vendors` rather than directly so the source-of-
truth URL stays in one place.
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
PATH = "assigned_numbers/company_identifiers/company_identifiers.yaml"
YAML_URL = f"https://bitbucket.org/{REPO}/raw/{BRANCH}/{PATH}"
COMMITS_URL = f"https://api.bitbucket.org/2.0/repositories/{REPO}/commits/?pagelen=1"
OUTPUT = Path(__file__).resolve().parents[1] / "src" / "wifiscope" / "data" / "bluetooth_vendors.json"


def _fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "wifiscope-vendor-sync"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def _latest_commit() -> str:
    try:
        body = _fetch(COMMITS_URL)
        payload = json.loads(body)
        return str(payload["values"][0]["hash"])
    except Exception as exc:
        print(f"warning: could not fetch source commit hash: {exc}", file=sys.stderr)
        return "unknown"


def main() -> int:
    print(f"==> fetching {YAML_URL}")
    raw = _fetch(YAML_URL)
    doc = yaml.safe_load(raw)
    entries = doc.get("company_identifiers") or []
    if not isinstance(entries, list):
        print("error: company_identifiers is not a list", file=sys.stderr)
        return 1

    out: dict[str, str] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        value = entry.get("value")
        name = entry.get("name")
        if value is None or not isinstance(name, str):
            continue
        # YAML accepts hex literals (0x10BB) and yields a Python int.
        try:
            cid = int(value)
        except (TypeError, ValueError):
            continue
        out[str(cid)] = name

    if not out:
        print("error: no vendor entries parsed", file=sys.stderr)
        return 1

    commit = _latest_commit()
    print(f"==> source commit: {commit}")

    payload: dict[str, object] = {
        "_meta": {
            "source_commit": commit,
            "fetched_at": datetime.now(timezone.utc).date().isoformat(),
            "source_url": YAML_URL,
        },
    }
    # Sort numerically for stable diffs commit-to-commit.
    for key in sorted(out, key=int):
        payload[key] = out[key]

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    print(f"==> wrote {OUTPUT} ({len(out)} vendors)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
