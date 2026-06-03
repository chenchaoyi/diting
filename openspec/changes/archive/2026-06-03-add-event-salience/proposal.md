# Familiarity-weighted event salience + salience-gated push

## Why

Phase 1 gave every seen event a `familiarity` class but nothing consumes it
yet. Meanwhile the companion push path still fires on *every* push-type
transition gated only by a blunt per-target silence window — so the user's own
habitual phone re-appearing pushes exactly like a stranger's device walking in.
That is the flood the user hit ("疯狂滴给我发送推送通知"): volume without
ranking.

This is Phase 2a — the keystone of the event-design deepening: a single
**salience** score that ranks each event by *how much it should grab
attention*, weighting the Phase-1 familiarity class against the event's
intrinsic kind and signal strength. The first consumer is the push gate:
known-routine arrivals stop pushing, genuinely new / anomalous ones still do.

## What Changes

- **A pure salience scorer** (new `src/diting/salience.py`): `salience(payload)
  -> tier` over `noise` / `low` / `notable` / `high`, computed from the wire
  payload (which already carries `familiarity` after Phase 1). Familiarity-
  weighted: a `habitual` arrival is `noise`, a `first_time` / `returning`
  arrival is `notable` (a close first-time BLE device is `high`); intrinsic
  anomalies (`loss_burst`, high-confidence `rf_stir`, `latency_spike`,
  `network_change`, disassociation) score `notable`/`high` regardless of
  familiarity; departures (`*_left`) are `noise`. When familiarity is absent
  (no store) the scorer never *invents* low salience — arrivals stay `low` so
  current push behaviour is preserved.

- **Salience stamped onto the event** centrally in `EventLogger._emit` (the one
  choke point all payloads flow through, just downstream of familiarity), as an
  optional `salience` field — additive, None-omitted, recorded in the JSONL so
  the offline analyzer + later phases can rank on it.

- **Salience-gated push**: `PushPolicy.should_push` reads `payload["salience"]`
  and drops anything below a configurable threshold (default `low`, i.e. only
  `noise` is suppressed) BEFORE the existing rf_stir-confidence + silence-window
  gates. The gate can only *reduce* pushes; when no salience is present it is a
  no-op, so unpaired / pre-store behaviour is unchanged.

## Impact

- Affected specs: a NEW `salience` capability (the scorer's contract), `events`
  (events gain an optional `salience` field), `companion-bridge` (push gated on
  salience; sink strips the desktop-local field before sealing).
- Affected code: new `src/diting/salience.py`; `src/diting/event_log.py`
  (stamp salience in `_emit`); `src/diting/companion/push_policy.py` (read +
  gate); `src/diting/companion/sink.py` (strip `salience` alongside
  `familiarity`).
- **Scope limit (honest):** this slice adds the salience score + the push gate
  only. It does NOT add insight events, push-insights beyond the gate, or
  live-ify `analyze.py` — those are Phase 2b / 2c. The TUI events modal is not
  re-styled here (salience is not yet on the in-ring dataclasses). Salience
  stays desktop-local (stripped from the companion wire, like `familiarity`);
  mobile salience ranking is a later coordinated `companion-protocol` change.
- No name-based input: salience reads only the authoritative payload fields
  (type, familiarity — itself authoritatively keyed — signal strength), never a
  Bonjour name or hostname.
