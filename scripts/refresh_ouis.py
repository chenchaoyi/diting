#!/usr/bin/env python3
"""Refresh the bundled IEEE OUI maps.

Downloads the IEEE Registration Authority's MA-L (24-bit), MA-M
(28-bit), and MA-S (36-bit) CSV registries, parses each, dedupes,
normalises keys, and rewrites the bundled JSON files under
``src/diting/data/``:

- ``wifi_ouis.json`` / ``bluetooth_ouis.json``  — MA-L (24-bit)
- ``wifi_ouis_ma_m.json`` / ``bluetooth_ouis_ma_m.json`` — MA-M (28-bit)
- ``wifi_ouis_ma_s.json`` / ``bluetooth_ouis_ma_s.json`` — MA-S (36-bit)

Run from the repo root, before each release, when you want to pick
up newly-registered OUIs:

    uv run python scripts/refresh_ouis.py

The script is intentionally read-only against IEEE — it does not
fall back to a cache or partial result on a per-registry failure.
A failure fetching one registry exits non-zero and leaves all
existing data files untouched.

License note: IEEE distributes the OUI registries freely; the
convention is to attribute "IEEE Registration Authority". The _meta
block in each resulting JSON records the source URL and fetch
timestamp.
"""
from __future__ import annotations

import csv
import io
import json
import sys
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DATA_DIR = _REPO_ROOT / "src" / "diting" / "data"


@dataclass(frozen=True)
class Registry:
    """One IEEE registry tier (MA-L / MA-M / MA-S)."""

    name: str
    csv_url: str
    prefix_bits: int  # 24, 28, or 36
    output_basenames: tuple[str, ...]


# Tier definitions. Output paths intentionally mirror the bluetooth /
# wifi twins so both consumers (BLE + Wi-Fi) keep working as today.
_REGISTRIES: tuple[Registry, ...] = (
    Registry(
        name="MA-L",
        csv_url="https://standards-oui.ieee.org/oui/oui.csv",
        prefix_bits=24,
        output_basenames=("bluetooth_ouis.json", "wifi_ouis.json"),
    ),
    Registry(
        name="MA-M",
        csv_url="https://standards-oui.ieee.org/oui28/mam.csv",
        prefix_bits=28,
        output_basenames=(
            "bluetooth_ouis_ma_m.json",
            "wifi_ouis_ma_m.json",
        ),
    ),
    Registry(
        name="MA-S",
        csv_url="https://standards-oui.ieee.org/oui36/oui36.csv",
        prefix_bits=36,
        output_basenames=(
            "bluetooth_ouis_ma_s.json",
            "wifi_ouis_ma_s.json",
        ),
    ),
)


def _key_for_assignment(assignment_hex: str, prefix_bits: int) -> str | None:
    """Convert IEEE's ``Assignment`` column into our ``aa:bb:cc[:dd[:ee]]`` key.

    IEEE writes:
    - MA-L assignments as 6 hex chars  (e.g. ``001122``)
    - MA-M assignments as 7 hex chars  (e.g. ``0011223``)  → padded to 8
    - MA-S assignments as 9 hex chars  (e.g. ``001122334``) → padded to 10

    The lookup function in ``diting.ble`` matches on character ranges,
    not on bit-masks, so we keep the IEEE assignment as a hex string
    and zero-pad to a colon-separated byte form. Trailing-nibble
    sub-allocations (the MA-M / MA-S case) are encoded by keeping the
    odd-length hex and emitting one extra colon-separated nibble.
    """
    a = assignment_hex.strip().upper()
    if any(c not in "0123456789ABCDEF" for c in a):
        return None
    if prefix_bits == 24:
        if len(a) != 6:
            return None
        return f"{a[0:2]}:{a[2:4]}:{a[4:6]}".lower()
    if prefix_bits == 28:
        # IEEE MA-M assignment is 7 hex chars; we encode the 4-bit
        # nibble as a single hex digit in the fourth byte slot.
        if len(a) != 7:
            return None
        return f"{a[0:2]}:{a[2:4]}:{a[4:6]}:{a[6]}".lower()
    if prefix_bits == 36:
        # IEEE MA-S assignment is 9 hex chars; emit five colon-separated
        # pieces, the last being a single nibble.
        if len(a) != 9:
            return None
        return f"{a[0:2]}:{a[2:4]}:{a[4:6]}:{a[6:8]}:{a[8]}".lower()
    return None


def parse_csv(csv_text: str, registry: Registry) -> dict[str, str]:
    """Parse IEEE OUI CSV text into a ``{key: vendor}`` dict.

    Filters to rows whose Registry column matches ``registry.name``.
    Drops the header row. Dedupes by key — IEEE occasionally lists
    the same key twice under slightly different organization-name
    variants; first wins.

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
        registry_col, assignment, org_name = row[0], row[1], row[2]
        if registry_col.strip() != registry.name:
            continue
        key = _key_for_assignment(assignment, registry.prefix_bits)
        if key is None:
            continue
        if key in out:
            continue
        out[key] = org_name.strip()
    return out


def write_ouis(
    ouis: dict[str, str], *, registry: Registry, path: Path,
) -> None:
    """Write the dict to JSON in the schema callers expect.

    Mirrors the existing file shape: a ``_meta`` block at the top
    followed by ``key → vendor`` entries. Keys are sorted so diffs
    stay stable across re-runs.
    """
    payload = {
        "_meta": {
            "source": (
                f"IEEE Registration Authority — {registry.name} "
                f"({registry.prefix_bits}-bit) OUI registry"
            ),
            "source_url": registry.csv_url,
            "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "license": (
                "Attribution-only convention; see IEEE Registration "
                "Authority terms at https://standards.ieee.org/products-programs/regauth/"
            ),
            "note": (
                f"Full {registry.name} registry. To refresh, run "
                "`uv run python scripts/refresh_ouis.py` from the repo "
                "root. All three tiers (MA-L 24-bit, MA-M 28-bit, MA-S "
                "36-bit) are refreshed together. The lookup function in "
                "`diting.ble.lookup_oui_vendor` tries the longest prefix "
                "first."
            ),
        }
    }
    for key in sorted(ouis.keys()):
        payload[key] = ouis[key]
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")


def _fetch_csv(url: str) -> str:
    """Fetch IEEE CSV text with a browser-shaped User-Agent.

    IEEE's CDN returns HTTP 418 to clients with an empty / "Python-
    urllib" User-Agent. Send a real-looking UA so the fetch lands.
    """
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X) "
                "diting-refresh-ouis/1.0"
            ),
            "Accept": "text/csv,*/*",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read().decode("utf-8", errors="replace")


def main() -> int:
    # Pass 1: fetch + parse all three registries. We hold all three
    # results in memory before writing anything so a partial failure
    # never leaves the bundled data half-updated.
    results: list[tuple[Registry, dict[str, str]]] = []
    for reg in _REGISTRIES:
        print(f"fetching {reg.csv_url} ...", flush=True)
        try:
            csv_text = _fetch_csv(reg.csv_url)
        except Exception as exc:
            print(
                f"ERROR: fetch failed for {reg.name}: {exc}",
                file=sys.stderr,
            )
            return 1
        print(f"parsing {len(csv_text):,} bytes ({reg.name}) ...", flush=True)
        try:
            ouis = parse_csv(csv_text, reg)
        except ValueError as exc:
            print(
                f"ERROR: parse failed for {reg.name}: {exc}",
                file=sys.stderr,
            )
            return 2
        results.append((reg, ouis))

    # Pass 2: write all output files. By this point every fetch has
    # succeeded and every parse has succeeded; a write failure here
    # is local disk only.
    for reg, ouis in results:
        for basename in reg.output_basenames:
            path = _DATA_DIR / basename
            print(
                f"writing {len(ouis):,} {reg.name} entries to {path}",
                flush=True,
            )
            write_ouis(ouis, registry=reg, path=path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
