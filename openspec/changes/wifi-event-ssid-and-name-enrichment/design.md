# Design

## D1. Why add SSID, not "do better AP-name lookup"

The current event lines fall back to raw BSSIDs because the user's
`aps.yaml` doesn't have entries for those BSSIDs. That's expected
— filling the inventory is the user's job and `format_bssid` already
does the right thing when entries exist.

What the user is *actually* asking for is the SSID. The SSID is
populated by macOS automatically for every association the user
makes (it's the network's broadcast name); we don't need the user
to maintain any extra config to get it. Adding SSID to the event
gives the user a stable, always-available label for "which
network", independent of how thorough their `aps.yaml` is.

## D2. Where the SSID is read

Both event sources already have access to the SSID at emission
time:

- `WiFiPoller._maybe_emit_roam` runs against `ConnectionUpdate`,
  which carries `Connection.ssid`. The poller already remembers
  `_last_bssid` to detect roams; we add a parallel `_last_ssid`
  field updated in lockstep.
- The environment monitor's `RFStirEvent` emission happens
  inside `EnvironmentMonitor.observe()`, which receives the
  current `Connection` snapshot from the poller. The monitor
  already pulls `bssid` off it; we pull `ssid` too.

No new IPC, no new threading, no new awaits.

## D3. Field-default + serialisation

`RoamEvent` and `RFStirEvent` are `@dataclass(frozen=True,
slots=True)`. Adding a default-None field is safe (existing
constructors that omit the field still work); reordering existing
fields is not — Python forbids non-default-before-default fields,
and serialisation order in `event_to_jsonl` matters for analysis
reproducibility.

So the new fields land at the **end** of each dataclass:

```python
@dataclass(frozen=True, slots=True)
class RoamEvent:
    timestamp: datetime
    previous_bssid: str
    previous_channel: int | None
    new_bssid: str
    new_channel: int | None
    previous_ssid: str | None = None  # NEW
    new_ssid: str | None = None       # NEW
```

```python
@dataclass(frozen=True, slots=True)
class RFStirEvent:
    timestamp: datetime
    bssid: str
    location: str
    magnitude_db: float
    duration_s: float
    confidence: str
    mode: str
    ssid: str | None = None  # NEW
```

`event_to_jsonl` (in `event_log.py`) writes existing keys first
and appends the new keys to the end of the dict. JSONL consumers
that ignore unknown keys see no change.

## D4. Renderer — when to show SSID, when to skip

Roam event line, two cases:

- **Same SSID on both sides** (band switch within an ESS, or
  inter-AP roam keeping the same network): render
  `SSID: <name>` once.
- **Different SSIDs** (the user roamed off one network and onto
  another — rare in practice, but possible): render
  `SSID: <prev> → <new>`. The `→` matches the BSSID arrow on
  the same line.

When both `previous_ssid` and `new_ssid` are None, the SSID
segment is omitted entirely — adding `SSID: n/a` is worse than
just leaving it out.

RF stir event line: `· SSID <name>` segment is appended to the
existing `<location> 处 RF 扰动` body when `event.ssid` is
populated. Omitted when None (location alone is enough; the
user can correlate against the connection panel).

ZH catalog keys are added for the new wrapper strings (`SSID:
{ssid}`, `SSID: {prev} → {new}`, `SSID {ssid}`).

## D5. Hidden + redacted SSID edge cases

- **Hidden SSID** (CoreWLAN returns `""`): the renderer treats
  empty-string the same as None — segment omitted. A hidden SSID
  has nothing useful to show.
- **TCC-redacted SSID** (CoreWLAN returns `None` because Location
  Services is denied): same — segment omitted. The user already
  sees the redacted state in the connection panel.
- **Inter-AP roam with one side TCC-redacted** (rare; the poller
  loses Location between the previous and new association):
  the renderer surfaces whichever side is known. If neither, the
  segment is omitted.

## D6. Test surface

`tests/test_tui_helpers.py` already covers the existing event
formatters. We add:

- `test_format_roam_event_includes_ssid_when_same_on_both_sides`
- `test_format_roam_event_renders_ssid_transition_when_different`
- `test_format_roam_event_omits_ssid_segment_when_both_none`
- `test_format_roam_event_omits_ssid_segment_for_hidden_ssid`
- `test_format_rf_stir_event_includes_ssid_when_present`
- `test_format_rf_stir_event_omits_ssid_segment_when_none`

Plus a roundtrip test in `tests/test_event_log.py`:
- `test_event_to_jsonl_roundtrip_roam_with_ssid_pair`
- `test_event_to_jsonl_roundtrip_rf_stir_with_ssid`

And a poller test:
- `test_roam_event_fills_ssid_from_connection_updates`

The environment monitor side picks up coverage by widening one
existing test in `tests/test_environment.py` to assert the
emitted event carries `ssid`.
