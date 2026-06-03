# Design — event salience + salience-gated push

## The tier model

Salience is a 4-level ordered tier, not a float — easier to reason about, to
gate on, and to render later:

```
noise (0) < low (1) < notable (2) < high (3)
```

`salience(payload) -> str | None`. Returns `None` for types we don't score
(`session_meta`, `connection_update`/`link_state` control lines we don't want
ranked) so `_emit` omits the field; otherwise one of the four tiers.

### Scoring rules (first match wins)

Intrinsic anomalies — salient regardless of familiarity:

| type | tier |
|---|---|
| `loss_burst` | `high` (real loss always matters) |
| `rf_stir` confidence `high` | `high`; `medium` → `notable`; `low` → `low` |
| `latency_spike` | `notable` |
| `network_change` | `notable` |
| `link_state` disassociated | `notable`; associated → `low` |

Arrivals — familiarity-weighted (`ble_device_seen`, `bonjour_service_seen`,
`lan_host_seen`, `roam`):

| familiarity | tier |
|---|---|
| `habitual` | `noise` (the everyday ambient norm — suppress) |
| `occasional` | `low` |
| `returning` | `notable` (was habitual, back after a long gap) |
| `first_time` | `notable`, bumped to `high` when a BLE arrival is close (`rssi_dbm >= -60`) |
| absent (no store) | `low` — never invent `noise`; preserves pre-store push behaviour |

`roam`: `band_switch` kind → `low` (routine radio hop); otherwise by the AP
familiarity already on the payload.

Departures (`*_left`) and `lan_host_dhcp_rotation` → `noise` / `low`. At-launch
BLE warmup (`at_launch: true`) is capped at `low` so the startup environment
dump never elevates to `notable`.

### Why centralise in `_emit`

Every emitted payload flows through `EventLogger._emit`, and `familiarity` is
already stamped by the `emit_*` method just upstream. Computing salience there
means:
- one call site, not the 8 scattered emit sites;
- the score sees the *final* payload (familiarity included);
- both the JSONL writer and the observer tap (companion sink) receive the
  same stamped dict — no second computation, no drift.

`_emit` adds `payload["salience"]` (when non-None) before tapping the observer
and writing.

## Push gate reads, never recomputes

`PushPolicy.should_push` reads `payload.get("salience")` — it does NOT import
the scorer. Rationale: the sink receives the already-stamped payload, so the
field is authoritative; and the policy's unit tests build bare payloads, where
a missing salience must be a **no-op pass-through** (gate only suppresses on
*positive* low-salience evidence). Order inside `should_push`:

1. type ∈ push_types? (unchanged — still excludes `*_left`, `session_meta`)
2. **salience gate (new):** if `salience` present and its tier `< threshold`
   (default `low`) → drop. Absent salience → skip this gate.
3. rf_stir confidence gate (unchanged)
4. per-(type,target) silence window (unchanged)

The default threshold `low` means only `noise` is dropped — i.e. habitual
arrivals + departures. Everything else flows to the existing gates. The
threshold is configurable (`DITING_PUSH_MIN_SALIENCE`, default `low`) so a user
can demand `notable`+ for a quieter phone.

This layering guarantees the change can only *reduce* push volume; with no
familiarity store wired, no arrival is ever `noise`, so push behaviour is
byte-for-byte the same as today.

## Wire safety

`salience` is desktop-local in Phase 2a — the push decision is made on the
desktop before sealing, so the phone never needs the field. The companion sink
strips `{"familiarity", "salience"}` before sealing (mobile runs strict
`validate_event`, which rejects unknown keys). The JSONL log keeps both. Mobile
salience ranking is a later coordinated `companion-protocol` version bump.

## Alternatives considered

- **Float score 0..1.** Rejected: harder to gate/render, invites false
  precision over what is a coarse ranking.
- **Salience on the event dataclasses** (so the TUI modal can highlight rows).
  Deferred: would thread a field through every dataclass + emit site for a
  cosmetic win; the modal re-style is Phase 2b. Keeping salience payload-only
  keeps this slice to ~4 files.
- **Recompute salience inside the push policy.** Rejected: duplicate logic, and
  the policy would then need the scorer + familiarity inputs it doesn't carry.
  Reading the stamped field is simpler and keeps one source of truth.
