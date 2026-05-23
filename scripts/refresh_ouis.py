#!/usr/bin/env python3
"""Refresh the bundled IEEE OUI maps.

Pulls all three IEEE OUI tiers — MA-L (24-bit), MA-M (28-bit), and
MA-S (36-bit) — and rewrites the bundled JSON files under
``src/diting/data/``:

- ``wifi_ouis.json`` / ``bluetooth_ouis.json``  — MA-L
- ``wifi_ouis_ma_m.json`` / ``bluetooth_ouis_ma_m.json`` — MA-M
- ``wifi_ouis_ma_s.json`` / ``bluetooth_ouis_ma_s.json`` — MA-S

Two sources are supported, picked via ``--source``:

- ``ieee`` (default when reachable): fetch each tier's CSV directly
  from the IEEE Registration Authority. Authoritative but the CDN
  is intermittently unreachable from CN networks (TLS mid-handshake
  RST).
- ``wireshark``: fetch the Wireshark project's ``manuf`` file from
  ``https://www.wireshark.org/download/automated/data/manuf``. The
  ``manuf`` file is a community-maintained mirror of IEEE OUI data
  (re-generated regularly), exposes all three tiers in one file
  marked by ``/28`` / ``/36`` prefix-bit notation, and reaches CN
  networks reliably.
- ``auto`` (the default): try IEEE first; on any failure fall back
  to Wireshark. Records which source was used in each output's
  ``_meta.source`` field so future maintainers can tell.

Run from the repo root:

    uv run python scripts/refresh_ouis.py
    uv run python scripts/refresh_ouis.py --source wireshark
    uv run python scripts/refresh_ouis.py --manuf-file /tmp/manuf.txt

The script is read-only against the network — it does not cache or
partially update on failure. Any failure exits non-zero and leaves
the bundled data unchanged.

License note: IEEE distributes the OUI registries freely (attribution-
only). The Wireshark ``manuf`` file is GPL-2.0-licensed; we ingest
the data values (vendor names, IEEE prefixes), not the file itself,
which is the same posture every other Wireshark-derived OUI
project takes.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import re
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
    ouis: dict[str, str],
    *,
    registry: Registry,
    path: Path,
    source_override: str | None = None,
    source_url_override: str | None = None,
) -> None:
    """Write the dict to JSON in the schema callers expect.

    Mirrors the existing file shape: a ``_meta`` block at the top
    followed by ``key → vendor`` entries. Keys are sorted so diffs
    stay stable across re-runs.

    ``source_override`` / ``source_url_override`` let the Wireshark
    code path annotate the resulting file with where the data
    actually came from. When both are None, the defaults reflect
    direct IEEE fetch.
    """
    source_label = source_override or (
        f"IEEE Registration Authority — {registry.name} "
        f"({registry.prefix_bits}-bit) OUI registry"
    )
    source_url = source_url_override or registry.csv_url
    payload = {
        "_meta": {
            "source": source_label,
            "source_url": source_url,
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


# ---------- Wireshark manuf path ----------

# The community-maintained mirror, regenerated regularly from IEEE.
# Reaches CN networks where IEEE direct does not.
_WIRESHARK_MANUF_URL = (
    "https://www.wireshark.org/download/automated/data/manuf"
)


_MANUF_LINE_RE = re.compile(
    r"^(?P<prefix>[0-9A-Fa-f][0-9A-Fa-f:]+)"
    r"(?:/(?P<bits>\d+))?"
    r"\s+(?P<short>\S+)\s+(?P<vendor>.+?)\s*$"
)


def _manuf_prefix_to_key(prefix: str, bits: int | None) -> tuple[str, str] | None:
    """Convert a Wireshark prefix + bit-width into ``(tier, key)``.

    Returns one of:

    - ``("MA-L", "aa:bb:cc")`` for 24-bit (default when no /N).
    - ``("MA-M", "aa:bb:cc:d")`` for 28-bit (``/28``).
    - ``("MA-S", "aa:bb:cc:dd:e")`` for 36-bit (``/36``).
    - ``None`` for malformed / unexpected widths.
    """
    hex_only = prefix.replace(":", "").lower()
    if any(c not in "0123456789abcdef" for c in hex_only):
        return None
    if bits is None or bits == 24:
        if len(hex_only) < 6:
            return None
        return ("MA-L", f"{hex_only[0:2]}:{hex_only[2:4]}:{hex_only[4:6]}")
    if bits == 28:
        if len(hex_only) < 7:
            return None
        return (
            "MA-M",
            f"{hex_only[0:2]}:{hex_only[2:4]}:{hex_only[4:6]}:{hex_only[6]}",
        )
    if bits == 36:
        if len(hex_only) < 9:
            return None
        return (
            "MA-S",
            f"{hex_only[0:2]}:{hex_only[2:4]}:{hex_only[4:6]}:"
            f"{hex_only[6:8]}:{hex_only[8]}",
        )
    # Unexpected width (Wireshark sometimes carries non-IEEE custom
    # widths — skip those rather than mis-key them).
    return None


def parse_wireshark_manuf(text: str) -> dict[str, dict[str, str]]:
    """Parse a Wireshark ``manuf`` file into a per-tier dict.

    Returns ``{"MA-L": {…}, "MA-M": {…}, "MA-S": {…}}``. Each value
    is the ``key → vendor-name`` map for that tier, ready to be
    written out by ``write_ouis``.

    Wireshark column 3 holds the full IEEE vendor name verbatim.
    Wireshark column 2 is its own abbreviated identifier (ignored).
    The ``00:00:00`` row is a Wireshark-specific commentary
    annotation, NOT an IEEE name — we keep it as-is so the bundled
    file matches the lookup contract; downstream `_normalize_vendor`
    will tidy display.
    """
    out: dict[str, dict[str, str]] = {"MA-L": {}, "MA-M": {}, "MA-S": {}}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        m = _MANUF_LINE_RE.match(raw_line)
        if m is None:
            continue
        prefix = m.group("prefix")
        bits_str = m.group("bits")
        bits = int(bits_str) if bits_str else None
        vendor = m.group("vendor").strip()
        if not vendor:
            continue
        keyed = _manuf_prefix_to_key(prefix, bits)
        if keyed is None:
            continue
        tier, key = keyed
        if key in out[tier]:
            # First wins, matching IEEE-CSV dedup convention.
            continue
        out[tier][key] = vendor
    return out


def _fetch_wireshark_manuf() -> str:
    """Download the Wireshark manuf file as UTF-8 text."""
    req = urllib.request.Request(
        _WIRESHARK_MANUF_URL,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X) "
                "diting-refresh-ouis/1.0"
            ),
            "Accept": "text/plain,*/*",
        },
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _write_from_results(
    results: list[tuple[Registry, dict[str, str]]],
    *,
    source_label: str | None = None,
) -> None:
    """Write the bundled JSON files from a list of ``(registry, dict)``
    pairs.

    ``source_label`` overrides the ``_meta.source`` annotation —
    useful when the data came from the Wireshark mirror rather than
    direct IEEE."""
    for reg, ouis in results:
        for basename in reg.output_basenames:
            path = _DATA_DIR / basename
            print(
                f"writing {len(ouis):,} {reg.name} entries to {path}",
                flush=True,
            )
            write_ouis(
                ouis, registry=reg, path=path, source_override=source_label,
            )


def _refresh_from_ieee() -> list[tuple[Registry, dict[str, str]]] | None:
    """Try the IEEE direct path. Returns the parsed per-tier results
    on success, or None on any fetch / parse failure (so the caller
    can fall through to a different source)."""
    results: list[tuple[Registry, dict[str, str]]] = []
    for reg in _REGISTRIES:
        print(f"[ieee] fetching {reg.csv_url} ...", flush=True)
        try:
            csv_text = _fetch_csv(reg.csv_url)
        except Exception as exc:
            print(
                f"[ieee] fetch failed for {reg.name}: {exc}",
                file=sys.stderr,
            )
            return None
        print(
            f"[ieee] parsing {len(csv_text):,} bytes ({reg.name}) ...",
            flush=True,
        )
        try:
            ouis = parse_csv(csv_text, reg)
        except ValueError as exc:
            print(
                f"[ieee] parse failed for {reg.name}: {exc}",
                file=sys.stderr,
            )
            return None
        results.append((reg, ouis))
    return results


def _refresh_from_wireshark(
    *, manuf_path: Path | None = None,
) -> list[tuple[Registry, dict[str, str]]] | None:
    """Pull the Wireshark manuf file (or load a local copy) and
    re-partition it into the three-tier shape. Returns the per-tier
    results, or None on failure."""
    if manuf_path is not None:
        print(f"[wireshark] reading {manuf_path} ...", flush=True)
        try:
            text = manuf_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            print(
                f"[wireshark] cannot read {manuf_path}: {exc}",
                file=sys.stderr,
            )
            return None
    else:
        print(
            f"[wireshark] fetching {_WIRESHARK_MANUF_URL} ...",
            flush=True,
        )
        try:
            text = _fetch_wireshark_manuf()
        except Exception as exc:
            print(
                f"[wireshark] fetch failed: {exc}", file=sys.stderr,
            )
            return None

    print(
        f"[wireshark] parsing {len(text):,} bytes ...", flush=True,
    )
    tier_dicts = parse_wireshark_manuf(text)

    out: list[tuple[Registry, dict[str, str]]] = []
    for reg in _REGISTRIES:
        out.append((reg, tier_dicts.get(reg.name, {})))
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--source",
        choices=("auto", "ieee", "wireshark"),
        default="auto",
        help=(
            "Data source. 'auto' (default) tries IEEE direct first "
            "and falls back to the Wireshark mirror on any failure. "
            "'ieee' uses only IEEE direct (fails hard). 'wireshark' "
            "uses only the Wireshark mirror."
        ),
    )
    parser.add_argument(
        "--manuf-file",
        type=Path,
        default=None,
        help=(
            "Local copy of the Wireshark `manuf` file. When provided, "
            "skips the network fetch and re-partitions this file. "
            "Implies --source wireshark."
        ),
    )
    args = parser.parse_args(argv)

    if args.manuf_file is not None:
        source = "wireshark"
    else:
        source = args.source

    results: list[tuple[Registry, dict[str, str]]] | None = None
    source_used: str | None = None
    source_url_used: str | None = None

    if source == "ieee":
        results = _refresh_from_ieee()
        if results is None:
            print("ERROR: IEEE fetch failed", file=sys.stderr)
            return 1
        source_used = None  # use default per-tier IEEE label
    elif source == "wireshark":
        results = _refresh_from_wireshark(manuf_path=args.manuf_file)
        if results is None:
            print("ERROR: Wireshark fetch failed", file=sys.stderr)
            return 1
        source_used = (
            "Wireshark `manuf` mirror of IEEE Registration Authority"
        )
        source_url_used = _WIRESHARK_MANUF_URL
    else:  # auto
        results = _refresh_from_ieee()
        if results is None:
            print(
                "[auto] IEEE direct failed — falling back to Wireshark mirror",
                file=sys.stderr,
            )
            results = _refresh_from_wireshark()
            if results is None:
                print(
                    "ERROR: both IEEE and Wireshark sources failed",
                    file=sys.stderr,
                )
                return 1
            source_used = (
                "Wireshark `manuf` mirror of IEEE Registration Authority"
            )
            source_url_used = _WIRESHARK_MANUF_URL

    # Pass 2: write. By this point every fetch + parse succeeded; a
    # write failure here is local disk only.
    for reg, ouis in results:
        for basename in reg.output_basenames:
            path = _DATA_DIR / basename
            print(
                f"writing {len(ouis):,} {reg.name} entries to {path}",
                flush=True,
            )
            write_ouis(
                ouis,
                registry=reg,
                path=path,
                source_override=source_used,
                source_url_override=source_url_used,
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
