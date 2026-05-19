# Design

This change has two halves — a data-only OUI refresh and a
behaviour-affecting LANHost enrichment + modal layout. Both
arrived from the same real-environment audit so they ship
together.

## D1. Full IEEE OUI registry — what we sync

IEEE Registration Authority publishes the OUI registry as a CSV at
`https://standards-oui.ieee.org/oui/oui.csv`. The file is ~3-4 MB
(post-2024) and updates roughly monthly. The CSV's MA-L block
covers 24-bit OUIs — about 35-40k entries today. That's what we
want: 24-bit MAC prefixes mapping to vendor names.

CSV columns (the IEEE export):

```
Registry,Assignment,Organization Name,Organization Address
```

We keep only `MA-L` rows and ignore `MA-M` / `MA-S` (smaller
sub-allocations — out of scope for this MVP). Each row's
`Assignment` is the 24-bit OUI in `AABBCC` form; we normalise to
`aa:bb:cc` to match the existing dict key format.

## D2. Refresh script

`scripts/refresh_ouis.py` is a small CLI:

```bash
uv run python scripts/refresh_ouis.py
```

It hits the IEEE URL, parses the CSV, dedupes (~5% duplicate OUI
entries in the raw export), normalises keys, writes
`src/diting/data/wifi_ouis.json` with a refreshed `_meta` block
(source URL, fetch timestamp, license attribution).

Failure modes:

- IEEE unreachable → exit non-zero, leave the existing file
  untouched.
- Malformed CSV → exit non-zero. We surface the line number so
  the user can pull the raw CSV and check.
- Backwards compat: the dict shape is unchanged, just bigger.
  Callers (`load_ouis`, `lookup_oui_vendor`) get more entries
  without code changes.

## D3. Why not MA-M / MA-S in this pass

MA-M (28-bit) and MA-S (36-bit) registries cover ~10k more
vendors. Adding them requires:

1. Schema change in the data file (mixed key lengths or a
   nested structure).
2. `lookup_oui_vendor` tries the longest prefix first.

Both are doable but the ROI is uneven — MA-L already covers
~95% of devices on a typical network. We can add MA-M / MA-S
in a follow-up change when a real user surfaces a device the
MA-L lookup misses. Keeping this PR tighter ships value sooner.

## D4. Why RTT capture goes inside `_ping_one`

macOS `ping -c 1` writes one stats line per packet to stdout:

```
PING 192.168.1.1 (192.168.1.1): 56 data bytes
64 bytes from 192.168.1.1: icmp_seq=0 ttl=64 time=2.439 ms
```

The `time=X.XXX ms` segment is the RTT we want. Rather than
adding a separate parse layer, `_ping_one` captures stdout,
matches a regex (`r"time=([\d.]+)\s*ms"`), and returns
`(reachable, rtt_ms | None)`.

The previous version used `stdout=DEVNULL` to discard ping's
output — we now use `PIPE` and read it. Tiny cost; the output is
a few hundred bytes per call.

Failure handling: when `ping` exits 0 but stdout doesn't parse
(unlikely but possible on weird locale builds), we return
`(True, None)` — we know the host is reachable but the RTT was
unparseable. The modal renders Reachable but omits Latency.

## D5. Sweep returns per-IP results

The previous `_sweep` returned None — it was fire-and-forget,
populating the kernel ARP cache as a side effect. With RTT
capture we need to keep the per-IP result:

```python
async def _sweep(hosts) -> dict[str, tuple[bool, float | None]]:
    sem = asyncio.Semaphore(30)
    async def _one(ip):
        async with sem:
            return ip, await _ping_one(ip, timeout_ms=...)
    pairs = await asyncio.gather(*[_one(ip) for ip in hosts])
    return dict(pairs)
```

The merge step looks up each ARP-cached IP in this dict to set
`last_rtt_ms` and `last_reachable_at`. Hosts in the ARP cache
that we didn't sweep this tick (e.g. the user's own Mac, where
we always inject self into state without pinging) keep their
existing values.

## D6. LANHost field semantics

```
last_seen           — last time we saw an ARP entry (kernel cache)
last_reachable_at   — last time the host responded to ICMP
last_rtt_ms         — RTT of the most recent successful ping
```

Why two timestamps instead of one? They mean genuinely different
things:

- `last_seen` advances on every observation in the ARP cache,
  even if the host is no longer reachable. ARP entries persist
  for ~15-20 minutes on macOS.
- `last_reachable_at` advances only when ICMP got a reply this
  sweep. A host that's gone offline but still in ARP cache will
  have a fresh `last_seen` but a stale `last_reachable_at`.

The detail modal surfaces both, so a user investigating a
suspected-offline device can see the gap.

## D7. Modal layout

Network section, before:

```
Network
  IP             192.168.1.42
  MAC            de:ad:be:ef:00:01
  Reverse DNS    my-mac.local
```

After:

```
Network
  IP             192.168.1.42
  MAC            de:ad:be:ef:00:01
  Reverse DNS    my-mac.local
  Latency        2.4 ms              ← new
  Reachable      this sweep          ← new
```

Edge cases:

- Host never reached: `Latency` row omitted; `Reachable` shows
  `never`.
- Host was reached, now silent: `Latency` shows last-known RTT
  in dim italic; `Reachable` shows `Xm Ys ago`.

Bonjour services section, before — section omitted when empty.
After — always shown, with a `(no Bonjour services)`
dim-italic placeholder when there are none.

## D8. Performance impact

- Data file: 10 KB → 3 MB. One-time install size +3 MB. Negligible.
- Memory: dict grows from ~250 to ~35k entries. ~5 MB Python heap.
- First load: 50-100 ms parse (already lazy-cached on first lookup).
- Ping subprocess: stdout capture adds ~5 KB heap per call,
  released immediately. No measurable wall-clock impact.
- Lookup speed: O(1) dict lookup either way.

## D9. Test surface

`tests/test_lan.py` additions:

- `test_ping_one_returns_rtt_on_zero_exit` — mock the subprocess
  with canned `time=X.XXX ms` stdout, expect parsed RTT.
- `test_ping_one_returns_none_rtt_on_nonzero_exit` — exit 2, no
  stdout parse.
- `test_ping_one_returns_true_none_when_stdout_unparseable`.
- `test_sweep_returns_per_ip_results` — dict shape verified.
- `test_lan_host_last_rtt_ms_populated_from_sweep` — full merge
  path.
- `test_lan_host_last_reachable_at_preserved_when_silent` — host
  reached once, then silent next tick; field preserved.
- `test_oui_refresh_script_parses_csv` — small synthetic CSV
  fixture.

`tests/test_tui_helpers.py` additions:

- `test_lan_detail_modal_renders_latency_row_when_rtt_known`
- `test_lan_detail_modal_omits_latency_row_when_rtt_unknown`
- `test_lan_detail_modal_renders_reachable_row_with_relative_time`
- `test_lan_detail_modal_renders_never_when_never_reachable`
- `test_lan_detail_modal_renders_bonjour_empty_state_when_no_services`

## D10. Surface impact

- `src/diting/lan.py` — `_ping_one` return shape, `_sweep` return
  shape, `LANHost` two new fields, merge logic. ~60 LoC.
- `src/diting/tui.py::LANDetailScreen._render_body` — Latency /
  Reachable rows + Bonjour empty-state. ~30 LoC.
- `src/diting/i18n.py` — `Latency`, `Reachable`, `this sweep`,
  `never`, `(no Bonjour services)` entries.
- `src/diting/data/wifi_ouis.json` — refreshed from IEEE (~35k
  entries, ~3 MB).
- `scripts/refresh_ouis.py` — new file, ~80 LoC.
- `tests/test_lan.py` — additions, ~120 LoC.
- `tests/test_tui_helpers.py` — additions, ~80 LoC.
- `scripts/tui_snapshot.py::_switch_to_lan_inventory` — synthetic
  hosts updated with `last_rtt_ms` + `last_reachable_at`; new
  assertions on the modal.
- `README.md` + `docs/zh/README.md` — IEEE attribution; mention
  the refresh script.

No new third-party dependency.
