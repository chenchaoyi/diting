# Design

## D1. Where the BSSID dedup runs

Two candidate sites:

- **A.** `helper/Sources/diting-tianer/main.swift::runScanAndDumpJSON`
  — dedup in the Swift helper before it serialises the JSON.
- **B.** `src/diting/_helper.py::scan` — dedup the Python list parsed
  from the helper JSON.

We pick **B**. Reasons:

- The helper writes one JSON document per scan and exits; the Python
  side is the long-lived process holding history rings, latency
  aggregates, and the inventory. Dedup at the boundary the long-lived
  process owns avoids a wire-format change (the helper schema stays
  at 4) and lets older helpers benefit from the fix without a
  re-install.
- The direct CoreWLAN fallback path in `macos_backend.scan` also has
  the same risk; layering dedup on top of both code paths in one
  place keeps the invariant uniform.
- The helper is ad-hoc-signed and bumping its cdhash re-prompts the
  user for TCC — avoided when the fix is Python-only.

Concretely: `_helper.scan` builds `out: list[ScanResult]` row by row.
We change the build step to use a `dict[str, ScanResult]` keyed by
lowercase BSSID; on collision keep the entry with the higher RSSI
(`max` by `rssi_dbm`, treating `None` as `-200`). At the end we
return `list(by_bssid.values())`, which preserves insertion order
in Python 3.7+. Rows whose BSSID is `None` are kept as-is (they're
already rare — only the redacted-helper path produces them).

## D2. Tx Rate idle cache scope + invalidation

The Tx rate originates from `iface.transmitRate()` on each poll
(currently ~1 s). It is a single scalar attached to the
`Connection` model, not to scan rows.

**Cache key:** `(ssid, bssid)` of the associated interface. Cache
is invalidated when either changes (roam, association loss,
reassociation). Same-AP scan tick with rate=0 → surface cached.
Different-AP tick → cached is dropped, no annotation.

**Where the flag is exposed.** `Connection.tx_rate_idle: bool`
(new), defaulting to `False`. The flag is set only when the
current poll returned 0 / None but a valid prior rate was within
the cache window. The TUI reads the flag to decide whether to
append `" (idle)"`.

**Cache window.** The cache holds the last non-zero rate from
the same association indefinitely while the association lasts.
We don't add a time decay — a TX rate that was correct 30 s ago
on the same AP is still a reasonable display, since the alternative
is `n/a`. The cache resets on disassociate; if the user roams and
comes back to the same AP, the cache will refill on the next
non-zero observation, which is fine.

**Why not show `(idle)` always, even on first poll?** Because we
have no last-known value to use — we'd be showing `n/a (idle)`,
which is worse than `n/a`. The flag only fires when the cached
value is being substituted in.

## D3. Services placeholder — why `_label` was wrong

`_label(name, value)` is the spec'd helper for "indented row with
a left-aligned label column and a value to the right". It treats
`value is None` as "no data" and appends an em-dash (`—`). The
placeholder line `(none advertised)` is not a label-value pair;
it's a single explanatory string. Misusing `_label` for it
appended an em-dash that read as a stray glyph.

**Fix.** Bypass `_label` for these placeholder lines; render them
as standalone dim-italic lines with the same two-space indent
`_label` produces:

```python
out.append("  " + t("(none advertised)") + "\n",
           style="dim italic")
```

Sweep for the same anti-pattern across `_section_services`,
`_section_extra_uuids`, `_section_other_services`. Each
either has the same construct now or could acquire it later
without us noticing — better to fix all today.

## D4. Bonjour by-host sort — column semantics

In the existing service-row mode, each row carries
`vendor / name / services (one) / age / host`. In by-host mode
the same columns can be reused, but `services` becomes a
comma-joined list:

```
vendor              name                       services                                       age  host
Apple, Inc.         Blue Pod                   AirPlay, AirPlay audio, Apple Companion, Home   20s  Blue-Pod
```

The services column SHALL be truncated to the column width with
an ellipsis when it overflows (use `fit_cells`, never raw `str`
slicing — service-type names are ASCII so no CJK width risk
yet, but the helper is uniform).

The sort key in by-host mode is "freshest host first" (newest
`last_seen` across the host's services), so a HomePod that
re-advertises lands at the top. Within the row, services are
joined in a stable order (alphabetical by service-type short
name).

`s` cycles: `service` (default) → `by-host` → back to `service`.
The footer keystroke hint already says `s Sort`, so no new
binding label is needed.

## D5. Unknown-vendor label parity

The mDNS diagnostics "Top vendors" line is rendered by
`_bonjour_diagnostics_lines` (or whatever the analogue is — find
the function). It currently formats the unknown bucket as
`? <n>`. The same panel's column placeholder, and every other
panel's, uses `(unknown)`. Picking the column convention keeps
the page readable left-to-right ("(unknown) 5" reads as a count
of unknowns; "? 5" reads as a question).

Pure rendering change. No data-model implication.

## D6. Surface impact

- Scan dedup affects every consumer of `scan()` (Python).
  `MacOSWiFiBackend.scan` returns the deduped list directly; the
  diagnostics panel's "Visible BSSIDs 24 total" will start
  reading the actual distinct count, which is the intent.
- Tx-rate cache touches `MacOSWiFiBackend.snapshot` (or
  equivalent — wherever `Connection` is constructed). The new
  `tx_rate_idle: bool` field on `Connection` is additive;
  existing callers ignoring it see no change.
- BLE detail services empty state — text-only.
- Bonjour by-host mode — additive sort option; default mode
  unchanged.
- Unknown-vendor label — text-only.
