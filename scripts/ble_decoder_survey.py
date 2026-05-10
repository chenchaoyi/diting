"""Survey BLE vendor / device-class coverage of wifiscope's lookup chain.

Reads a sample of helper `ble-scan` output (from --input <path> or by
spawning the helper for a fresh capture), dedups by identifier, and
reports:

  - how many devices vendor-resolve via the existing chain
    (manufacturer cid → SIG vendor table → member-UUID table →
     128-bit member-UUID table → name-pattern table)
  - what's left and which kind of fix would close each remainder
    (per-vendor decoder package, name-pattern entry, vendor-private
     cid investigation, or a physical-data limit)
  - distribution of service_data UUIDs in the population (the targets
    if we ever decide to bring in HA-ecosystem decoders for sensor
    data extraction)

This script was originally written as a one-off spike to evaluate
whether `bluetooth-data-tools` would help (answer: no — it's a GAP
frame parser, the same layer our helper already covers). Kept in the
tree so future runs can re-measure coverage as helper / data tables
evolve.

Usage:

    uv run python scripts/ble_decoder_survey.py [--input PATH] [--lines N]

Options:
    --input PATH   Read helper-raw.jsonl from PATH instead of spawning
                   the helper. Useful for offline analysis of an old
                   capture (e.g. one stashed under /tmp/wfs-tui-audit-*).
    --lines N      Cap the helper sample size at N JSONL lines. Default
                   800 — enough that dedup yields ~250 unique devices in
                   a typical office.
"""
from __future__ import annotations

import argparse
import collections
import json
import subprocess
import sys
from pathlib import Path

# Importing wifiscope.ble assumes the script runs from the repo root or
# with the package installed editable (`uv run` already does the right
# thing). No path mangling here.
from wifiscope._helper import find_helper
from wifiscope.ble import (
    load_member_uuids,
    load_vendors,
    lookup_member_vendor,
    lookup_name_vendor,
    lookup_vendor,
)


def capture_via_helper(lines: int) -> str:
    """Run the helper's ble-scan subcommand and capture N lines of JSONL.

    Returns the captured text. Errors are surfaced as a runtime error
    so the caller can stop instead of analysing partial / broken data.
    """
    helper = find_helper()
    if helper is None:
        raise RuntimeError(
            "wifiscope-helper.app not found. Build it first with "
            "`./helper/build.sh` and grant Bluetooth in System Settings."
        )
    proc = subprocess.Popen(
        [helper, "ble-scan"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    captured: list[str] = []
    assert proc.stdout is not None
    try:
        for line in proc.stdout:
            captured.append(line)
            if len(captured) >= lines:
                break
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
    return "".join(captured)


def dedup(text: str) -> dict[str, dict]:
    """Last-write-wins merge across multiple sightings of the same id.

    Connected-snapshot sentinels and connected-peripheral lines are
    skipped — this survey is about advertising rows, where vendor
    resolution actually has multiple paths to fail.
    """
    out: dict[str, dict] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        if d.get("connected_snapshot") or d.get("connected"):
            continue
        ident = d.get("id")
        if not isinstance(ident, str):
            continue
        out[ident] = {**out.get(ident, {}), **d}
    return out


def resolve_vendor(d: dict, vendors: dict, members: dict) -> str | None:
    """Mirror of _build_device's vendor chain (without prior carry-forward).

    Returns the first hit or None. Order matches src/wifiscope/ble.py
    so this script tracks production behaviour as the chain evolves.
    """
    cid = d.get("manufacturer_id")
    if isinstance(cid, int):
        v = lookup_vendor(cid, vendors)
        if v:
            return v

    services = d.get("service_uuids") or []
    if isinstance(services, list) and services:
        v = lookup_member_vendor(tuple(services), members)
        if v:
            return v

    # Schema-4 fallback: service_data keys are also SIG service UUIDs
    # and resolve to the same vendor table. Many Xiaomi / Google /
    # Microsoft devices broadcast their UUID only here.
    sd = d.get("service_data") or {}
    if isinstance(sd, dict) and sd:
        keys = tuple(k for k in sd.keys() if isinstance(k, str))
        if keys:
            v = lookup_member_vendor(keys, members)
            if v:
                return v

    name = d.get("name")
    if isinstance(name, str):
        v = lookup_name_vendor(name)
        if v:
            return v
    return None


def categorize_unresolved(d: dict) -> str:
    """For an unresolved row, what kind of fix would help?"""
    has_mfg = isinstance(d.get("manufacturer_id"), int)
    sd = d.get("service_data") or {}
    has_svc_data = isinstance(sd, dict) and bool(sd)
    services = d.get("service_uuids") or []
    has_svc_uuid = isinstance(services, list) and bool(services)
    has_name = isinstance(d.get("name"), str) and bool(d["name"])
    has_type = isinstance(d.get("type"), str)

    if not (has_mfg or has_svc_data or has_svc_uuid or has_name or has_type):
        return "silent"
    if has_mfg:
        return "vendor-private-cid"
    if has_svc_data:
        return "service-data-decoder-needed"
    if has_svc_uuid:
        return "service-uuid-not-in-sig"
    if has_name:
        return "name-pattern-miss"
    return "other"


# Service-data UUID → maintainer-of-the-day decoder package, for the
# benefit of future readers wondering whether to grow the dependency
# tree. Keep updated as Home Assistant's BLE ecosystem moves.
_SERVICE_DATA_HINTS = {
    "FE95": "Xiaomi MiBeacon — pip install xiaomi-ble",
    "FCD2": "Bose — community decoder, no clean PyPI release",
    "FDEE": "Huawei — no public python decoder",
    "FD5A": "Samsung SmartTag / Apple Find My — no clean PyPI release",
    "FCF1": "Google Fast Pair — pip install fast-pair-ble (limited)",
    "FE9F": "Google Smart Setup",
    "FE2C": "Google Cast",
    "FED2": "Microsoft Surface",
    "FD2D": "Tile — community decoder",
    "FEAA": "Eddystone — pip install ibeacon (also handles iBeacon)",
    "FF22": "Sony LinkBuds",
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=None,
        help="path to a helper-raw.jsonl file; defaults to spawning helper",
    )
    parser.add_argument(
        "--lines", type=int, default=800,
        help="cap the helper sample at N JSONL lines (default: 800)",
    )
    args = parser.parse_args()

    if args.input is not None:
        text = args.input.read_text()
        source = str(args.input)
    else:
        text = capture_via_helper(args.lines)
        source = "live helper capture"

    rows = dedup(text)
    print(f"source: {source}")
    print(f"unique advertising devices: {len(rows)}")
    print()

    vendors = load_vendors()
    members = load_member_uuids()

    resolved = sum(
        1 for d in rows.values() if resolve_vendor(d, vendors, members)
    )
    unresolved = [
        d for d in rows.values() if not resolve_vendor(d, vendors, members)
    ]
    print(f"vendor resolved: {resolved} ({resolved/len(rows):.1%})")
    print(f"vendor unresolved: {len(unresolved)} "
          f"({len(unresolved)/len(rows):.1%})")
    print()

    if unresolved:
        buckets: collections.Counter = collections.Counter(
            categorize_unresolved(d) for d in unresolved
        )
        print("Unresolved breakdown — what would close each:")
        for k, v in buckets.most_common():
            print(f"  {v:3d}  {k}")
        print()

    sd_uuids: collections.Counter = collections.Counter()
    for d in rows.values():
        sd = d.get("service_data") or {}
        if isinstance(sd, dict):
            for k in sd.keys():
                sd_uuids[k] += 1
    if sd_uuids:
        print(f"service_data UUIDs seen ({sum(sd_uuids.values())} occurrences "
              f"across {len(sd_uuids)} unique UUIDs):")
        for uuid, n in sd_uuids.most_common():
            hint = _SERVICE_DATA_HINTS.get(uuid.upper(), "")
            print(f"  {n:3d}  {uuid}  {hint}")
        print()

    cid_misses: collections.Counter = collections.Counter()
    for d in unresolved:
        cid = d.get("manufacturer_id")
        if isinstance(cid, int):
            cid_misses[cid] += 1
    if cid_misses:
        print(f"unresolved rows by manufacturer_id "
              f"({sum(cid_misses.values())} occurrences) "
              f"— vendor-private cids that SIG hasn't published:")
        for cid, n in cid_misses.most_common(20):
            print(f"  {n:3d}  cid={cid} (0x{cid:04x})")
        print()


if __name__ == "__main__":
    main()
