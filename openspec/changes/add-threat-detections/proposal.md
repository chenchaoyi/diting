# Threat detections — defensive security insights

## Why

Phase 2 turned the enriched stream into operational *insights* (familiarity
clusters, link/loss heuristics). Phase 3 adds the defensive-security tier: a
small set of **threat** detectors that flag when the user's wireless
environment looks *hostile* rather than merely noisy — an AP impersonating a
trusted SSID, a burst of forced disconnects, an unfamiliar device that trails
the user between locations. These are exactly the "valuable changes" the system
exists to surface, at the highest stakes.

Threats are defensive: they alert the *owner* of the machine that their own
environment may be compromised. They use only authoritative, hard-to-spoof
signals (BSSID, OUI/vendor, disassociation timing, the rotation-folded device
identity) — never a user-controllable name — per the project's
no-name-based-classification rule.

## What Changes

- **A `critical` severity** for threat-class insights, above `warn`: salience
  `high`, always notifies, and renders as a distinct `[THREAT]` row. Threats
  reuse the existing `insight` event type + engine plumbing (JSONL, TUI,
  watchdog) — a threat is a `critical`-severity insight with a security `code`.

- **A threat engine** (new `src/diting/threats.py`), a sibling of the insight
  engine: it `observe`s the same enriched stream into bounded state and
  `collect(now)` emits threat insights (per-code/-target cooldown). Hermetic +
  testable. Detectors:
  - **`evil_twin`** — the user associates/roams onto the same SSID via an AP of
    a *different vendor* than already seen for that SSID this session (OUI
    mismatch under one network name → impersonation signal).
  - **`deauth_storm`** — a burst of disassociations in a *tight* window (an
    acute forced-disconnect pattern, distinct from the slower
    `repeated_disassociates` operational insight). Honestly framed: inferred
    from `link_state` transitions, since CoreWLAN does not expose 802.11
    management frames.
  - **`follows_you`** — an *unfamiliar* BLE device whose presence spans ≥2
    distinct location epochs (a `network_change` advances the epoch) in one
    session: a device that moved with the user.

## Impact

- Affected specs: a NEW `threats` capability (the engine + detector contract),
  `insights` (the `critical` severity), `anomaly-watchdog` (critical insights
  notify).
- Affected code: new `src/diting/threats.py`; `salience.py` (`critical`→high),
  `_watchdog.py` (notify on `critical`), `insights.py` (`format_insight_summary`
  gains the threat-code one-liners) + `i18n.py` (EN↔ZH), `tui.py` (construct the
  threat engine, register its observer, drain it in the collect timer; the
  `[THREAT]` render branch).
- **Scope limit (honest):** `security_downgrade` is DEFERRED — detecting a
  weaker-than-expected cipher needs the connection `security` on the wire, which
  is a proper `companion-protocol` field addition (paired version bump), not a
  desktop-local stripped field. Cross-session "follows-you" (using the
  familiarity store's payload-keyed history) is also deferred; this phase is
  within-session. Threats stay **desktop-local** (macOS notification + TUI +
  JSONL) like all insights — forwarding them to the phone rides the same
  deferred "insights on the wire" protocol change. `evil_twin` only sees APs the
  user actually associates/roams to (not passive scan twins), and uses vendor
  mismatch — a same-vendor twin evades it; this limitation is documented.
- No name-based input: detectors key on BSSID / OUI-vendor / disassociation
  timing / the rotation-folded device identity, never an SSID-as-trust or a
  Bonjour/host name.
