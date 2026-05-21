# align-events-vocabulary

## Why

A TUI audit on 2026-05-21 with `DITING_LANG=en` and
`DITING_LANG=zh` flagged two A1-era post-ship issues:

**1. EN UI says "joined" but the event is `*_seen`.** Every
`ble_device_seen` / `bonjour_service_seen` / `lan_host_seen`
event renders in EN as `device joined: ` / `service joined: ` /
`host joined: `. ZH translates the same EN keys to `设备出现：`
/ `服务出现：` / `主机出现：` — i.e. "appeared / seen". The
JSONL `type` field, the BLEPoller's internal vocabulary, the
spec's MODIFIED requirement landed in fix-ble-left-dedup all
say "seen". "Joined" reads like *paired / associated* — but
the event fires on the first passive observation, including
random strangers' phones walking past. The EN wording is
misleading and disagrees with ZH and the JSONL schema. EN and
ZH agree on the sibling `*_left` events (`device left` /
`设备消失`), so only the seen-side has drifted.

**2. Events-filter docs claim 1/2/3/4/0; A1 added 5/6/7.**
The EventsScreen filter cycle has eight buckets since A1 —
`tui.py:782-784` binds `5` / `6` / `7` to `ble` / `bonjour` /
`lan` and `action_set_filter` accepts them. The bindings work.
But four user-facing strings still say "1/2/3/4/0":

- `src/diting/tui.py:884` — events-modal footer hint
- `src/diting/i18n.py:1248-1249` — that footer's ZH value
- `src/diting/tui.py:612` — help-modal "Events modal (m)" paragraph
- `src/diting/i18n.py:880, 886` — the help-modal paragraph EN + ZH

The new BLE / Bonjour / LAN filters are undiscoverable without
reading the source. (The HelpScreen test
`test_events_screen_filter_cycle_has_eight_buckets` asserts the
filter-bucket cycle has eight entries, but not that the key-list
in the prose matches.)

## What changes

- Rename three EN i18n catalog keys to match the canonical event
  vocabulary: `device joined: ` → `device seen: `,
  `service joined: ` → `service seen: `, `host joined: ` →
  `host seen: `. ZH values are unchanged (`设备出现` etc. already
  mean "appeared / seen").
- Update the call sites in `tui.py:1947`, `:1970`, `:1993`.
- Extend the four "1/2/3/4/0" strings to "1/2/3/4/5/6/7/0" (or
  a more compact phrasing — see design.md).
- Update the `tui-shell` spec: the EventsPanel format bullets
  for the seven A1-added types switch from `joined` to `seen`,
  and the scenario example matches.
- Update three existing tests in `test_tui_helpers.py` that
  assert the old wording.

## Impact

- **EN UI** — three lines in the events panel and one events-modal
  footer hint change wording. No layout / width change.
- **JSONL log** — untouched; the canonical event type names
  (`ble_device_seen` etc.) are already correct and remain
  load-bearing identifiers.
- **ZH UI** — no change. ZH already used "出现" / "appeared / seen"
  for the seen events.
- **Spec** — `tui-shell` MODIFIED requirement around EventsPanel
  formatting. No new requirement, no removed requirement.
- **Tests** — three string-assertion flips. No semantic change.

## Affected code

- `src/diting/i18n.py` — three i18n keys + filter-footer hints
- `src/diting/tui.py:612, 884, 1947, 1970, 1993`
- `tests/test_tui_helpers.py:2659, 2692, 2725`
- `openspec/specs/tui-shell/spec.md:135-147` (delta target)
