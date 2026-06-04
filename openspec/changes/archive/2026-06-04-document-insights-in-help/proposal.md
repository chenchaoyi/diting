# Document the insight/threat layer in the help + basics modals

## Why

The in-app `?` help and `b` basics glossary predate three shipped layers and a
shipped binding, so a real-environment audit flagged them as stale:

- The familiarity → salience → **insight** → **threat** layers (#148–#151)
  produce `[INSIGHT]` / `[THREAT]` rows in the events modal and drive `--notify`,
  but neither modal explains what they are.
- The companion pairing screen (`k`, shipped #140) is in the footer's Modals
  group but the help modal's Bindings list never listed it, and the footer
  requirement still enumerates only `events, help, basics` ("eight primary
  bindings") — falsified the moment companion landed.
- The `--notify` help text still claimed monitor-anomaly-only, omitting that a
  note / warn / threat-level insight or threat now also notifies (and forwards
  to a paired phone).

The glossary opens with "every term diting shows in the dashboard" — a promise
broken once `[INSIGHT]` / `[THREAT]` / familiarity classes appear with no
definition.

## What Changes

- Help modal (`_help_content`): list the companion `k` binding; add an
  **Insights & threats** section explaining `[INSIGHT]` (device cluster,
  repeated disconnects, loss, jitter, band-steering) and `[THREAT]` (evil-twin,
  deauth-storm, follows-you, security-downgrade), the familiarity classes, and
  the authoritative-signal keying; revise the `--notify` text to cover the
  TUI insight/threat path.
- Basics glossary (`_basics_content`): add an **Insights & threats** section
  defining `Familiarity`, `INSIGHT`, `THREAT`.
- `i18n.py`: matching ZH for every new / changed EN help+glossary key
  (EN↔ZH parity).
- Spec: correct the stale footer requirement to reflect the shipped companion
  binding; record that the help + basics modals document the insight/threat
  layer.

No runtime behavior changes — documentation catching up to already-shipped,
already-specced capabilities.

## Impact

- Affected specs: `tui-shell` (footer binding enumeration; help/basics content).
- Affected code: `src/diting/tui.py` (`_help_content`, `_basics_content`),
  `src/diting/i18n.py` (ZH catalog).
- No new fields, no new bindings — `k` already exists and is footer-exposed.
