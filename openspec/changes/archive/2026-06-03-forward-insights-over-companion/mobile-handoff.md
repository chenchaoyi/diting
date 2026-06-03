# diting-mobile handoff — companion-protocol v2 (`insight` events)

Pairs with **diting desktop PR #153** (`feat(companion): forward
insights/threats over the wire — desktop half (v2)`, squash `92bebf8` on
`main`). Desktop is the source of truth for the wire contract; this is the
mobile half. **Ship mobile v2 BEFORE the desktop release (v1.14) that forwards
insights** — otherwise the desktop sends v2 envelopes the phone silently drops.

---

## 0. What changed on the wire

`insight` is a new companion-protocol event type (incl. the `critical` threat
tier). The protocol major bumped **1 → 2**, but with **per-envelope minimum-
version stamping**: every *existing* event type still seals at `v1`, and **only
`insight` seals at `v2`**. Consequences for mobile:

- The relay path is unchanged (`/v1/...`), pairing still works, existing event
  envelopes are still `v1`.
- A phone that supports only `{1}` **abstains on the v2 insight envelopes and
  keeps receiving every other event** — this is the graceful-degradation
  guarantee. Verify your *current* shipped build does this (it should already:
  it gates each pulled envelope on `is_supported_version(env.v)`).
- A v2 phone (this update) adds `2` to its supported set and decodes both.

---

## 1. Re-vendor the protocol artifacts

Copy the regenerated artifacts from desktop `src/diting/companion/protocol/`
into the mobile repo's vendored `protocol/` and update the conformance
hashes. **`manifest.json` (protocol_version now `2`):**

```
schema/event.schema.json      80e24912810274962e72026592309721227827225c38fe7042b8a4e1a6a24234
schema/envelope.schema.json   9bb8f9f24a8e2416a2d04afeda19f66db470a4ff2f6a9904c4389a4661b1f8ff
schema/pairing.schema.json    9dcbcd2aa3cbe0e18f69cef30f93b98f155a921d807713ae5a321fdec13d991e
schema/apns-trigger.schema.json 33b064b2c4e9297c06b5e0c9976a81b4439a6c8f6ca1933da9beeb9cd0852160
fixtures/events.jsonl         2f6369f3840de3bc426396cb32470402a19e3f50aa899ab18f4123770b59e51f
fixtures/sealed-envelope.json 424293068c6bb0e5bea54fad08fb2ca8a4c7da964471d86677e0f6627738a694
fixtures/pairing.txt          08ee609275f7b8e4df6b4bf3daf04e0df838694bce22fc4087ee8b6140a4fc42
fixtures/apns-trigger.json    31d9e05d1f3733226a66c0c5238f9fc9905f6b8525e860476071eb69c120b0d0
fixtures/relay-auth.json      66cc5ea726270d34b40d6cce706d65221f99a107024b9b6ff3cd1c4a6beecf3c
```

The cross-repo conformance test (the one that already pins vendored artifacts to
`manifest.json` hashes) will fail until you re-vendor — that's the drift check
doing its job.

### Artifact diffs to expect

- **`event.schema.json`** — one new `oneOf` branch (top-level `additionalProperties:false`, but `detail` is an open object):
  ```json
  {
    "type": "object",
    "required": ["ts", "type", "code", "severity"],
    "properties": {
      "ts": {"type": "string", "pattern": "<the TS_PATTERN>"},
      "type": {"const": "insight"},
      "code": {"type": "string"},
      "severity": {"type": "string", "enum": ["info", "note", "warn", "critical"]},
      "detail": {"type": "object"}
    },
    "additionalProperties": false
  }
  ```
- **`envelope.schema.json`** — `v` enum widened: `{"type":"integer","enum":[1,2]}`.
- **`apns-trigger.schema.json`** — `c` enum gains `"insight"` (now `["ble","bonjour","env","insight","lan","link"]`).
- **`fixtures/events.jsonl`** — one new line (nested `detail`):
  ```json
  {"ts":"2026-05-20T12:00:15+08:00","type":"insight","code":"new_device_cluster","severity":"note","detail":{"count":3,"window_s":120}}
  ```
- **`fixtures/pairing.txt`** — bumped to `diting-pair://v2/...` (pairing rides the major). A v1 phone abstains on a v2 pairing (spec-sanctioned "newer protocol" notice); since desktop+mobile ship together this is moot.
- **`fixtures/sealed-envelope.json`** — **unchanged** (it seals a `link_state`, which stays `v1`). Good signal your per-envelope reasoning matches.

---

## 2. Dart decoder changes (mirror desktop)

1. **Supported versions.** Add `2` to the supported set (`{1, 2}`). This is what
   flips the phone from "abstain on insight envelopes" to "decode them." Keep the
   abstain-on-unsupported path for any future `v3`.
2. **`validate_event` mirror.** Add the `insight` type: required `code:String`,
   `severity:String` ∈ {info,note,warn,critical}, optional `detail:Object`
   **whose inner keys are NOT validated** (this is the `obj` tag — only assert
   it's a map/object; do not enforce a key set). Top-level stays strict
   (`additionalProperties:false`): reject unknown top-level keys as today.
3. **No producer logic needed.** `EVENT_MIN_VERSION` / per-envelope stamping is a
   desktop *seal* concern. Mobile only *decodes* whatever `env.v` it receives
   (if supported). Don't replicate the stamping map.

---

## 3. Render + notify

Severity drives presentation (mirror desktop's `tui._format_insight_event`):

| severity | row label | notify? |
|---|---|---|
| `info` | `[INSIGHT]` | no (log/timeline only) |
| `note` | `[INSIGHT]` | yes |
| `warn` | `[INSIGHT]` | yes |
| `critical` | `[THREAT]` (red) | yes |

The one-line summary is generated from `code` + `detail` **in the phone's own
i18n** (the desktop does NOT send localised text — JSONL/wire carry only `code`
+ structured `detail`). Implement the equivalent of desktop
`insights.format_insight_summary`. **Insight code catalog** (code → severity →
`detail` keys → desktop EN string):

| code | severity | detail keys | EN one-liner |
|---|---|---|---|
| `new_device_cluster` | note | `count`, `window_s` | "{n} unfamiliar devices appeared together" |
| `repeated_disassociates` | warn | `count` | "Wi-Fi dropped {n} times recently" |
| `loss_observed` | warn | `peak_loss_pct` | "Packet loss observed (peak {pct}%)" |
| `latency_without_loss` | note | `spikes` | "Latency spikes without loss — likely jitter" |
| `band_steering` | info | `roams`, `band_switches` | "AP band-steering: {n} roams, mostly band switches" |
| `evil_twin` | critical | `ssid`, `known_vendor`, `new_vendor`, `bssid` | "Possible evil twin: SSID {ssid} now on a {vendor} AP" |
| `deauth_storm` | critical | `count`, `window_s` | "Possible deauth storm: {n} rapid disconnects" |
| `follows_you` | critical | `identifier`, `locations` | "A device has stayed with you across {n} locations" |

Render an unknown future `code` by falling back to the raw `code` string (don't
crash) — desktop does the same. The doorbell push body already arrives as
cleartext (desktop sets the `push` summary sibling = this one-liner); use it
directly for the notification if you prefer not to re-localise.

---

## 4. Conformance + sequencing checklist

- [ ] Re-vendor `protocol/` artifacts; drift/conformance test green against the
      new `manifest.json` hashes (protocol_version 2).
- [ ] Add `2` to supported versions; `insight` to the Dart `validate_event`
      (open `detail`); fixtures (incl. the new insight line) all validate.
- [ ] Render `[INSIGHT]`/`[THREAT]` rows + notifications per the severity table;
      localise the code catalog.
- [ ] Regression: confirm a v1 envelope (e.g. `ble_device_seen`) still decodes,
      and a synthetic future `v3` envelope is abstained (not crashed).
- [ ] **Release mobile v2 before** the desktop v1.14 release.

---

## 5. Out of scope (still deferred, both repos)

- `security_downgrade` threat — needs the connection cipher as its own wire
  field (a further additive protocol change), not in v2.
