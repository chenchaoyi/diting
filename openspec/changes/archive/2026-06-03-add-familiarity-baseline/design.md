# Design — familiarity / baseline layer

## The store

`src/diting/familiarity.py` — `FamiliarityStore`, a process-scoped, persistent
record of every entity diting has ever observed, keyed by a stable identity.

### Identity key (authoritative only — never a spoofable name)

`familiarity_key(...)` returns a namespaced string:

- **BLE** — `ble:<payload>` where `<payload>` is the non-Apple, non-trivial
  `manufacturer_hex` (the same stable per-device token the v1.11.x payload
  fusion uses); fall back to `ble:vn:<vendor_id>/<name>` when there is no usable
  payload (Apple, header-only, or absent). NEVER the rotating UUID.
- **Wi-Fi AP** — `ap:<bssid>` (SSID kept as a record field, not in the key).
- **LAN host** — `lan:<mac>` (lowercased).
- **Bonjour** — `bonjour:<service_type>/<instance>` (the announced service
  identity, not a user-set display name).

### Per-entity record

```
key, kind ('ble'|'ap'|'lan'|'bonjour'),
first_seen_ever, last_seen,           # ISO-8601 local
total_sightings: int,
days: set[str] -> distinct_days_seen  # 'YYYY-MM-DD' the entity was seen
dwell_ewma_s: float | None            # typical dwell, EWMA over seen->left spans
rssi_band: int | None                 # coarse typical RSSI bucket (BLE/AP), optional
```

### Familiarity class (defaults; scene-tunable in a later phase)

Computed from the record state BEFORE recording the current sighting, so the
very first observation reads `first_time`:

- `first_time` — no prior record (this is the first time ever).
- `habitual` — `distinct_days_seen >= 3` (seen across ≥3 distinct days).
- `returning` — was habitual AND `now - last_seen > 7d` then seen again.
- `occasional` — seen before but not yet habitual.

Thresholds are module constants (`_HABITUAL_DAYS = 3`, `_RETURNING_GAP_DAYS = 7`)
so a later scene-aware pass can tune them.

### Persistence + bounds

- A single JSON file (dict `key -> record`), default `./diting-familiarity.json`,
  `DITING_FAMILIARITY_STORE` env override — mirrors `DITING_COMPANION_STATE` /
  the calibration file. **Git-ignored** (holds real BSSIDs/MACs/fingerprints);
  `diting-familiarity.example.json` is the public shape.
- Loaded once at startup; updated in memory; persisted periodically + on clean
  shutdown. **Fail-soft read** (corrupt file / record → skip, never raise — like
  `ReportStore.readAll`).
- **Bounded**: cap at `_MAX_ENTITIES` (default 5000) and age out entities unseen
  for `_AGE_OUT_DAYS` (default 30) on load/save, so it can't grow without limit.

### API (hermetic, injectable path — testable without a real environment)

```
store = FamiliarityStore(path)                 # load (fail-soft)
cls = store.observe_seen(key, kind, now, rssi) # classify (pre-update) THEN record; returns the class str
store.observe_left(key, dwell_s)               # fold dwell into the EWMA
store.flush()                                   # persist (bounded + aged)
```

## Wiring + the `familiarity` field

- Each seen-emit site computes its `familiarity_key`, calls `observe_seen`, and
  sets the returned class on the event's new optional `familiarity` field:
  `ble_device_seen`, `bonjour_service_seen`, `lan_host_seen`. `roam` carries the
  AP's familiarity (`ap:<new_bssid>`). `left` sites call `observe_left` for the
  dwell EWMA but carry no class.
- The field is **optional** on the event dataclasses + JSONL (`None` omitted, per
  the existing "None fields omitted" rule), so the JSONL key set stays stable for
  consumers that ignore it.

## The wire-compat decision (important)

`companion-protocol`'s `validate_event` is **strict** — it fail-closes on unknown
fields (`test_validate_rejects_unknown_field`). So a new field on a forwarded
event would make the mobile consumer **reject the whole event**, breaking sync.
A wire field therefore needs a coordinated protocol bump + mobile re-vendor.

**Decision for Phase 1: `familiarity` is desktop-LOCAL.** It rides the local
JSONL log, the in-memory ring (TUI), and `analyze.py` — but the companion sink
**strips local-only fields** (`{"familiarity"}`) from the payload before sealing,
so the wire contract, fixtures, and mobile are untouched. Crossing the wire is a
deferred, coordinated change (a later phase / the mobile mirror). This keeps
Phase 1 contained and cannot break live companion sync.

## Out of scope (Phases 2–3)

No salience score, no insight/second-order events, no push/log surfacing change,
no threat detections. Phase 1 only produces + persists the signal; nothing ranks
or routes on it yet.

## Testing approach

- Pure store tests (injected path): key derivation per kind (BLE payload vs
  fallback; never name-as-key); class thresholds (first_time → occasional →
  habitual → returning); dwell EWMA; persistence round-trip; fail-soft on corrupt
  records; bounded cap + age-out.
- Event tests: seen events carry `familiarity` when a store is wired, omit it
  when absent; JSONL key stability.
- Companion test: the sink strips `familiarity` before sealing (wire stays clean,
  mobile-safe).
