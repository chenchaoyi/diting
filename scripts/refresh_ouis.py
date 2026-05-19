#!/usr/bin/env python3
"""Refresh the bundled IEEE OUI map.

Downloads the IEEE Registration Authority's MA-L (24-bit) CSV from
``https://standards-oui.ieee.org/oui/oui.csv``, parses it, dedupes,
normalises keys to ``aa:bb:cc`` form, and rewrites
``src/diting/data/wifi_ouis.json``.

Run from the repo root, before each release, when you want to pick
up newly-registered OUIs:

    uv run python scripts/refresh_ouis.py

The script is intentionally read-only against IEEE — it does not
fall back to a cache or partial result on failure. On any error it
exits non-zero and leaves the existing data file untouched.

License note: IEEE distributes the OUI registry freely; the convention
is to attribute "IEEE Registration Authority". The _meta block in
the resulting JSON records the source URL and fetch timestamp.
"""
from __future__ import annotations

import csv
import io
import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

_IEEE_OUI_CSV_URL = "https://standards-oui.ieee.org/oui/oui.csv"
_REPO_ROOT = Path(__file__).resolve().parent.parent
# Two consumers historically: bluetooth_ouis.json (BLE + LAN host
# lookups via `diting.ble.load_ouis`) and wifi_ouis.json (Wi-Fi BSSID
# vendor lookups via `diting.network.load_wifi_ouis`). The data is
# identical — both are IEEE 24-bit OUI → vendor — so refresh writes
# the same payload to both files. A future refactor can consolidate
# to a single file; today, keeping the two paths preserves the
# back-compat the rest of the code expects.
_OUTPUT_PATHS = [
    _REPO_ROOT / "src" / "diting" / "data" / "bluetooth_ouis.json",
    _REPO_ROOT / "src" / "diting" / "data" / "wifi_ouis.json",
]


def parse_csv(csv_text: str) -> dict[str, str]:
    """Parse IEEE OUI CSV text into a `{aa:bb:cc: vendor}` dict.

    Filters to MA-L rows (24-bit OUI assignments). Drops the
    "Registry,Assignment,Organization Name,Organization Address"
    header row. Dedupes — IEEE occasionally lists the same OUI
    twice under slightly different organization-name variants;
    first wins.

    Raises ValueError when the CSV's header doesn't match the
    expected IEEE format (defensive against IEEE silently changing
    the schema).
    """
    reader = csv.reader(io.StringIO(csv_text))
    rows = iter(reader)
    try:
        header = next(rows)
    except StopIteration:
        raise ValueError("CSV is empty")
    # Trim whitespace + BOM from the first cell so the registry
    # column matches whatever IEEE feeds us.
    header = [h.strip().lstrip("﻿") for h in header]
    expected = ["Registry", "Assignment", "Organization Name"]
    if header[: len(expected)] != expected:
        raise ValueError(
            f"unexpected CSV header: {header!r} (wanted prefix {expected!r})"
        )
    out: dict[str, str] = {}
    for row in rows:
        if len(row) < 3:
            continue
        registry, assignment, org_name = row[0], row[1], row[2]
        if registry.strip() != "MA-L":
            continue
        a = assignment.strip().upper()
        if len(a) != 6 or any(c not in "0123456789ABCDEF" for c in a):
            continue
        key = f"{a[0:2]}:{a[2:4]}:{a[4:6]}".lower()
        if key in out:
            continue
        out[key] = org_name.strip()
    return out


def write_ouis(ouis: dict[str, str], *, source_url: str, path: Path) -> None:
    """Write the dict to JSON in the schema callers expect.

    Mirrors the existing file shape: a `_meta` block at the top
    followed by `aa:bb:cc → vendor` entries. Keys are sorted so
    diffs stay stable across re-runs.
    """
    payload = {
        "_meta": {
            "source": (
                "IEEE Registration Authority — MA-L (24-bit) OUI registry"
            ),
            "source_url": source_url,
            "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "license": (
                "Attribution-only convention; see IEEE Registration "
                "Authority terms at https://standards.ieee.org/products-programs/regauth/"
            ),
            "note": (
                "Full MA-L registry. To refresh, run "
                "`uv run python scripts/refresh_ouis.py` from the repo "
                "root. MA-M (28-bit) and MA-S (36-bit) sub-allocations "
                "are not included; the lookup function only matches "
                "the first 6 hex characters (24-bit OUI)."
            ),
        }
    }
    for key in sorted(ouis.keys()):
        payload[key] = ouis[key]
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")


def main() -> int:
    print(f"fetching {_IEEE_OUI_CSV_URL} ...", flush=True)
    # IEEE's CDN returns HTTP 418 to clients with an empty / "Python-
    # urllib" User-Agent. Send a real-browser-shaped UA so the fetch
    # actually lands.
    req = urllib.request.Request(
        _IEEE_OUI_CSV_URL,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X) "
                "diting-refresh-ouis/1.0"
            ),
            "Accept": "text/csv,*/*",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            csv_text = resp.read().decode("utf-8", errors="replace")
    except Exception as exc:
        print(f"ERROR: fetch failed: {exc}", file=sys.stderr)
        return 1

    print(f"parsing {len(csv_text):,} bytes ...", flush=True)
    try:
        ouis = parse_csv(csv_text)
    except ValueError as exc:
        print(f"ERROR: parse failed: {exc}", file=sys.stderr)
        return 2

    for path in _OUTPUT_PATHS:
        print(
            f"writing {len(ouis):,} OUI entries to {path}",
            flush=True,
        )
        write_ouis(ouis, source_url=_IEEE_OUI_CSV_URL, path=path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
