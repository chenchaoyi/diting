<sub>**English** · [中文](docs/zh/CHANGELOG.md)</sub>

# Changelog

All notable changes to diting (formerly `wifiscope` — see the
[Unreleased] BREAKING note) are recorded here. The format is
loosely based on [Keep a Changelog](https://keepachangelog.com/), and
the project follows [Semantic Versioning](https://semver.org/) where
practical. The leading `v0.x` line is allowed to break minor
behaviours between releases.

## [Unreleased]

## [1.14.0] — 2026-06-03

**Insights + threats reach your phone, and a fourth threat lands.** The
event-design layer from 1.13.0 was desktop-local; this release forwards it
over the companion bridge and adds `security_downgrade` to the threat tier.

### Added

- **Insights + threats over the companion wire.** `insight` is now a
  first-class `companion-protocol` event (the protocol major is **v2**), so
  the synthesized findings and threats from 1.13.0 forward to a paired phone —
  salience-gated, so `info`-level insights stay desktop-local while
  `note`/`warn`/`critical` (including every threat) push through. Forwarding
  uses **per-envelope versioning**: existing events stay v1, only `insight`
  rides a v2 envelope, so a phone that has not yet updated keeps receiving
  every other event and simply ignores insights until it does.
- **`security_downgrade` threat.** Re-associating to a familiar SSID at a
  weaker cipher than the strongest seen this session (e.g. WPA2 → open) now
  raises a `[THREAT]` — the payoff an evil twin is usually after. Like the
  other threats it keys on authoritative signal (the cipher), never the
  SSID itself.

### Notes

- **Update the phone app to its v2 build to see insights/threats there.** An
  older app silently ignores them (no breakage) until updated; the desktop
  shows everything regardless.
- The connection cipher (`security`) is recorded in the JSONL log on
  associated `link_state` lines but is desktop-local — it never crosses the
  companion wire.

## [1.13.0] — 2026-06-03

The **event-design intelligence layer.** diting stops treating every
transition as equal noise and starts answering, in four stacked layers,
"is this worth your attention?" — *is it familiar?* → *how salient is
it?* → *is it worth surfacing?* → *is it hostile?* Every layer keys on
authoritative, hard-to-spoof signals (BLE manufacturer payload, BSSID,
OUI/vendor, MAC, disassociation timing) — never a user-controllable name.
All of it is desktop-local; nothing new crosses the companion wire this
release.

### Added

- **Familiarity baseline.** A persistent, bounded store
  (`diting-familiarity.json`, git-ignored like the captures) records every
  entity diting sees under a stable identity — the BLE manufacturer
  payload (not the rotating UUID), AP BSSID, LAN MAC, Bonjour service —
  and classifies each `seen` event as `first_time` / `occasional` /
  `habitual` / `returning`. Seen events + `roam` carry an optional
  `familiarity` field in the JSONL log.
- **Salience scoring + a quieter phone.** Each event is ranked
  `noise` / `low` / `notable` / `high`, weighting familiarity against the
  event's kind and signal strength. The companion push now gates on
  salience: your own habitual devices re-appearing score `noise` and stop
  flooding the phone, while genuine newcomers and anomalies still get
  through. Tune the floor with `DITING_PUSH_MIN_SALIENCE` (default `low`).
- **Live insights.** A live engine synthesizes "valuable change" events —
  `new_device_cluster` (several unfamiliar devices arriving together) plus
  live-ified versions of the offline analyzer's heuristics
  (`repeated_disassociates`, `loss_observed`, `latency_without_loss`,
  `band_steering`). They surface as `[INSIGHT]` rows in the Events view, in
  the JSONL log, and — for note/warn severity — a macOS notification.
- **Threat detections.** A defensive-security tier flags a hostile
  environment as `[THREAT]` rows (and always-on notifications):
  `evil_twin` (you land on a same-SSID AP of a different OUI-vendor),
  `deauth_storm` (a tight burst of disconnects — inferred from association
  state, since CoreWLAN does not expose 802.11 frames), and `follows_you`
  (an unfamiliar BLE device that stays with you across a network change).

### Notes

- Insights and threats are desktop-local for now; forwarding them to a
  paired phone is a future companion-protocol change. `security_downgrade`
  detection is deferred for the same reason (it needs the connection
  cipher on the wire).
- CHANGELOG entries for 1.10.0–1.12.0 were not recorded at release time;
  see the Git history and GitHub Releases for those.

## [1.9.1] — 2026-05-30

Patch release. **Repairs the CN-network install path.** `ghproxy.com`,
the single hardcoded fallback mirror, was discontinued and now answers
`200` with an HTML landing page — which `install.sh` wrote into
`SHASUMS256.txt` and died on. The installer now walks an ordered chain
of live mirrors and validates every download (a `SHASUMS256.txt` only
if it yields a real 64-hex entry, a tarball only if it is valid gzip),
with `SHASUMS256.txt` fetched GitHub-direct-first so trust stays
anchored on GitHub. SHA256 verification stays mandatory. No change to
the TUI itself.

### Fixed

- **CN-network installs broke because `ghproxy.com` was discontinued.**
  The single hardcoded fallback mirror now answers `200` with an HTML
  landing page instead of proxying the file, which `install.sh` wrote
  into `SHASUMS256.txt` and then died `missing entry for …`. The
  installer now walks an ordered chain of live mirrors
  (`ghfast.top` → `gh-proxy.com` → `ghproxy.net`) and **validates every
  download** — a `SHASUMS256.txt` is accepted only if it yields a
  64-hex entry for the target tarball (HTML/empty `200` rejected), a
  tarball only if it is valid gzip; a bad response is skipped and the
  next mirror tried, and an exhausted chain aborts with a real error.
  `SHASUMS256.txt` is fetched GitHub-direct-first regardless of where
  the tarball came from, so trust stays anchored on GitHub.
  `DITING_INSTALL_MIRROR` now also accepts a custom `http(s)://` proxy
  prefix (a working or self-hosted mirror); `ghproxy` means the live
  chain (skip GitHub-first). SHA256 verification stays mandatory.

## [1.9.0] — 2026-05-29

Minor release. **One change to the BLE events surface, in two parts.**
Transition events now carry the same `device_type` / `device_class` the
BLE list already decodes — so a device the list shows as `iPhone` no
longer reads `(anonymous)` in the events — and `(anonymous)` is unified
to mean exactly one thing everywhere: a truly-silent broadcast. The
events modal folds the at-launch device census into one expandable
summary row so genuine mid-session transitions are no longer buried.
Additive JSONL only (new optional keys, None/False-omitted); no
permission or helper-schema change.

### Added

- **`device_type` / `device_class` on BLE transition events.**
  `BLEDeviceSeenEvent` and `BLEDeviceLeftEvent` now carry the Apple
  Continuity advertisement type and Nearby-Info device class the BLE
  list already decoded, so a device the list labels `iPhone` reads
  `iPhone` in the events too instead of `(anonymous)`. JSONL gains
  optional `device_type` / `device_class` keys (the Continuity type
  serialises under `device_type`, never `type` — the envelope owns
  `type`); both are omitted when absent, so old log lines stay
  diff-stable.
- **At-launch census fold in the events modal.** Every device already
  in range when diting launches fires a `seen` in the first ~12 s — a
  burst that buried the genuinely interesting mid-session events. The
  `m` modal now folds that startup census into one summary row
  (`session start · N devices already present (Apple ×8 · …)`) that
  expands on Enter / `→`. Nothing is hidden: the row expands to every
  folded device and the JSONL log keeps all of them. `BLEDeviceSeenEvent`
  gains an `at_launch` flag (JSONL key emitted only when true).

### Changed

- **`(anonymous)` now means one thing everywhere.** BLE event labels
  follow the same name cascade as the BLE list (helper name →
  `(rotating ID)` → type → device class → placeholder) via a shared
  resolver, and `(anonymous)` is reserved for the truly-silent case
  (no vendor, name, type, class, or service categories) — matching the
  diagnostic strip's count and the BLE list vendor cell. A device with
  a known vendor but no name now reads `(unknown)`, not `(anonymous)`.

## [1.8.0] — 2026-05-26

Minor release. **Four polished-UX features land together.** Three on
the installer / startup surface that the user sees in the first 30
seconds of their first encounter with diting, and one (the BLE
events merger) that finally tames the chronic noise the events modal
showed in dense BLE environments. None of these change a JSONL
contract or a permission surface; they all change what diting feels
like to use.

### Added

- **Pre-alt-screen startup splash with micro-motion brand mark.**
  The 6-15 s synchronous TCC-probe phase inside `_ensure_helper_ready`
  (a real Wi-Fi scan + a CoreBluetooth state poll) is now wrapped in
  a splash that renders the canonical pixel-art beast with a 4 Hz
  micro-motion animation (ear-twitch / eye-blink — silhouette and
  brand-orange palette stay 100 % identical across frames per the
  "do not redesign the mark" rule) plus a three-line ticking status
  block. Three-tier render ladder: interactive TTY ≥ 30 cols gets
  Rich `Live` with cycling frames; narrow TTY gets a static frame
  with `\r` updates; non-TTY (pipes, dumb terms) gets a single
  `diting starting...` line. Wall-clock latency unchanged —
  perceived-latency only. A later release can layer on TCC caching
  for the wall-clock win.
- **Three-tier output ladder for `install.sh`.** The
  `curl … | bash` installer's pre-v1.8.0 wall of `diting install: …`
  log lines is now a six-step numbered progress block with `✓`
  markers and an indented `Installed.` summary block — on
  interactive macOS terminals. Tier FULL adds the pixel-beast header
  + 24-bit ANSI brand-orange; Tier PLAIN drops the logo + color on
  `NO_COLOR=1` / `LC_ALL=C` / `TERM=dumb`; Tier LOG (non-TTY /
  Homebrew / CI / TESTONLY) is byte-identical to today so downstream
  parsers continue to work. `DITING_INSTALL_FORMAT={full,plain,log}`
  overrides detection.
- **CDN fallback for CN-network GitHub stalls.** `install.sh` tries
  the canonical GitHub Releases URL first with `curl --max-time 20`;
  on failure (the chronic CN→`objects.githubusercontent.com` stall),
  retries via `https://ghproxy.com/<github-url>`. GitHub stays the
  trust anchor — SHA256 verifies against whichever bytes downloaded.
  `DITING_INSTALL_MIRROR={auto,github,ghproxy}` env override
  (default `auto`). When the fallback fires the user sees a one-line
  notice (EN: `tarball or SHASUMS fetched via ghproxy.com mirror;
  trust anchored on SHA256`; ZH: `tarball 或 SHASUMS 通过 ghproxy.com
  镜像下载；信任仍锚定于 SHA256`).
- **BLE transition events keyed on physical-device clusters.** The
  v1.7.2 consecutive-duplicate grouping in the events modal didn't
  catch the dominant noise source — `BLEDeviceSeenEvent` /
  `BLEDeviceLeftEvent` fired per privacy-rotated identifier even
  though the live BLE panel already merged rotations via
  `merge_for_display`. Now both code paths share the same
  fingerprint (`(vendor_id, name)` exact + RSSI ±10 dB + service-UUID
  Jaccard ≥ 0.5). A single physical device rotating through N
  identifiers fires exactly one `seen` and exactly one `left`
  across its session. JSONL schema unchanged (same fields, same
  types, same representative identifier); external consumers see
  fewer events with byte-identical shape. `DITING_BLE_EVENT_MERGER=0`
  escape hatch restores per-identifier semantics for security
  audits. A user sitting still in an office sees the events modal go
  near-silent rather than the ~40 anonymous-rotation events / 90 s
  flood of pre-v1.8.0.

### Reorganised

- `src/diting/ble.py` gains module-level `_RSSI_WINDOW_DB` /
  `_JACCARD_THRESHOLD` constants read by both `merge_for_display`
  (the live BLE panel) and the new transition cluster index, so
  future tuning passes can't drift the two paths apart.

## [1.7.3] — 2026-05-26

Patch release. **Startup is no longer a frozen-looking wait.** The
6-15s synchronous TCC-probe phase inside `_ensure_helper_ready`
(a real Wi-Fi scan + a CoreBluetooth state poll) is now wrapped in
a pre-alt-screen splash that renders the canonical pixel-art beast
with a micro-motion animation and a ticking status block, so the
user sees what diting is doing instead of staring at a silent
terminal. **Wall-clock latency is unchanged** — perceived-latency
only. A later release can layer on TCC-result caching for the
wall-clock win.

### Added
- **Startup splash with three-tier render ladder.** Tier A
  (interactive TTY ≥ 30 cols): Rich `Live` driving 3 frames at 4 Hz
  + three-line status block (`[..]` → `[✓]` / `[✗]`). Tier B (TTY
  < 30 cols): one static frame + `\r` status overwrites. Tier C
  (non-TTY: pipes, dumb terms): single plain `diting starting...`
  line, no cursor games. Detection via `console.is_terminal` and
  `console.size.width`; the test harness exercises all three tiers
  with stub Consoles.
- **Micro-motion brand mark.** Three frames (canonical → ear-twitch
  → canonical → eye-blink), each differing from its neighbour by ≤
  2 cells. Silhouette and brand-orange palette stay 100% identical
  across frames per the "do not redesign the mark" rule in
  `CLAUDE.md`. The canonical pose is byte-equal to the running
  TUI header's `_LOGO_MARK_ART`.
- **Per-step probe status.** `_ensure_helper_ready` now hands
  `(label, callable)` pairs to `splash.run_with_splash()`; the
  status block ticks `helper located` / `checking Location
  Services` / `checking Bluetooth` as each probe resolves. Falsy
  returns mark `[✗]`; raised exceptions re-raise AFTER teardown
  so upstream error paths continue to fire.
- **i18n.** ZH catalog gains `diting 启动中…`, `已找到 helper`,
  `检查 Location Services`, `检查 Bluetooth`. The two macOS-product
  acronyms stay verbatim per the acronym-preservation rule.

## [1.7.2] — 2026-05-25

Patch release. Ten polish fixes surfaced by two `/tui-audit` passes
against a real corporate Wi-Fi + dense BLE environment — three TUI
display-layer fixes (EN locale) and seven ZH copy-quality fixes.
All changes are display-only; no JSONL contract changes, no
permission surface changes.

### Fixed
- **`_read_arp_cache` zero-pads each MAC octet at ingest.** macOS
  `arp -an` strips leading zeros (gateway rendered as
  `14:51:7e:71:5a:1` instead of `:01`); the LAN detail modal and
  LAN row column now render the canonical IEEE 802 form. Idempotent
  on already-padded input; covers every downstream consumer
  (`LANHost.mac`, JSONL transition events, LAN list, LAN detail).
- **BLE row renderer substitutes `(rotating ID)` for high-entropy
  local names.** Apple Continuity Find-My beacons
  (`NZ1NhvIw3H5T5cSy3kULrJ`-shaped strings) and Huami / Amazfit
  serials (`Z-GM0YXG6A`) were masquerading as human-readable
  device names. The new `_looks_like_rotating_id(name)` predicate
  matches `^[A-Za-z0-9+/=_-]{16,}$` (no whitespace, no Apple
  product prefix); the BLE detail modal gains a `Raw name:` row
  so the helper-emitted string is still reachable.
- **EventsScreen modal collapses consecutive duplicate BLE-seen
  rows.** Source-side dedup is per-identifier; rotating identifiers
  (Apple Continuity, MS CDP) each emit a fresh seen event, so the
  modal was a flood of `device seen: Apple, Inc. · (anonymous)`
  lines that drowned out roam / DHCP / LAN host arrival events.
  Modal renderer now folds runs of identical `(vendor, name_label)`
  rows into one `×N → HH:MM:SS` line. JSONL log on disk is
  unchanged.
- **ZH catalog closes seven copy gaps from the 2026-05-25 ZH-locale
  audit.** The shift-P / public-scene help line had no ZH
  translation; the Bonjour `service` sort token was self-mapped
  (`排序：service`); the basics-modal section heading `Noise / SNR`
  was self-mapped while every peer translated; the bare `" ago"`
  key dropped its leading space (`8s前` vs `5s 前扫描`); Apple
  Continuity protocol names half-translated to `Apple 配对` /
  `Apple 邻近` (with `配对` reading as Bluetooth pairing in Chinese
  — the wrong mental model); and the BLE detail ad-interval hint
  preserved EN word order. All now consistent.

## [1.7.1] — 2026-05-23

Patch release. **`session_meta` JSONL header now carries the at-
launch SSID + gateway_ip** — pre-v1.7.1 the call ran before the
first WiFi poll completed and the first line of every session log
reported `ssid: null` / `gateway_ip: null` even when the host was
associated. Downstream consumers (the analyzer, the `--for-llm`
prompt bundle, third-party `jq` scripts) would misread the
session as having started disassociated.

### Fixed
- **`emit_session_meta` populates SSID + gateway from a synchronous
  startup `get_connection()`.** Both call sites (`_run_monitor` in
  `cli.py`, `DitingApp.__init__` in `tui.py`) now fetch the
  connection once before the JSONL header is written. Failure
  (helper not ready, no Wi-Fi yet) is absorbed as `None` so the
  no-Wi-Fi cold-launch path keeps working. Pre-existing race
  shipped with v1.6.0; surfaced by the v1.7.0 release-binary
  smoke audit.

## [1.7.0] — 2026-05-23

Minor release. **LAN identification expansion** — the LAN view now
recognises far more devices on a typical CN home / office network
by layering four new identification sources on top of the existing
ARP + ICMP + OUI + Bonjour stack: multi-tier IEEE OUI registry
lookup, NBNS / SSDP / active mDNS probes, ICMP TTL fingerprinting,
and a rules-table device-class classifier. The probe layer is
scene-gated — `home` / `office` / `audit` default to active,
`public` defaults to passive but offers a one-shot consent override
via the new uppercase `P` keybinding (with 2-second cooldown +
JSONL audit event).

The LAN row layout reorganises per a UX benchmark of Fing Desktop:
the class column moves to the leftmost data position (it carries
more signal than vendor when scanning a list), and rows whose
`first_seen < 24 h` are prefixed with a `[new]` chip so unfamiliar
devices stand out.

### Added
- **Multi-tier IEEE OUI registry.** Three bundled JSON files
  (`wifi_ouis.json` MA-L, `wifi_ouis_ma_m.json` MA-M,
  `wifi_ouis_ma_s.json` MA-S) — 57 211 vendor mappings total. The
  lookup function tries 36-bit → 28-bit → 24-bit, longest prefix
  wins. CN white-label IoT vendors (Tuya / Aqara / Tapo / Imou)
  that only registered MA-S sub-allocations now resolve to their
  real brand. `scripts/refresh_ouis.py` extended with
  `--source ieee|wireshark|auto` — auto-falls back to the
  Wireshark `manuf` mirror when IEEE direct is unreachable
  (CN-network-friendly default).
- **Vendor display normalization.** Raw IEEE strings get stripped
  of trailing corporate-form tokens (`CO., LTD`, `CORPORATION`,
  `INC`, `TECHNOLOGIES`) and leading geographic prefixes
  (`SHENZHEN`, `HANGZHOU`, `BEIJING`); titlecased with acronym
  preservation (`HP`, `IBM`, `ASUS`, `H3C`, `TP-Link`).
  `NEW H3C TECHNOLOGIES CO., LTD` → `New H3C`. Raw form
  preserved on a dim continuation line in the detail modal.
- **Active LAN discovery layer** (new module
  `src/diting/lan_probes.py`): NBNS Status Query (RFC 1002
  wildcard `*`), SSDP M-SEARCH, active mDNS browse for the
  `_services._dns-sd._meta._tcp.local.` record, plus optional
  HTTP fetch of UPnP `LOCATION` XML for `friendlyName` +
  `modelName`. All three phases run concurrently via
  `asyncio.gather`, each fail-soft on exception. Zero new
  third-party deps — stdlib `socket` + `urllib` + `xml.etree`
  (defused against external entities). No new TCC permissions.
- **Scene-gated active probing.**
  `scene_defaults()["lan_active_probe"]` is `True` for home /
  office / audit, `False` for public. `DITING_LAN_PROBE=0|1`
  overrides; `DITING_LAN_UPNP_FETCH=0|1` separately gates the
  LOCATION-XML fetch.
- **Public-scene one-shot consent override.** Uppercase `P` in
  the LAN view opens `LANProbeConsentScreen` enumerating exactly
  what packets will be sent and the consequences (other guests'
  devices, IDS flagging, captive-portal disconnect). Confirm with
  `y` after a **2-second cooldown** to run ONE active-probe
  sweep; cooldown defeats muscle-memory press-through.
  Subsequent sweeps revert to passive; re-press `P` to re-consent.
- **`LANActiveProbeConsentedEvent` JSONL event.** Written on each
  consent press, carrying `scene`, `ssid`, and the planned packet
  counts. Audit-only — never emitted for scene-default or
  env-forced probing.
- **`[probing]` subtitle chip.** Shows in the LAN view's subtitle
  while a consented one-shot probe sweep is queued; clears when
  the resulting snapshot lands.
- **TTL fingerprint.** `_ping_one` now also parses the ICMP echo's
  `ttl=N` segment; `LANHost.ttl` carries the raw value,
  `LANHost.ttl_class` carries the coarse bucket (`unix` = 50-64,
  `windows` = 100-128, `router` = 200-255, None otherwise).
  Surfaces in the detail modal's Network section as
  `TTL 64 (unix)`. Zero additional traffic.
- **Device-class classifier** (new module
  `src/diting/lan_classify.py`). Pure function over the augmented
  LANHost returns one of 12 classes: `phone | tablet | laptop | desktop |
  tv | camera | smart-home | printer | nas | gaming | speaker |
  router`, or None. Total function — never raises on any field
  combination.
- **LAN row layout: class column + `[new]` chip.** Per Fing UX
  benchmark, the class column is the leftmost data column (it
  disambiguates faster than vendor — a "New H3C" OUI can be a
  router, AP, switch, or IoT bridge). Rows with `first_seen <
  24 h` carry a `[new]` chip in dim cyan; self / gateway never
  carry the chip.
- **Detail modal — Class + TTL + Active-discovery rows.**
  Identity section gains `Class:` (when classifier fires); new
  Active-discovery section consolidates NBNS name, UPnP server
  header, UPnP friendlyName, UPnP modelName. Network section
  gains `TTL: <value> (<class>)` when ICMP returned a TTL.
- **EN ↔ ZH i18n** for every new string: 11 class names, 2 TTL
  classes, `[new]` / `[probing]` chips, full consent modal copy.

### Documentation
- **`README.md` + `docs/zh/README.md`** gain a `## LAN
  identification` section covering the multi-tier OUI, the four
  enrichment layers, the scene-gating matrix, and the
  public-scene consent flow with an ASCII mock of the modal.

### Spec
- Single OpenSpec change `expand-lan-identification` (proposal +
  design.md + tasks.md + seven spec deltas: `lan-inventory`,
  `scenes`, `events`, `event-log`, `tui-shell`, `i18n`, `cli`).

## [1.6.0] — 2026-05-22

Minor release. **Scene awareness** — diting now carries an explicit
notion of *where the user is right now*. Four named scenes
(`home` / `office` / `public` / `audit`) each set their own BLE
presence-gate default and carry a baseline-expectation prior that
the `--for-llm` analysis bundle hands to the LLM as load-bearing
context. Scene resolves from a 5-tier precedence: `--scene` CLI
flag → `DITING_SCENE` env var → `scenes.yaml` per-network pinning
→ auto-detect heuristic (WPA-Enterprise / dense BSSID surface) →
`home` default. Every JSONL session now opens with a `session_meta`
line tagging the scene + how it was resolved, so the analyzer
can group cross-session aggregations by scene and the LLM bundle
prepends a "here's what 'office' looks like as a baseline" prior
to the prompt template.

For the audit / debug use case, `--scene audit` (or
`--ble-presence-gate 0`) disables the gate entirely and restores
the v1.4.0 "record everything" contract.

### Added
- **Scene auto-detect + `scenes.yaml` per-network persistence.** When neither `--scene` nor `DITING_SCENE` is set, diting now picks the scene itself at startup by inspecting the active Wi-Fi connection: enterprise auth (WPA2 / WPA3 Enterprise) → `office`; ≥ 30 visible BSSIDs in the CoreWLAN scan cache → `office`; otherwise `home`. A one-line stderr banner explains the choice (`auto-detected scene: office (WPA2 Enterprise auth)`); suppress with `DITING_SCENE_QUIET=1`. For networks you visit regularly, `scenes.yaml` (mirror of `aps.yaml` — optional, in cwd, git-ignored) pins SSID → scene (or `gateway_mac` → scene for SSID-collision cases like `eduroam`); yaml hit wins over auto-detect, banner becomes `pinned scene: office (matched "Meituan" in scenes.yaml)`. `scene_source` JSONL field extends from `{cli, env, default}` to `{cli, env, yaml, auto, default}` so the analyzer and LLM bundle can distinguish explicit user choice from automated guess. Resolution precedence: CLI flag > env var > scenes.yaml > heuristic > `home` default. `public` stays opt-in (captive-portal detection without active probing is unreliable).
- **Scene awareness — `--scene SCENE` flag + `DITING_SCENE` env var.** Four named environments (`home` / `office` / `public` / `audit`) each carry default knobs and a plain-language baseline expectation. Selected via CLI flag (highest priority), env var, or the default `home`. Drives the BLE presence-gate default per scene (`home=5s`, `office=15s`, `public=30s`, `audit=0s`); `--ble-presence-gate D` continues to override. Active scene renders as a chip in the TUI title bar (`scan 7s · [home]` / `扫描间隔 7s · [家]`). Spec lives in the new `scenes` capability.
- **JSONL `session_meta` event.** Every diting session now writes a `session_meta` line as the FIRST line of its JSONL log (both `--log` and `diting monitor`). Carries `scene`, `scene_source` (cli / env / default), `diting_version`, `ssid`, `gateway_ip`, `hostname`. Per-event lines unchanged — the session context lives ONLY in the header. PII surface kept narrow: hostname is in (anonymizable downstream), BSSID is NOT.
- **`diting analyze` reads `session_meta`.** Report header surfaces the active scene (e.g. `Scene: office (cli)`); multi-session globs summarise the scene mix (`Scenes: 2 × home, 1 × office`). Pre-scene-aware logs render `Scene: unknown (pre-scene-aware capture)` and continue.
- **`diting analyze --for-llm` injects scene context.** The generated `prompt.txt` opens with a `[Scene context]` paragraph telling the LLM what baseline to expect for the captured environment ("office mode — dense enterprise baseline churn expected — look for departures from this baseline, not the baseline itself"). Backfills observed BSSID + BLE-identifier counts from the data when present. Multi-scene bundles get a different paragraph instructing the LLM to compare across scenes.

## [1.5.0] — 2026-05-22

Minor release. BLE event-stream quality pass driven by the
2026-05-21 EN ↔ ZH TUI audit and a 5.6 h real-environment
capture. Three load-bearing changes: a configurable presence
gate that kills single-packet ghost flicker by default while
keeping the "record everything" contract opt-in available, the
state-machine fix that stopped one BLE identifier emitting 229
`left` events from a single `seen`, and a wording cleanup so the
EN UI / ZH UI / JSONL `type` field all agree on what `*_seen`
means. The `diting --help` output also got a structural
restructure on the way through — Subcommands and Global options
now live in two clear sections instead of one flat list.

### Changed
- **`diting --help` restructured.** Subcommands and global options now live in clearly-separated sections (was one flat list). `--notify` is promoted to a top-level entry instead of an inline hint under "(no args)". `analyze` lists its flags (`--since` / `--for-llm` / `--anonymize`) in the top-level help — previously they were only discoverable via the README. Each entry uses 2-line descriptions instead of 5-line paragraphs; the README still carries the long-form documentation. Both EN and ZH catalogs updated.
- **BLE anonymous-advert presence gate, default 5 s.** `BLEPoller` no longer fires `BLEDeviceSeenEvent` on the first observation of an anonymous advert (vendor + RSSI only, no `name`). Instead the identifier enters PENDING and must be observed for at least `presence_gate_s` seconds before graduating to PRESENT and emitting `seen`. An identifier that ages out via TTL before the gate matures emits NOTHING — no `seen`, no `left` — eliminating the single-packet `seen_for=0s` ghost flicker that dominates dense RF environments. Named adverts (`Magic Keyboard`, `Z-GM0YXG5J`, `ccy iPhone 15 Pro Max`) and connected peripherals (`_connected` snapshot) bypass the gate and still fire `seen` on the first observation — only anonymous adverts are gated. New CLI flag `--ble-presence-gate DURATION` (`5s` / `30s` / `2m`, or `0` to disable) plus `DITING_BLE_PRESENCE_GATE` env var; CLI wins over env, defaults to 5 s. `0` restores the A1 record-everything contract for users who want to catch every ephemeral advert (security research, AirTag-spotting, brief-advertiser debugging).

### Fixed
- **Events panel said "joined" but the events are `*_seen`.** EN UI rendered `ble_device_seen` / `bonjour_service_seen` / `lan_host_seen` as `[BLE] device joined:` / `[BJ] service joined:` / `[LAN] host joined:`. ZH already said `设备出现 / 服务出现 / 主机出现` (appeared / seen). The JSONL `type` field always said `*_seen`. The EN wording also lied about semantics — "joined" reads like *paired / associated*, but the event fires on the first passive observation, including strangers' phones walking past. Renamed three EN i18n keys to `device seen: ` / `service seen: ` / `host seen: `; ZH unchanged.
- **Events filter footer claimed `1/2/3/4/0`; A1 added `5/6/7`.** The EventsScreen filter cycle has eight buckets since A1 (`ble` / `bonjour` / `lan` on keys `5` / `6` / `7`), the bindings work, but four user-facing strings — events-modal footer and help-modal "Events modal (m)" paragraph, EN + ZH — still listed only the legacy five keys. Extended to `1/2/3/4/5/6/7/0` in both locales so the new filters are discoverable from the TUI alone.
- **BLE `ble_device_left` re-emission bug.** A device at the edge of range whose adverts the macOS Bluetooth stack briefly stopped delivering would TTL-evict, re-populate `_devices` from the next advert, evict again, and re-emit `BLEDeviceLeftEvent` on every cycle. One identifier in a real 5.6 h capture produced 229 left events from a single seen — 67,548 BLE events / 13 MB JSONL for the session. `BLEPoller._detect_transitions` now gates left-emission on a per-session `_departed_identifiers` set: at most one left per seen, identifier silent for the rest of the session after departure. JSONL size for the captured session drops ~63%.

## [1.4.0] — 2026-05-21

Minor release. The long-timeline-analysis arc: the JSONL log
captures a much richer event vocabulary, `diting analyze` reads
many logs at once and surfaces patterns across weeks, and a new
`--for-llm` bundle exports a paste-ready report + prompt for
ChatGPT / Claude when a user wants richer interpretation than
the local heuristics produce. No API keys, no telemetry, no
extra dependency — diting stays offline-first.

### Added
- **Seven new event types in the JSONL log.** `BLEPoller`,
  `BonjourPoller`, and `LANInventoryPoller` now emit transition
  events alongside their existing snapshot streams:
  `ble_device_seen` / `ble_device_left`,
  `bonjour_service_seen` / `bonjour_service_left`,
  `lan_host_seen` / `lan_host_left` /
  `lan_host_dhcp_rotation`. No debounce — every first observation
  of an identifier fires its `seen` event, including short-lived
  ghost MACs in dense environments. EventsScreen filter cycle
  extends from 5 → 8 buckets (`ble` / `bonjour` / `lan`) and
  EventsPanel renders the new types with `[BLE]` / `[BJ]` /
  `[LAN]` prefix tags.
- **`diting analyze` accepts multiple JSONL paths via shell
  glob.** Optional `--since DURATION` flag (`30d` / `7d` /
  `24h` / `90m` / `60s`) filters the merged event stream to
  the last DURATION before "now". Single-file no-`--since`
  invocations keep the existing per-session layout verbatim —
  the new cross-session blocks only render when the user is
  doing a multi-session view.
- **Five cross-session aggregations** rendered below the
  per-session report when the input is multi-session:
  hour-of-day distribution (24-row ASCII bars), day-of-week × hour
  heatmap (Unicode block density `▁▂▃▄▅▆▇█`), per-network
  ranking (groups events by associated BSSID via
  `connection_update` walk; orphan events land in
  `(unknown network)`), daily trend (per-day total + 7-day
  rolling average), and top contributors (BSSIDs by
  roam + RF-stir, BLE identifiers by `seen` count, LAN hosts
  by DHCP rotations).
- **`diting analyze --for-llm [outdir]`** — writes a paste-ready
  bundle (`report.md` + `prompt.txt`) for ChatGPT / Claude. The
  report uses Markdown tables for ranked data, fenced text
  blocks for ASCII charts, and always-present `## Glossary`
  section so the LLM doesn't have to guess diting-specific
  terms (`stir`, `co_located`, the 7 new event types). The
  prompt is a 5-section analyst template asking the LLM to
  identify patterns, name root causes + evidence, suggest
  follow-up investigations, tag inferences with confidence, and
  not speculate beyond the data. CLI prints a 4-step paste
  workflow to stdout.
- **`--anonymize`** (companion flag, default OFF) — replaces
  SSIDs / BSSIDs / RFC1918 IPs / hostnames / BLE identifiers /
  LAN MACs with stable first-seen handles (`SSID_1`, `AP_1`,
  `IP_1`, `HOST_1`, `BLE_1`, `MAC_1`). Public IPs (`8.8.8.8`,
  `1.1.1.1`) and vendor names (`Apple, Inc.`, `Cisco Systems`)
  pass through unchanged. The handle ↔ original mapping prints
  to TERMINAL ONLY — never into the bundle — so users can decode
  the LLM's references locally without leaking the mapping into
  a public chat.

### Changed
- **Twelve event types** share the EventRing + JSONL writer (was
  five). The analyzer treats unknown event types as benign
  passthrough already, so reading a new-format log with an old
  build degrades gracefully.
- **`diting analyze` argparse signature** — `paths` is now
  `nargs="+"`; `--since DURATION` and `--for-llm [outdir]` /
  `--anonymize` are new optional flags.

### Fixed
- **TZ-bucketing bug** caught on CI before A2 shipped — cross-
  session aggregators bucket by the timestamp's own offset
  (encoded in the JSONL `ts` string), not by the analyzer
  machine's local TZ. CI runners are UTC; using `.astimezone()`
  was shifting `+08:00` timestamps by -8 hours on CI vs the
  user's local machine.

## [1.3.0] — 2026-05-19

Minor release. Two real-environment audit findings on a Meituan
corp network drove a vendor-lookup upgrade and a LAN-host detail
modal enrichment; one smaller UX fix rides along.

### Added
- **Full IEEE OUI registry (~250 entries → 39,444).** The bundled
  `*_ouis.json` data files were a hand-curated subset; replaced
  with the full IEEE Registration Authority MA-L (24-bit) registry.
  Both `bluetooth_ouis.json` (used by BLE and the LAN host list)
  and `wifi_ouis.json` (used by Wi-Fi BSSID resolution) now ship
  the same canonical 39 k-entry dataset. On corp networks, gateway
  / enterprise-switch OUIs (Cisco, Aruba, H3C, HPE, Huawei, etc.)
  now resolve to vendor names instead of `(unknown)`. File size:
  ~20 KB → ~1.5 MB each; in-memory heap +~5 MB; lookup speed O(1)
  unchanged.
- **`scripts/refresh_ouis.py`.** New CLI that pulls the canonical
  CSV from `https://standards-oui.ieee.org/oui/oui.csv`, parses +
  dedupes, and rewrites both data files. Run before each release
  to pick up newly-registered OUIs. IEEE attribution added in
  `_meta` and README.
- **`LANHost.last_rtt_ms` and `LANHost.last_reachable_at`.** New
  fields populated from each sweep's per-host ICMP results.
  `last_seen` (ARP cache observation) and `last_reachable_at`
  (most recent successful ICMP echo) are tracked separately so a
  host that's in ARP but offline shows the freshness gap. Fields
  are preserved across silent ticks — a temporarily-quiet host's
  last-known RTT stays visible in the modal.
- **LANDetailScreen Network section: Latency + Reachable rows.**
  `Latency  X.X ms` (omitted when last_rtt_ms is None);
  `Reachable  this sweep | Xs ago | never` (always rendered).
  Parsed from the new `_ping_one` return tuple
  `(reachable, rtt_ms | None)`.
- **LANDetailScreen Bonjour services empty-state placeholder.**
  When the host has no Bonjour services, the section now renders
  `(no Bonjour services)` instead of being hidden entirely —
  users had no signal that the cross-reference channel was
  checked.

### Changed
- **`_ping_one` and `_sweep` return shape.** `_ping_one` now
  returns `tuple[bool, float | None]` parsed from `time=X.XXX ms`
  in macOS ping stdout. `_sweep` returns
  `dict[str, tuple[bool, float | None]]` so the merge step can
  populate per-host RTT and reachability without re-running probes.

### Fixed
- **Duplicate ZH labels in LAN diagnostics.** `子网 子网
  11.10.158.0/24` and `上次扫描 上次扫描 38s` doubled because both
  the row prefix and the value template translated to the same ZH
  word. Dropped the lowercase prefix from the value templates;
  the row label alone identifies the row.
- **Title bar showed `扫描间隔 7s` on every view.** That's the
  Wi-Fi CoreWLAN scan interval — but on the LAN view the user
  could reasonably think LAN swept at 7s, when it actually sweeps
  at 60s. Made the cadence view-specific: `scan 7s` on wifi,
  `sweep 60s` on lan, dropped entirely on BLE / Bonjour
  (push-driven pollers).

## [1.2.0] — 2026-05-19

Minor release. Headline: a new fourth panel that answers "who's on
my Wi-Fi?" from a regular Mac client, no router login. Two smaller
UX changes also ride along.

### Added
- **LAN inventory panel.** Cycle to it via `n` (fourth view after
  Wi-Fi → BLE → Bonjour). Each tick the new `LANInventoryPoller`
  ICMP-pings every IP in the local /24 around your interface
  (30-way concurrency, 200 ms per host) and reads the kernel ARP
  cache via `arp -an`, then enriches each entry with OUI vendor,
  reverse DNS, and a **Bonjour cross-reference** for friendly
  names. Rows pin `this Mac` first with ★, then `gateway` with ★,
  then sort by IP ascending. Locally-administered (random) MACs
  are flagged with `(random MAC)` in place of a vendor. State is
  keyed by lowercase MAC so `first_seen` is preserved across DHCP
  IP rotation. Default-on; lazy-constructs on first LAN-view
  entry so users who never cycle in pay zero cost. See
  [`docs/explainers/lan-inventory-arp.md`](docs/explainers/lan-inventory-arp.md)
  for the design.
- **`DITING_LAN_INVENTORY_WIDE=1` env var.** Relaxes the default
  /24 cap to /22 (1022 hosts) for users on wider home subnets.
  Corporate /16+ VLANs are still narrowed to a /22 around the
  interface IP; diting never sweeps the full broadcast domain.
- **LANDetailScreen modal** (priority `i` from the LAN view).
  Identity / Network / Bonjour services / Activity sections.
  Arrow-keys passthrough so `up` / `down` walks the LAN table
  with the modal tracking. Closes on `Esc` / `i` / `q`.
- **LAN-view diagnostics block.** `LAN inventory  N hosts ·
  M named (Bonjour) · K unknown vendor · subnet … [· capped] ·
  last sweep Xs ago`.

### Changed
- **Help screen rebound from `h` to `?`.** `h` is now an
  intentional no-op so it stays free for a future per-view binding
  without colliding with the global help shortcut. The `?` key
  matches the convention every other CLI uses for "show help".
- **Help text + bindings now reflect the four-view cycle.**

### Fixed
- **mDNS list no longer empties when no zeroconf callback fires.**
  The poller now actively re-probes every tracked service-type at
  a 30 s cadence so devices that re-assert unchanged records (the
  common HomePod / printer case) keep their `last_seen` fresh
  even when zeroconf's change-driven callbacks stay quiet.
- **Hide Tx / Max when CoreWLAN reports `Max < Tx`.** macOS 26
  `maximumLinkSpeed()` returns a stale value in some scenarios
  that makes Tx look faster than the radio's maximum (which
  cannot happen physically). The Tx half stands alone correctly;
  showing both produces a self-contradiction, so the Max half is
  suppressed in that case.

## [1.1.2] — 2026-05-18

Two fixes / one enhancement driven by real-environment use of v1.1.1.

### Fixed
- **Bonjour list no longer empties after ~1 minute of stable
  services.** zeroconf's `update_service` callback is change-driven
  — a HomePod re-asserting an unchanged AirPlay record fires no
  callback, so `last_seen` stayed frozen at the first
  `add_service` time and the 60 s TTL evicted live services even
  though zeroconf's own DNS cache still held the records. The
  poller now refreshes liveness from zeroconf's cache each
  snapshot tick: any entry whose service-instance name still has
  a non-expired record in `Zeroconf.cache.entries_with_name` gets
  its `last_seen` bumped. The TTL backstop default also moves
  from 60 s → 300 s; with the cache-refresh path keeping stable
  services alive, the TTL is now a last-resort sweep, not the
  primary eviction mechanism.

### Added
- **Wi-Fi event lines (roam, RF stir) surface the affected
  SSID.** Roam lines render `SSID: <name>` when both sides share
  a network (band switch / same-ESS roam) and `SSID: <prev> →
  <new>` when they differ; RF stir lines append `· SSID <name>`
  after the disturbance body. The segment is omitted entirely
  when both sides are `None` or `""` (hidden). The AP-name half
  is unchanged — it still comes from `aps.yaml` via
  `NetworkInventory`, so a fully-populated inventory keeps
  showing friendly AP names. SSID context is additive and works
  even when the inventory is empty.
- JSONL log lines for `RoamEvent` and `RFStirEvent` carry the
  new `previous_ssid` / `new_ssid` / `ssid` keys when populated;
  keys are skipped when `None` so old log entries stay
  diff-stable.

## [1.1.1] — 2026-05-17

Polish pass driven by a real-environment `/tui-audit` against the
v1.1.0 build. Three bugs and two display improvements.

### Fixed
- **Wi-Fi scan no longer shows the same BSSID multiple times.**
  CoreWLAN's scan can return the same BSSID across multiple
  scan-dwell instances; the Python side now dedups by lowercase
  BSSID and keeps the strongest RSSI. The "Nearby BSSIDs (N)"
  count reflects distinct BSSIDs.
- **BLE detail Services / Manufacturer-data placeholders no
  longer carry a stray em-dash.** Empty states like
  `(none advertised)` and `(no manufacturer-specific data)` were
  being rendered through the label / value helper, which appends
  an em-dash when value is None. They're now standalone
  dim-italic lines.
- **Connection panel's Tx Rate field no longer flickers to
  `n/a` between scans.** `MacOSWiFiBackend` caches the last
  non-zero `transmitRate()` per association; when a poll on the
  same `(ssid, bssid)` comes back zero (radio idle), the cached
  value is surfaced with an `(idle)` annotation. The cache
  invalidates on roam / reassociate.

### Added
- **`by-host` sort mode for the Bonjour panel.** Pressing `s`
  while on the mDNS view now cycles `service ↔ by-host`. The
  by-host mode collapses each host's announces into one row
  with a comma-joined services column (`AirPlay, AirPlay audio,
  Apple Companion, HomeKit`), `…`-truncated when long. Useful
  for an environment full of HomePods that each advertise 4
  services and clutter the default per-service list.

### Changed
- **Unknown-vendor bucket label parity.** Both the mDNS and BLE
  Top-vendors diagnostics line now read `(unknown) N` for
  unresolved-vendor counts, matching the column placeholder.
  Previously rendered as `? N`, which read as a typo.

## [1.1.0] — 2026-05-17

The Wi-Fi panel grows two hands. You can now associate an SSID
directly from its detail modal (`j`), and on first save the
credential goes into your **login keychain behind a Touch ID
ACL** — every subsequent join is a single biometric tap rather
than an admin-password sheet. The TUI also picks up a branded
title bar, plus a stack of helper polish and display fixes.

### Added
- **Join a Wi-Fi network from its detail page (`j`).** New binding
  on the Wi-Fi detail modal opens a confirmation prompt —
  including a "not hitless, ~2-5 s gap" warning — and on confirm
  associates via a new `diting-tianer associate` helper
  subcommand. Networks with a saved password join after a Touch
  ID tap; new networks get a native macOS password sheet rendered
  by the helper bundle (with a "Remember this network" checkbox).
  Enterprise / 802.1X is refused with a hint to use the system
  Wi-Fi menu once. `c` (force re-roam) is unchanged. See
  `openspec/changes/archive/2026-05-16-wifi-connect-from-detail/`.
- **Wi-Fi passwords live in the login keychain behind Touch ID.**
  The helper persists its own copy of the password under the
  `diting Wi-Fi` service namespace with a
  `SecAccessControlCreateWithFlags(.userPresence, …)` ACL.
  macOS unlocks it with Touch ID on capable hardware and falls
  back to the **login** password (not the admin password) when
  biometric is unavailable. Previous PRs tried to read Apple's
  System-Keychain AirPort items directly — that path requires
  an admin sheet on every call, which is unusable. See
  `openspec/changes/archive/2026-05-17-wifi-keychain-touch-id/`.
- **Branded title bar.** The top status line is now a flat band
  carrying the radar mark + `diting v<version>` — the same
  pixel-art beast you see in `assets/logo-mark.svg`.

### Fixed
- **Router unreachability copy.** When the Router probe gets no
  ICMP reply but the WAN probe still works, the diagnostics line
  reads `Router (no ICMP reply)` / `Router (ICMP 无响应)` instead
  of the misleading "unreachable" — many home routers silently
  drop ICMP echo but still forward traffic.
- **Tuya BLE alias + "samples over <1s".** Tuya devices now
  resolve via the vendor alias map (no more raw IEEE registrant
  string), and the BLE detail's RSSI-history footer reads
  `samples over <1s` instead of `samples over 0s` when the
  history spans less than a second.
- **`diting-tianer associate` polish.** `-g -n` flags on the
  `open` outer→inner spawn so the helper doesn't focus-steal
  during a join; early-exit when already on the target SSID;
  multiple CWKeychain-signature fallbacks; Keychain READ/WRITE
  goes through `Security.framework` `SecItem*` rather than the
  private `CWKeychain` selectors.

### Migration note
The Touch ID change relocates saved Wi-Fi passwords from Apple's
System Keychain to diting's own login-keychain namespace. On
first join after upgrade, every previously-saved SSID will fall
back to the password sheet once — confirm the password (or paste
from the system Wi-Fi prefs) and tick "Remember" again. The
helper bundle's cdhash also moves with the
`feat(macos-helper)!` change, so first launch re-grants Location
+ Bluetooth + Notifications once.

## [1.0.12] — 2026-05-16

Two related helper-bundle fixes for v1.0.11 user reports: Dock icon
flashing on every Wi-Fi scan, and `--notify` silently dropping
every anomaly banner.

### Fixed
- **`diting-tianer.app` no longer flashes in the Dock during TUI
  runtime.** `helper/Info.plist` now sets `LSUIElement=true` so the
  bundle is a "background-only / agent app" — no Dock presence,
  no Cmd+Tab presence. Windows still work (the install-time
  HelperAppDelegate's status panel is unchanged), and TCC grants
  still attach by CFBundleIdentifier / cdhash so every other
  feature is unaffected. Previously every `scan` invocation
  re-launched the bundle via LaunchServices (per the v1.0.7
  macOS-26 fix) and the Dock icon flashed briefly until
  `setActivationPolicy(.prohibited)` ran.
- **`--notify` banners actually deliver.** Same macOS-26 TCC
  asymmetry that bit `scan` also bit `notify`: when Python
  invoked the bundle's binary directly with `notify`, the helper
  process was NOT LaunchServices-attributed and
  `UNUserNotificationCenter.requestAuthorization` came back
  `granted=false` — silent drop, no banner. `notify` now uses the
  same outer/inner LaunchServices split as `scan`: outer half
  spawns `/usr/bin/open -W -g -a <bundle> --env
  DITING_NOTIFY_VIA_LAUNCH=1 --env DITING_NOTIFY_TITLE=... --env
  DITING_NOTIFY_BODY=... --args notify`; inner half runs as the
  LaunchServices-launched instance, has the bundle's
  Notifications grant, posts the banner, exits. Python's
  watchdog code path is unchanged.

### Migration note
The `LSUIElement` change bumps the bundle's cdhash. Users
upgrading from v1.0.11 will re-grant Location + Bluetooth +
Notifications once on next install.

## [1.0.11] — 2026-05-15

The Wi-Fi and Bonjour detail modals stop being raw-field dumps and
start telling you what the rest of diting already knows. Same data,
much richer context.

### Added (Wi-Fi detail modal)
- **Signal history** — sparkline of the last ~hour of RSSI samples
  for the inspected BSSID + a `σ X dB · stable / active` stability
  label. Drawn from `EnvironmentMonitor`'s existing per-BSSID ring.
- **Same physical AP** — sibling BSSIDs (2.4 / 5 / 6 GHz radios)
  grouped via `NetworkInventory.is_same_ap`, with their channel /
  band / RSSI from the current scan.
- **Roam history** — newest-first list (capped at 10) of roam
  events where this BSSID was either `previous_bssid` or
  `new_bssid`. `[same-AP]` / `[cross-AP]` tags.
- **Recommendation** — when the inspected row IS the
  currently-associated BSSID AND a same-SSID candidate is ≥ 15 dB
  stronger, render `consider switching to <BSSID> on <band> ·
  +N dB`. Uses the same `clearly-better` rule the diagnostics
  panel's Roam score line uses.

### Added (Bonjour detail modal)
- **Vendor-resolution trace** — Identity section's vendor row
  appends ` · via txt-vendor / oui / hostname-pattern /
  service-type-hint` so the user can see which signal won. Backed
  by a new `BonjourDevice.vendor_trace` field populated by a new
  `resolve_vendor_with_trace()`. Maintainers use it to find
  long-tail decoder gaps; users get a small confidence cue.
- **Other services on this host** — when one host advertises
  multiple services (the user's own Mac is the canonical case:
  `AirPlay` + `AirPlay audio` + `Apple Companion`), list the other
  categories with their `last_seen` age. Reframes the modal from
  service-instance-centric to device-centric.
- **TXT decoders** — well-known keys (`model` / `osxvers` /
  `srcvers` / `deviceid`) parse into named friendly fields
  rendered above the raw TXT table. Apple model identifiers like
  `MacBookPro18,1` decode to `MacBook Pro 16-inch (M1 Pro, 2021)`;
  macOS major versions render with codenames (e.g. `Tahoe (26)`).
  Lives in `src/diting/mdns_txt_decoders.py` as a small
  registry; decoders never raise.
- **Cross-surface correlation** — new section ties the Bonjour
  host to the rest of diting's scan surfaces via three rules:
  - **Rule 1** (deterministic): the announced IP matches the
    Mac's `Connection.ip_address` → `local Mac (this host is
    you)`. Fires on every announcement of the user's own Mac.
  - **Rule 2** (opportunistic): TXT `deviceid` parses as a
    canonical MAC AND those bytes appear in some BLE row's
    `manufacturer_hex` → `also on BLE as <name|type|vendor> ·
    <RSSI> dBm`. Rare for Apple devices (RPA) but useful for
    printers / IoT hubs that embed their MAC in adverts.
  - **Rule 3** (probabilistic, hedged): the Bonjour hostname
    resolves to Apple via `_NAME_PATTERN_VENDORS` AND a nearby
    BLE row carries an Apple-Proximity-class `type` (`Nearby
    Info` / `Nearby Action` / `Handoff` / `Apple Proximity`) →
    `likely the same device as BLE row <short-id>`. The
    "likely" hedge is explicit because hostname-pattern
    correlation is probabilistic.

### Changed
- `WifiDetailScreen.__init__` and `BonjourDetailScreen.__init__`
  gain optional kwargs (`environment_monitor` / `event_ring` /
  `latest_scan` for Wi-Fi; `latest_mdns` / `latest_ble` /
  `latest_connection` for Bonjour) so the modals can read live
  session state. All default to `None`; sections whose ref is
  missing omit entirely.
- `_section_txt` (Bonjour) now renders Decoded first + Raw second.
  Decoded keys are excluded from the Raw table via
  `mdns_txt_decoders.decoded_keys()`.

### Spec
Three capabilities modified: `wifi-detail-modal`,
`bonjour-detail-modal`, `mdns-scanning`. See
`openspec/changes/archive/2026-05-15-wifi-and-bonjour-detail-enrichment/`.

## [1.0.10] — 2026-05-14

Two fixes that surface only in the curl-installed frozen binary
(not in `uv run diting`).

### Fixed
- **Frozen binary's `--version` and TUI title now report the real
  version.** v1.0.9 shipped without `--copy-metadata diting` in the
  PyInstaller invocation, so `importlib.metadata.version("diting")`
  raised `PackageNotFoundError` in the frozen build and
  `__version__` fell back to `"0+unknown"`. Result: `diting
  --version` printed `diting 0+unknown` and the TUI header rendered
  `diting v0+unknown`. Adding `--copy-metadata diting` to
  `scripts/build_frozen.py` packs the dist-info into the frozen
  archive. Regression test in `tests/test_helper.py` guards against
  the flag being removed again.
- **Bonjour prewarm now starts at TUI mount, not on first
  wifi → BLE.** The "first wifi → BLE" trigger landed in
  1.0.x worked on the source build because `.py` file reads release
  the GIL during the actual `open()` syscall, so the prewarm
  worker overlapped with the BLE view's reading time. PyInstaller's
  `PyiFrozenImporter` decompresses modules from a PYZ archive
  inside pure-Python code that holds the GIL throughout — so
  `asyncio.to_thread` doesn't help, and users on v1.0.9 saw the
  second `n` press (BLE → mDNS) hang for >1.5 s. Moving the
  trigger to `App.on_mount` gives the prewarm the entire wifi-view
  dwell time to amortise, which is plenty.

### Spec / breaking-ish note
The `mdns-scanning` capability's "user who only uses Wi-Fi view
never imports zeroconf" guarantee no longer holds — every TUI
session now imports zeroconf at mount. The cost runs in a worker
so there's no user-visible slowdown; the change is documented in
the `prewarm-bonjour-at-mount` OpenSpec change.

## [1.0.9] — 2026-05-14

Small, useful: a way to tell what version of diting you're running.

### Added
- **`diting --version` (and `-V`)** prints `diting <X.Y.Z>` and
  exits 0. Short-circuits before any locale / log / TUI / helper
  work so it's fast and side-effect-free — safe to wire into bug-
  report scripts.
- **TUI header now shows the version.** `App.title` becomes
  `diting v<X.Y.Z>` so the running version is visible at a glance,
  no key press required. Subtitle (view / scan cadence / paused)
  is unchanged.

### Changed
- **`diting.__version__` is now lazy.** Sourced from
  `importlib.metadata.version("diting")` instead of a hand-
  maintained string. The previous constant in
  `src/diting/__init__.py` had drifted to `"0.5.0"` while the
  project was at 1.0.8 — the new approach makes `pyproject.toml`'s
  `version` the single source of truth so this can't drift again.

## [1.0.8] — 2026-05-14

Two parallel pushes land together: the helper bundle gets its own
icon and a single ordered install flow (no more chaotic three-window
stack on first launch), and the release workflow finally ships
x86_64 tarballs reliably again.

### Added (helper bundle / install UX)
- **Helper bundle ships the diting logo as its AppIcon.**
  Pre-rendered PNGs at every macOS iconset size live under
  `helper/Resources/AppIcon.iconset/` (regenerated by
  `scripts/build_app_icon.py` from `docs/design/diting-design/assets/logo-mark.svg`).
  `helper/build.sh` packs them with `iconutil --convert icns` into
  `Contents/Resources/AppIcon.icns`; Info.plist declares
  `CFBundleIconFile=AppIcon`. The icon now appears in Finder, in
  the macOS TCC prompts for Location and Notifications, and in
  every Notification Centre alert the watchdog raises.
- **`diting-tianer notify --title T --body B` subcommand.** Uses
  `UNUserNotificationCenter` under the bundle's identity so the
  notification thumbnail is the diting logo. Requests
  authorization once, posts, exits within ~1 s.
- **Notifications TCC step at install time** alongside Location
  and Bluetooth, so the watchdog can fire alerts without
  triggering a surprise prompt months later.

### Changed (helper bundle / install UX)
- **Install-time permission flow is now a single ordered wizard.**
  `HelperAppDelegate` requests Location → Bluetooth → Notifications
  in sequence; each step fires only after the previous step's auth
  callback resolves. The user sees one macOS TCC prompt at a time
  on top of the status window. The status panel renders three lines
  (one per step) prefixed `1/3` / `2/3` / `3/3` with an arrow
  marking the current step.
- **Install-time locale follows macOS user preference.** `install.sh`
  reads `defaults read -g AppleLanguages`, derives `DITING_LANG=en|zh`,
  and passes both `--env DITING_LANG=...` AND `--args -AppleLanguages
  '(<bundle-tag>)'` to `open` so the helper UI, the TCC prompt
  headers, and the prompt body text all render in the same language.
  Previously `Locale.preferredLanguages` and
  `Bundle.preferredLocalizations` could disagree under LaunchServices
  and the user saw a mixed-language stack.
- **`cli.py`'s helper auto-prime path also passes `-AppleLanguages`**
  so the same agreement holds at runtime when `diting --lang zh`
  re-launches the helper.
- **Helper language fallback switches from
  `Locale.preferredLanguages.first` to
  `Bundle.main.preferredLocalizations.first`** — the same source
  macOS uses to pick `.lproj` — so an absent `DITING_LANG` env still
  produces an agreeing UI.
- **Watchdog notifications route through the helper, not osascript.**
  `_macos_notify` shells out to `<helper-bin> notify --title ...
  --body ...` (resolved via `_helper.find_helper`). No osascript
  fallback — a missing helper silently skips the notification.
  Eliminates the AppleScript scroll icon that used to appear in
  every alert.

### Changed (release flow)
Intel (x86_64) releases land on every tag again. Prior tags
(v1.0.0 – v1.0.7) shipped the x86_64 tarball only when the
`macos-13` runner happened to be available — which during 2026 has
been "almost never", since GitHub Actions has been winding down the
Intel hosted-runner pool. v1.0.7's release sat with the Intel job
queued for hours before the user manually unblocked arm64 by
uploading just the arm64 SHASUMS entry.

- **Release workflow now builds both arches from a single `macos-14`
  (arm64) runner**:
  - Swift helper is built once as **universal2** (`swift build
    --arch arm64 --arch x86_64`) — a single .app whose binary
    contains both arch slices. Gated by env var
    `DITING_HELPER_UNIVERSAL=1` so local dev defaults to a
    fast native-only build.
  - PyInstaller's frozen Python is arch-specific (takes the running
    Python's arch), so we build it twice: once natively on the
    arm64 host, once under **Rosetta 2** via `arch -x86_64`. The
    Rosetta path uses a separate `uv` install (also under Rosetta)
    that pulls x86_64 pyobjc / ifaddr / zeroconf wheels.
  - Both tarballs are uploaded to the release; the `shasums` job
    aggregates as before. The release surface is unchanged from
    v1.0.7's perspective — install.sh keeps fetching
    `diting-<v>-darwin-<arch>.tar.gz` per `uname -m`.
- **Local dev unchanged**: `helper/build.sh` defaults to native
  build. Set `DITING_HELPER_UNIVERSAL=1` to test the universal2 path.

### Migration note (breaking)
The new `CFBundleIconFile` plist entry changes the bundle's cdhash.
Users upgrading from v1.0.x will re-grant Location + Bluetooth once
on the next install (and grant Notifications for the first time).
Future installs at the same path retain grants.

### Caveats
- Rosetta-emulated PyInstaller is ~2× slower than native on the same
  host — the release workflow's total wall-clock grows by ~3-5 min
  per release. Acceptable.
- The x86_64 frozen binary is built on an arm64 host under
  emulation; the result has not been smoke-tested on a real Intel
  Mac in this change. Volunteer testers welcome.

## [1.0.7] — 2026-05-13

The macOS 26 install hang that survived v1.0.3 → v1.0.5 had a deeper
root cause than every prior fix attempted: **direct-exec subprocesses
of an ad-hoc-signed bundle's binary don't inherit the bundle's
Location TCC grant on macOS 26**. CoreLocation's TCC check requires
the process to be LaunchServices-attributed; CoreBluetooth's doesn't
(which is why `bluetooth-status` worked the whole time).

User surfaced the asymmetry: `uv run diting` worked because they'd
been repeatedly `open`-ing the in-repo bundle this session, keeping
locationd warm-cached for that cdhash at that path; `diting`
(curl-installed) hung indefinitely because the install path's bundle
was cold and the direct-exec scan subprocess saw
`CLLocationManager.authorizationStatus = .notDetermined` regardless
of whatever run-loop pump / NSApp.run / disclaim trick was layered
on top.

### Fixed
- **`scan` subcommand re-launches itself via LaunchServices.** Two
  halves of the same function, switched on `DITING_SCAN_VIA_LAUNCH`
  env var:
  - **Outer half** (no env var): spawns
    `/usr/bin/open -W -g -a <bundle> --env DITING_SCAN_VIA_LAUNCH=1
    --env DITING_SCAN_OUT=<tempfile> --args scan`. Waits for the
    LaunchServices'd child, reads the JSON it wrote, relays to
    stdout, exits. Python's `subprocess.run([binary, "scan"])` sees
    this as if the original subprocess produced the output directly
    — no Python-side protocol change.
  - **Inner half** (`DITING_SCAN_VIA_LAUNCH=1`): runs as the
    LaunchServices-launched bundle instance. `NSApplication.shared.
    setActivationPolicy(.prohibited)` keeps it out of the Dock and
    prevents focus theft. `ScanWorker : CLLocationManagerDelegate`
    initialises `CLLocationManager`, calls
    `requestWhenInUseAuthorization` + `startUpdatingLocation`, then
    runs a scan-with-retry loop (up to 6 attempts × 500 ms apart)
    until any returned row has a `bssid` — or denied / restricted
    cuts the loop short. `NSApp.run()` pumps both the run loop and
    the libdispatch main queue. JSON is written to `$DITING_SCAN_OUT`
    via atomic file write; `exit(0)` ends the inner process.
- **`ble-scan` and `bluetooth-status` are unchanged.** They keep
  using disclaim + direct-exec; CBCentralManager's TCC honours
  cdhash directly so no LaunchServices hop is needed there.

### Empirical timings (cold subprocess scan, user's macOS 26 machine)

| Run | Time | Result |
|---|---|---|
| 1 (cold) | 1.56 s | 116 / 116 unredacted |
| 2 (locationd cached after run 1) | 0.29 s | 139 / 139 unredacted |
| 3 (cold again) | 1.84 s | 103 / 103 unredacted |

LaunchServices launch dominates the latency budget on cold runs
(~500 ms – 1 s). Acceptable for the one-time `has_permission` probe
at startup. Continuous-scan latency could be lowered further by
running the bundle as a long-lived background daemon and using
socket IPC for scan requests; deferred until it actually matters.

### Why prior attempts failed (for future-us / future debuggers)

| Version | Approach | Why it didn't work |
|---|---|---|
| v1.0.3 | disclaim + `Thread.sleep(0.3)` | Thread.sleep doesn't pump run loop AND direct exec doesn't get bundle TCC |
| v1.0.6 | disclaim + `RunLoop.current.run(mode:.default, before:)` | Same — pumping the run loop doesn't change the TCC attribution |
| (interim) | disclaim + `dispatchMain()` + 6-retry loop | Worked when locationd had a warm cache for the cdhash at that path; failed cold |
| (interim) | NSApp.run() in direct-exec subprocess | NSApp doesn't change the kernel's TCC subject; still `.notDetermined` |
| **v1.0.7** | LaunchServices re-launch via `open --args scan` | First version that gets bundle-attributed TCC reliably from cold |

The diagnostic that nailed it: write
`CLLocationManager.authorizationStatus().rawValue` to stderr at the
start of the disclaimed scan path. On macOS 26 it prints `0`
(`.notDetermined`) — proving the bundle's grant simply isn't reaching
this process, no matter how the in-process code is structured.

## [1.0.6] — 2026-05-13

The v1.0.3 → v1.0.5 chain attempted to fix CoreWLAN scan
redaction under install.sh-installed helpers via
disclaim-responsibility + `CLLocationManager.startUpdatingLocation()`
+ `Thread.sleep(0.3)`. The disclaim hop and the manager init are
necessary but the third piece was wrong: `Thread.sleep` does not
pump the run loop, so `CLLocationManager`'s delegate-callback
handshake with `locationd` never actually completes inside the
short-lived CLI subprocess. CoreWLAN's redaction gate on macOS 26
checks whether the calling process is a *registered* location
consumer (not just an authorized one), so scans came back redacted
even when the bundle's TCC grant was in place.

This kept the user stuck at "需要以下权限：- 定位服务" through
v1.0.3 / v1.0.4 / v1.0.5 even after clicking Allow on the popup.

### Fixed
- **`runScanAndDumpJSON()` pumps the run loop until the location
  authorization callback fires.** New `LocationAuthProbe` delegate
  signals when `locationManagerDidChangeAuthorization` resolves to
  a non-`.notDetermined` state. The scan subcommand now runs
  `RunLoop.current.run(mode:.default, before:…)` slices of 50 ms
  each, exiting as soon as the callback lands (typically <100 ms
  on a freshly-granted bundle) or after a 2 s timeout. Only then
  does `scanForNetworks` get called. Mirrors the existing
  `runBluetoothStatusProbe` pattern.
- Verified locally end-to-end: 3 cold-start subprocess scans
  (helper GUI killed between runs to defeat warm-cache effects)
  return 100% unredacted rows.

## [1.0.5] — 2026-05-13

User on macOS 26 installed v1.0.4 via the one-liner and ended up
with a helper bundle whose TCC grants never landed — `tccutil
reset` even reported "Failed to reset" because the bundle id had
no TCC entry at all. The popup window had fired and auto-closed
before the user saw it, and the macOS permission prompts went
with it.

### Fixed
- **install.sh launches the helper foreground, not `open -g`
  (background).** macOS 26 was firing the bundle, showing prompts
  briefly, and tearing them down before the user could click
  Allow on either dialog. install.sh now does plain `open` so
  the helper's status window appears on top, the macOS prompts
  layer over it, and the user has time to actually grant the
  permissions before the auto-close timer kicks in.

## [1.0.4] — 2026-05-13

User reported macOS's TCC permission prompts were inconsistent:
the Location prompt showed "谛听 · 天耳" (Chinese display name)
while the Bluetooth prompt showed "diting-tianer.app" (raw bundle
filename) — and both prompt bodies were always English even for
zh users. macOS picks the TCC prompt's header name from different
fields per category (`CFBundleDisplayName` for Location, the
bundle's URL filename for Bluetooth), and the prompt body comes
straight from the usage-description plist keys.

### Fixed
- **TCC prompts now localise consistently.** Helper bundle ships
  `Resources/en.lproj/InfoPlist.strings` and `Resources/zh-Hans.lproj/
  InfoPlist.strings` with locale-specific `CFBundleDisplayName`,
  `CFBundleName`, and all three usage-description keys
  (`NSLocationUsageDescription`,
  `NSLocationWhenInUseUsageDescription`,
  `NSBluetoothAlwaysUsageDescription`). macOS now picks Chinese
  strings for zh users in both the Location and Bluetooth prompt
  headers AND bodies. `CFBundleLocalizations` lists both
  locales so older macOS releases that don't autodiscover lproj
  dirs still pick the right one. `helper/build.sh` copies the
  `Resources/*.lproj` tree into the assembled `.app`.
- **Top-level `Info.plist` `CFBundleName` / `CFBundleDisplayName`
  unified.** Both keys now default to `diting · tianer` (English
  fallback) instead of the previous split where `CFBundleName` was
  `diting-tianer` and `CFBundleDisplayName` was `谛听 · 天耳` —
  the split was what produced the language-inconsistent prompts
  in the first place.

## [1.0.3] — 2026-05-13

First end-user-installed release surfaced a long-latent CoreWLAN
bug that only bites under the install.sh flow, plus two small
helper-popup UX issues. v1.0.2's install path worked but `diting`
itself hung at "需要以下权限：定位服务" because the helper's `scan`
subcommand kept returning redacted BSSIDs even after the user
clicked Allow.

### Fixed
- **Wi-Fi scan unredacts under install-script TCC grants.** Two
  parallel issues kept BSSIDs / SSIDs `null`:
  1. The helper's `scan` subcommand inherited responsibility from
     its terminal parent, so tccd attributed the request to
     Terminal (no `NSLocationUsageDescription`) instead of the
     bundle. The BLE path has done a
     `responsibility_spawnattrs_setdisclaim` re-exec since
     v0.5.0; `scan` now does the same hop.
  2. macOS 14.4+ / 26 requires an active `CLLocationManager` in
     the calling process at the moment of `scanForNetworks` — the
     bundle's TCC grant on disk is necessary but not sufficient.
     The `scan` subcommand now initialises a `CLLocationManager`
     and calls `startUpdatingLocation()` before the CoreWLAN
     call, mirroring what the GUI bundle has always done.
  The earlier code comment claiming CoreLocation was "more
  lenient than CoreBluetooth" was wrong — verified locally that
  with both fixes BSSIDs / SSIDs / IE diagnostics flow as
  expected.

### Changed
- **Helper popup window is localised.** When `DITING_LANG=zh` (passed
  via `open --env` from Python's launcher) or when macOS's
  `Locale.preferredLanguages` starts with `zh`, the popup window
  shows Chinese instead of English. Title becomes "diting 天耳",
  body / status lines translate accordingly. The first-launch
  install.sh popup also picks up zh automatically for users on a
  Chinese-locale Mac.
- **Helper popup auto-close delay 1.5s → 4s.** Users reported the
  "All permissions granted" confirmation flashed by too fast to
  read; 4 s is long enough to comfortably take in without being
  annoying. The Python launcher's polling loop picks up the
  grants immediately regardless of how long the window stays up.

## [1.0.2] — 2026-05-13

Second hot-fix to the v1.0.0 release pipeline. v1.0.1 unblocked the
Swift helper build but the per-arch tarball step then failed on
two further issues that surfaced once the pipeline got further:

1. `scripts/package_release.sh` invoked `tar` with GNU-only flags
   (`--owner=0 --group=0 --numeric-owner`) which macOS bsdtar
   rejects outright. The fallback path I added for
   `--no-mac-metadata` still kept those flags, so the tarball
   command failed on the hosted runners.
2. The PyInstaller-frozen binary crashed on first run with
   `ImportError: attempted relative import with no known parent
   package`. PyInstaller compiled `cli.py` as a top-level script,
   stripping the `diting` package context that the module's
   `from .x import y` imports rely on.

End users with v1.0.0 or v1.0.1 should install v1.0.2 — those tags
never produced consumable assets. `install.sh` resolves "latest"
by default, so the curl one-liner picks v1.0.2 automatically.

### Fixed
- **Tarball builds on macOS bsdtar.** Drop the GNU-only
  `--owner=0 --group=0 --numeric-owner` flags from
  `scripts/package_release.sh`; plain `tar -czf` runs everywhere.
  Tarball reproducibility (deterministic uid/gid headers) was a
  nice-to-have, not load-bearing — SHA256 in `SHASUMS256.txt`
  remains the integrity guarantee.
- **Frozen binary preserves package context.** New
  `scripts/frozen_entry.py` stub imports `diting.cli:main`, and
  PyInstaller now compiles the stub (with `--paths src`) instead
  of `cli.py` directly. Relative imports inside the diting
  package resolve correctly at runtime.

## [1.0.1] — 2026-05-13

Hot-fix for the v1.0.0 release pipeline. The Swift helper source
had a trailing comma in a function-call argument list — a
Swift 6.1 feature accepted by newer local Xcode but rejected by
the hosted `macos-14` runner's older Swift toolchain. v1.0.0's
release workflow died on `Build Swift helper` before producing
any artefacts, so the GitHub Release had no tarballs and the
curl-bash one-liner returned 404.

v1.0.0 carried no consumable assets; v1.0.1 is what end users
should install. `install.sh` resolves the latest tag by default,
so `curl … | bash` automatically picks v1.0.1 with no flag
needed.

### Fixed
- **Swift helper builds on hosted CI runners.** Removed the
  trailing comma in `helper/Sources/diting-tianer/main.swift`
  Find My / AirTag detection branch so the helper compiles on
  Swift 5.x as well as 6.x.

## [1.0.0] — 2026-05-13

**The "just diting" release.** The install ceiling drops from "clone
the repo, install uv, build the Swift helper, run uv sync" to a
single curl-bash one-liner that ships a self-contained binary plus
the helper bundle. End users no longer need Python, `uv`, or Xcode
Command Line Tools on their machine. The TUI gets one last round of
polish: a unified row-select gesture across all three list panels
(Wi-Fi / BLE / Bonjour), each with its own detail modal that walks
the list live as the user presses ↑ / ↓.

### Added
- **One-line installer.** `curl -fsSL
  https://raw.githubusercontent.com/chenchaoyi/diting/main/install.sh
  | bash` detects arch (`darwin-arm64` / `darwin-x86_64`), pulls the
  matching tarball from the GitHub Release, verifies SHA256, extracts
  to `~/.local/share/diting/`, symlinks `~/.local/bin/diting`, copies
  the Swift helper to `~/Library/Application Support/diting/`, strips
  the quarantine xattr, and `open -g`s the helper once to prime TCC
  prompts. PATH-update hint for zsh / bash / fish printed when
  `~/.local/bin` isn't on PATH. `DITING_VERSION=vX.Y.Z` env var pins
  a specific release.
- **PyInstaller release pipeline.** New GitHub Actions workflow
  (`.github/workflows/release.yml`) triggered by `v*` tag push;
  `macos-14` arm64 + `macos-13` x86_64 matrix builds the helper,
  freezes the Python interpreter + deps via PyInstaller, packages
  the tarball, and uploads to the GitHub Release. A follow-up job
  aggregates `SHASUMS256.txt` from both arch builds.
- **Wi-Fi detail modal** (`i` / `Enter` / mouse-click on any scan
  row). Identity (SSID / BSSID / AP-name from `aps.yaml` / OUI
  vendor / "(associated)" annotation), Radio (channel / band /
  width / PHY / security), Signal (RSSI / noise / SNR), Beacon IE
  (BSS load, station count, 802.11r/k/v support — section omitted
  when all absent), Activity. BSSID redaction shows an actionable
  TCC hint instead of going silent.
- **Bonjour detail modal** (same gesture on the mDNS panel).
  Identity (instance / service type / category via i18n / vendor),
  Network (host / port / IPv4 + IPv6 addresses listed separately),
  TXT records with auto-fold for values > 60 chars (`<N-byte
  payload>` placeholder + 16-byte hex preview so AirPlay receivers
  with 30+ keys don't blow out the modal), Activity.
- **Live navigation inside any detail modal.** While a modal is
  open, ↑ / ↓ advance the underlying selection AND the modal body
  re-renders to track the new row. Walk a list of APs, BLE devices,
  or Bonjour services without close-and-reopen cycles. BLE modal
  also re-fetches per-device RSSI history so the sparkline updates.

### Changed
- **Unified row-select gesture across all three list views.** The
  ↑ / ↓ / `i` / `Enter` / mouse-click contract that BLE has had
  since v0.7 now applies to Wi-Fi and Bonjour too. Each panel's
  arrow-key action is view-gated so the same physical key is safe
  across views. Pin in `openspec/specs/tui-shell/spec.md` so future
  list panels inherit the contract by default.
- **`find_helper()` search order gains a fifth candidate**:
  `~/Library/Application Support/diting/diting-tianer.app`, where
  the curl-bash installer drops the bundle. The in-repo dev build
  stays pinned first so contributors running `uv run diting` from
  a checkout always pick up their freshly-`make helper`ed bundle.
- **README** leads with the one-liner; the existing clone + `uv
  sync` + `make helper` flow moves under "From source (for
  contributors)" — preserved exactly. Both paths coexist on the
  same machine.

### Fixed
- **Wi-Fi selection collides cleanly under TCC-redacted scans.**
  When BSSID is `None` (Location Services denied), the selection
  key falls back to `f"{ssid}#{channel}"` so users without grants
  can still navigate the list. Documented collision behaviour for
  the same-SSID-on-same-channel edge case.
- **Modal-close keys don't mutate selection.** `Esc` / `i` / `q`
  close any detail modal without clearing the panel highlight, so
  reopening returns to the same row.

### Bookkeeping
- **`docs/RELEASE.md`** (+ `docs/zh/RELEASE.md` mirror) — maintainer
  runbook for cutting a release: version bump, tag, watch the
  workflow, manual smoke, GitHub Release notes, dispatch dry-runs,
  troubleshooting (PyInstaller hooks, Gatekeeper, future `macos-13`
  runner retirement).
- **`docs/workflow.md`** (+ ZH mirror) notes that `uv run diting` is
  the developer path and the curl one-liner is the end-user path;
  both are first-class.
- Canonical OpenSpec count: 17 → 20 (new `wifi-detail-modal`,
  `bonjour-detail-modal`, `installation`; modified `ble-detail-modal`,
  `tui-shell`, `macos-helper`).

## [0.9.0] — 2026-05-12

The **Bonjour release.** diting grows a third TUI panel — mDNS /
Bonjour service discovery — alongside Wi-Fi and BLE, and adopts an
always-visible 3-view tab indicator so the user discovers from any
single screen that three views exist. `--notify` finally covers all
three anomaly event types with per-target debouncing. Plus a long
list of i18n polish, BLE Categories cleanup, and analyze CLI fixes
surfaced by the autonomous `/tui-audit` cycles between 2026-05-11
and 2026-05-12.

CHANGELOG bookkeeping note: with the OpenSpec-archive-as-history
workflow now stable, this file is **maintained at release time
only** (not per-PR). For the granular per-change rationale, see
`openspec/changes/archive/`.

### Added
- **mDNS / Bonjour discovery** as a third TUI panel alongside Wi-Fi
  and BLE. Press `n` to cycle the view through Wi-Fi → BLE → mDNS
  → Wi-Fi. The new panel lists service-instance announces on the
  local link (AirPlay, Chromecast, Sonos, printers, NAS, HomeKit,
  Bonjour workstations, etc.) with vendor / name / service category
  / age / host columns. Passive listen-only via the `zeroconf`
  library; subscribes to a curated set of well-known service types
  (no meta-discovery flood). The poller is lazy — users who never
  cycle past BLE pay neither the import nor the background-thread
  cost. Categories translate to ZH like the rest of the TUI. New
  capability `mdns-scanning`; `tui-shell` updated for the 3-way
  toggle. Dependency: `zeroconf >= 0.130`.
- **Anomaly watchdog mode.** `--notify` now raises a macOS
  Notification Centre banner for all three anomaly event types
  (`rf_stir`, `latency_spike`, `loss_burst`) and is valid on both
  `diting monitor --notify` (headless) and the default TUI
  subcommand (`diting --notify`). A per-(event-type, target)
  silence window debounces sustained anomalies so the banner cadence
  is one per minute per affected target, not one per detector tick.
  Two env vars tune behaviour without a recompile:
  `DITING_NOTIFY_SILENCE_S` (3–3600, default 60) overrides the
  silence window; `DITING_NOTIFY_STIR_CONFIDENCE` (`high` /
  `medium` / `all`, default `high`) loosens the `rf_stir` severity
  gate. Invalid values fall back to the default with a one-line
  stderr warning. Silence-window state is in-memory only and resets
  on restart. JSONL event streams are NOT debounced — only the OS
  notification side-effect is. Plain `diting` and plain
  `diting monitor` continue to fire NO notifications, matching
  pre-0.8.0 behaviour byte-for-byte.
- **Xiaomi / Anhui Huami manufacturer-data decoder** under
  `src/diting/decoders/xiaomi.py`. Conservative: recognises the
  frame, surfaces `xiaomi.cid` / `xiaomi.frame_seq` /
  `xiaomi.body_hex` / `xiaomi.body_len`, doesn't invent semantic
  field names (Xiaomi hasn't published a spec). Plus a
  vendors-line fold annotation summing `merged_count - 1` so the
  user reads "20 Anhui Huami devices · (+8 folded)" instead of
  worrying that RPA rotations are inflating the count.

### Changed
- **Always-visible tab indicator** in the third-slot panel's border
  title. Every view shows `Wi-Fi · BLE · Bonjour` with the active
  view styled bold-cyan and the other two dimmed. Panel-specific
  detail (`Nearby BSSIDs (N) · sort: AP`, etc.) moves to the
  panel's `border_subtitle` (bottom of frame). Closes the
  discoverability gap surfaced by the post-merge audit of the
  mDNS panel.
- **Header subtitle** uses the user-facing view name (`view: Wi-Fi`
  / `view: BLE` / `view: Bonjour`) instead of the internal mode
  token.
- **Help modal + READMEs** describe `n` as the 3-way cycle
  (`Wi-Fi BSSIDs → BLE → Bonjour`).
- **BLE Name column cascade** — `d.name → d.type → d.device_class →
  (unknown)`. Rows whose helper tagged them `Find My target` /
  `MS device beacon` / `Apple Proximity` etc. now render the type
  name instead of `(unknown)`. Services column simplifies to just
  the service-UUID category (no more `Find My target · Find My`
  duplication across two columns).
- **Bonjour row rendering polish**: Name column strips the
  redundant `._<service-type>.local.` suffix and RAOP rows drop
  their `<MAC-as-hex>@` machine prefix. Host column widened from
  18 → 26 cells and the universal `.local` suffix stripped — typical
  workstation names like `ccy-MBP2024-M4-Office` no longer truncate
  mid-word.
- **`Tx / Max` row** drops the redundant trailing `max` / `最大`
  suffix (the row label already says Max).
- **`analyze` time-range** renders the end date when the session
  crosses midnight. Previously `2026-05-10 22:04 → 13:01 (14h 57m)`
  forced the reader to mentally subtract the duration; now end
  carries `YYYY-MM-DD` when the local date differs from the start.

### Fixed
- **44 ZH catalog gaps closed** including the entire `BLEDetailScreen`
  modal (Identity / Activity / Services section headings, every
  field label, the inline annotations, the `Esc / i 关闭` close
  hint). Help modal `r` key whitespace bug fixed
  (`~5s` ↔ `~5 s` catalog/call-site mismatch). Panel short-names
  in the help modal now properly translate.
- **RF-stir confidence enum** (`medium` / `high` / `low`) renders
  translated (`中` / `高` / `低`) in the events modal under ZH —
  previously leaked raw English from a bare f-string.
- **`% loss` suffix** on latency-spike events translates to `丢包`
  under ZH (was bare English).
- **Analyze stir-aggregates labels** (`modes:` / `confidence:` /
  `locations:`) translate properly.
- **`service types` i18n leak** in the mDNS diagnostic row
  (catalog-key whitespace mismatch).
- **BLE Categories diagnostic** no longer counts protocol-utility
  GATT services (`1800` Generic Access, `1801` Generic Attribute,
  `180A` Device Information) as device kinds. Per-row Services
  column still renders them.
- **Connected BLE rows** display `online` / `在线` instead of `—`
  in the last-seen column (connected by definition means live).
- **BLE diagnostic Categories** reorders to count-first format
  (`8 iPhone` not `iPhone 8`) so it doesn't read as a model
  number.

### Removed
- Dead `_environment_line` helper in `src/diting/tui.py` — had no
  production callers (only one unit test exercised it), shadowed
  the still-used `_environment_lines`. Cleanup.

### Bookkeeping
- **CHANGELOG policy change**: as of 0.9.0, this file is maintained
  at release time only. Per-PR changes are captured by their
  OpenSpec proposal under `openspec/changes/`; on release, the
  archived proposals since the last tag get summarised here. See
  `docs/workflow.md` for the updated policy.

## [0.8.0] — 2026-05-10

The "diting" release. Project renamed from `wifiscope` to **谛听
(Diting)**, README realigned to lead with the new positioning
("your Mac hears more than it tells you"), the BLE deep-
identification pipeline + decoder framework + detail modal stack
shipped, the SDD workflow + 15 canonical specs were backfilled,
and a design-system audit applied uniformly across voice / type /
iconography / layout. v0.x rules — minor-version breakage allowed
— are exercised here for the env-var rename and helper bundle ID
change.

### BREAKING — project rename: `wifiscope` → `diting (谛听)`

The project is renamed to **谛听 (Diting)**. The original name implied
a Wi-Fi-only tool; the project's actual scope (BLE / link health / RF
environment, with LAN / mDNS / sensing roadmap) is much broader.
谛听 — the Buddhist mythical creature whose ear hears all sounds in
ten directions — covers the broader thesis: surface what macOS quietly
perceives but doesn't show.

Tagline: *"Your Mac hears more than it tells you."* /
*「你的 Mac 听见了什么，告诉你。」*

What this means for users:

- CLI binary: `wifiscope` → `diting`
- Helper bundle: `wifiscope-helper.app` → `diting-tianer.app`
  (天耳 / "heavenly ear" — the Buddhist supernatural power 谛听
  itself possesses; the Swift bundle that holds Location Services +
  Bluetooth grants and brokers signals to Python). **You will need
  to re-grant Location Services + Bluetooth on first launch** —
  macOS TCC keys grants by cdhash, and the new bundle has a new ID
  (`com.chenchaoyi.diting.tianer`).
- Environment variables: `WIFISCOPE_*` → `DITING_*` (`WIFISCOPE_LANG`,
  `WIFISCOPE_HELPER`, `WIFISCOPE_INVENTORY`, `WIFISCOPE_GATEWAY`,
  `WIFISCOPE_WAN`, `WIFISCOPE_SCAN_INTERVAL`,
  `WIFISCOPE_LATENCY_WAN_TARGET`). No backwards-compat shim — if you
  had a script with the old names, update it.
- Default JSONL log filename: `wifiscope-<TS>.jsonl` →
  `diting-<TS>.jsonl`
- Python package: `import wifiscope` → `import diting`; PyPI / repo
  follow.
- **Not changed**: code-level Wi-Fi class names (`WiFiBackend`,
  `WiFiPoller`, `MacOSWiFiBackend` describe the *Wi-Fi capability*,
  not the app); the 15 capability spec names; behaviour of any
  feature.
- Historical entries below (v0.7.0 and earlier) still say
  `wifiscope` — those are frozen records of past releases.

### Added
- **Spec-driven development workflow** (`openspec/`). Every
  behaviour-affecting capability is now pinned by a canonical spec
  under `openspec/specs/<name>/spec.md`; new work goes through
  `openspec/changes/<name>/` proposals, archived after merge.
  Workflow rules: `docs/workflow.md` (EN) / `docs/zh/workflow.md`
  (ZH). 15 capabilities backfilled in this release.
- **CI hardened** — `.github/workflows/test.yml` now runs three
  jobs: pytest matrix, TUI snapshot regression (uploads
  `snapshot-output/` on failure), and `openspec validate --strict`.
  PR template at `.github/pull_request_template.md` enforces the
  branch / spec / test / docs / archive checklist.
- **`/opsx:test` slash command** delegates the full self-test
  (pytest + regression + spec validation) to a subagent so the
  parent context stays clean.
- **Per-protocol BLE decoders** under `src/wifiscope/decoders/`:
  iBeacon, Eddystone (UID/URL/TLM), Apple Continuity (Nearby Info
  / Find My / Handoff with multi-subtype walking), Microsoft CDP
  + Swift Pair, RuuviTag Format 5. Plug-in framework via
  `@register`; output keys protocol-namespaced.
- **BLE detail modal** (`i` / `enter`) with keyboard up/down +
  mouse click-to-inspect, RSSI history sparkline (per-device
  `BLEHistory` ring buffer), distance estimate, raw-byte hex
  dumps for manufacturer / service data, and a "Decoded payload"
  section.
- **Helper schema-4 raw passthrough** — `service_data`,
  `tx_power_dbm`, `solicited_service_uuids`,
  `overflow_service_uuids`, and `manufacturer_hex` now reach
  `BLEDevice` so downstream decoders can read CoreBluetooth's
  full advertisement view without re-implementing the bridge.
- **31 Apple BT-MAC OUIs** added to `wifi_ouis.json` so connected
  Magic Keyboard / Trackpad rows resolve to "Apple, Inc." instead
  of `(unknown)`.
- **Vendor lookup chain** now consults `service_data` keys (not
  just `service_uuids`), recovering Xiaomi MiBeacon / Google Fast
  Pair / Microsoft Find My devices that previously dead-ended at
  `(unknown)`. Real-environment coverage improved from 64 % → 99.5 %.
- **`(anonymous)` vs `(unknown)` distinction** — silent broadcasts
  render as `(anonymous)` (physical limit); lookup-chain misses
  with data render as `(unknown)` (actionable decoder gap).

### Changed
- **STIR legend** now reads `current σ > baseline ×2.5 (≥3 dB)` —
  pulled from `DEFAULT_SPIKE_RATIO` / `DEFAULT_SPIKE_MIN_DB` so it
  cannot drift from the firing logic. Previously read `×3`,
  conflating the ratio with the absolute floor.
- **BSSID singular / plural grammar** — `1 wide 2.4 GHz BSSID` vs
  `27 wide 2.4 GHz BSSIDs` now both render correctly in EN.
- **BLE vendor column** truncation signalled with `…` and 16
  consumer-brand aliases (`Hewlett Packard En` → `HP Enterprise`).
- **ZH translation polish** — 16 awkward / ambiguous strings
  rewritten: `σ 是 RSSI 抖动` → `σ 是 RSSI 标准差` (technical
  accuracy), `宽带 BSSID` → `宽信道 BSSID`, `最近` 同屏歧义拆为
  `最强` / `最近见到`, `扫描频率 7s` → `扫描间隔 7s`, etc.
- **`scripts/tui_snapshot.py` explore mode** respects
  `WIFISCOPE_LANG=zh` so audits can run in the ZH UI.

### Fixed
- BLE row navigation keys (`↑` / `↓` / `enter`) win over
  `VerticalScroll`'s built-in scroll handlers via `priority=True`.
  Mouse click on a BLE row also selects + opens detail.
- Diagnostics panel rendering stability in regression — seed helper
  pins `_link_diagnostic_tuple` / `_environment_diagnostic_tuple`
  on the App so a stray refresh cannot wipe seeded Link /
  Environment rows.
- **Help-modal ZH translation for `force re-roam`** — the catalog key
  in `i18n.py` was `cycle WiFi off/on` but the call site at
  `tui.py:426` used `cycle Wi-Fi off/on`, so ZH lookup silently
  fell back to English. Catalog key now matches the call site.

### Docs
- **Spec coverage matrix** in `tests/TESTING.md` (and ZH mirror) —
  every requirement under `openspec/specs/<capability>/spec.md`
  now points to a real test, a `(review-enforced)` convention,
  a `(regression-only)` snapshot scenario, or an honest `(gap)`.
  Coverage holes (cooldown / rearm logic, EventRing length cap,
  footer grouping, subtitle, fit_cells, network-change probe
  reset, atexit writer close, several CLI dispatch paths) are
  now visible instead of implicit.
- **`Wi-Fi` / `WiFi` normalisation** across user-visible prose
  (README, help modal, force-reroam toast). Internal class
  names (`WiFiBackend`, `WiFiPoller`) intentionally untouched.
- **README is now purely user-facing.** Contributor-leaning
  sections (`Specifications`, `Development`, `How it works`)
  moved into a new [`DEVELOPMENT.md`](DEVELOPMENT.md) at repo
  root with a ZH mirror at [`docs/zh/DEVELOPMENT.md`](docs/zh/DEVELOPMENT.md).
  README links to it once near the bottom. The capability index,
  dev commands, bilingual discipline, and BSSID-resolution
  algorithm deep-dive all live in the new doc; nothing was
  deleted, only relocated.
- **README realigned with the new positioning.** The `## Why`
  section now leads with the unifying thesis ("macOS perceives
  more than it shows; Diting surfaces it") and gives Wi-Fi /
  BLE / link-health / RF-environment / events equal billing
  instead of Wi-Fi-first. New `## What you can do with it` lists
  four user-value scenarios. Roadmap rewritten into three
  buckets: Near-term (mDNS / Bonjour, anomaly watchdog mode,
  per-device proximity compass, cellular state), Mid-term
  (scenario / investigate mode, JSONL replay, trend graphs,
  auto-roam), Further out (room-presence sensing as the
  long-term hardware-assisted flagship, menu-bar app, Linux
  backend, Continuity / Hotspot / Private Relay state).

## [0.7.0] — 2026-05-07

The "is the link actually working + what's stirring around me"
release. RSSI alone never tells you whether your gateway is queueing
packets or whether someone just walked past the laptop; v0.7.0 adds
two continuous probes that do.

### Added
- **Continuous latency / loss probe** (1 Hz ICMP via `/sbin/ping`)
  against the user's gateway and an auto-detected WAN anchor — the
  system's currently-configured DNS server, read straight from
  `SCDynamicStoreCopyValue("State:/Network/Global/DNS")` (with a
  `scutil --dns` subprocess fallback). Resolution order: the
  `WIFISCOPE_LATENCY_WAN_TARGET` env var beats auto-detect; when
  the only configured DNS is the gateway itself, the WAN probe is
  skipped and the diagnostic line reads `WAN n/a (DNS == gateway)`
  so the user knows why. DNS detection re-runs every 60 s so a
  network switch updates the anchor without restarting wifiscope.
  Pure ICMP — no raw socket, no sudo. The Diagnostics panel gains a
  `Link  gw 12 ms · 0% loss · WAN 18 ms · 0% loss · jitter 3 ms`
  row; loss / very-high-rtt / unreachable states render with a ⚠
  glyph and red styling.
- **Beacon IE depth in the helper.** `runScanAndDumpJSON` now walks
  CoreWLAN's `informationElementData` for each `CWNetwork` and
  decodes BSS Load (Element ID 11 → `bss_load_pct` +
  `bss_station_count`), Mobility Domain (54 → `supports_802_11r`),
  RM Enabled Capabilities (70 → `supports_802_11k`), and Extended
  Capabilities bit 19 (127 → `supports_802_11v`). Each field is
  emitted only when the IE is present, so v2 / partial-IE consumers
  remain forward-compatible. Schema number stays 3; the new fields
  are additive.
- **Environment monitor.** A new module computes per-BSSID rolling
  RSSI σ, fires `RFStirEvent` when both spec thresholds are met
  (current 5 s σ > 2.5 × trailing 5-min median σ AND > 3 dB
  absolute floor), and surfaces a `stable` / `active` / `quiet`
  qualifier on a new `Environment  σ 1.4 dB / 5s` Diagnostics row.
  Per-AP fusion modes auto-classify by median RSSI: `co_located`
  (>= -65 dBm) does redundancy fusion (a spike on >= 2 co-located
  APs counts as high-confidence); `spatial_channel` (-65 .. -85)
  fires events labelled with the AP's inventory name; `ignored`
  (< -85) is dropped as too noisy. NEVER claimed as people-counting
  or motion detection — the wording on every surface is "something
  changed".
- **Unified Events panel + modal `m` browser.** The v0.6.0 Roam
  log panel becomes the Events panel: same widget slot, same
  height, but accepts roam / rf_stir / latency_spike / loss_burst /
  link_state events through one `append_event` entry point. Each
  row carries a typed prefix (`[ROAM]` / `[STIR]` / `[LATENCY]` /
  `[LOSS]` / `[LINK]`). The new `m` binding opens an
  `EventsScreen` modal — full-screen browser of the last 100
  events, filterable via 1/2/3/4/0 subkeys, with a per-AP σ
  baseline mini-table and a sparkline of σ over the last hour at
  the bottom.
- **`wifiscope monitor` and `wifiscope calibrate` subcommands.**
  `monitor` is a headless long-run that streams JSONL events to
  stdout (or `--out path.jsonl`), with `--notify` raising macOS
  Notification Centre alerts on high-confidence events. Designed
  for Home Assistant / log-pipeline integration. `calibrate`
  records a configurable duration (default 5 min) of "empty room"
  RSSI samples per visible BSSID and writes
  `./wifiscope-baseline.json`; the Environment monitor reads that
  file at startup and switches the diagnostic line label to
  `quiet` / `active` from the default `stable` / `active`.
- **`WIFISCOPE_LATENCY_WAN_TARGET` env var** to pin the WAN probe
  IP for one-off invocations or networks where DNS auto-detection
  picks the wrong anchor.
- **`make monitor` Makefile target** (alias for `uv run wifiscope
  monitor`) for discoverability.
- **EventsScreen preview SVGs** (English + Chinese) so the README
  shows the modal browser. The existing 4 SVGs (Wi-Fi + BLE × EN +
  ZH) remain; `make preview` is now 6.
- **40+ new tests across 4 modules** covering ping output parsing,
  spike / loss-burst detectors, all 7 DNS auto-detection shapes
  the spec calls out, refresh cadence, env-var override, the
  scutil fallback parser, σ → event firing, mode classification,
  redundancy fusion, calibration round-trip, every event-format
  line, the Diagnostics body containing both new rows, and the
  modal open / close flow.

### Changed
- Diagnostics panel now has 7 lines (was 5): adds `Link` and
  `Environment` after the existing visible-networks / warnings /
  recommendations / health / score block.
- The "Roam log" panel is now "Events" — same slot, same height,
  same time-ordered ring, but it accepts every v0.7.0 event type.
- ScanResult dataclass gains `bss_load_pct`, `bss_station_count`,
  `supports_802_11r`, `supports_802_11k`, `supports_802_11v`. Each
  defaults to None so v2 helpers / pre-v0.7.0 cached scans remain
  parseable.

### Known limitations
- The adaptive baseline drifts overnight — leaving the office at
  6 PM and returning at 8 AM will briefly fire false-positive
  events the next morning. `wifiscope calibrate` corrects this for
  users who care.
- `/sbin/ping` reports millisecond precision only; sub-millisecond
  wired LAN reads as 0 or 1 ms.
- Loss-burst detection lags up to 5 s (3-of-5 rule).
- Environment events are correlation, not causation — a neighbour's
  AP rebooting can fire a stir event you did not cause.
- DNS auto-detection ignores DoH / DoT (Firefox encrypted DNS,
  Tailscale MagicDNS); we ping whatever the OS resolver believes
  its upstream is.

## [0.6.0] — 2026-05-07

The "what kind of device + what's actually connected" release. Two
questions the v0.5.0 BLE panel could not answer cleanly: *what is
this thing labelled "Apple, Inc. (anonymous) Find My"?* and *where
are the AirPods I'm listening to right now in this list?* — both
have answers now.

### Added
- **Tier-1 deep identification of public BLE advertisement formats.**
  The Swift helper's new `BLEAdParser` recognises iBeacon (Apple
  manufacturer type `0x02`), AirTag / Find My target (Apple type
  `0x12` ± Find My service `FD5A`), Eddystone in all four frame
  variants (UID / URL / TLM / EID via service `FEAA`), Tile (`FEED` /
  `FEEC`), Samsung SmartTag (Samsung company ID + `FD5A`,
  disambiguated from Apple Find My on the same UUID), and Microsoft
  Swift Pair (Microsoft company ID + leading `0x03`). Apple Nearby
  Info type `0x10` is decoded for its unencrypted device-class
  nibble: `iPhone`, `iPad`, `Mac`, `Apple TV`, `HomePod`, `Apple
  Watch`. Each row's "services" column now leads with this label so
  the panel reads `AirTag · Find My` instead of just `Find My`. Out
  of scope by design: per-model identification (iPhone 14 vs 15
  needs proprietary GATT) and decryption of Continuity payloads
  (lock state, Music-playing — encrypted, per-device-key).
- **Currently-connected peripherals in their own section.** The
  helper periodically calls `retrieveConnectedPeripherals` over a
  fixed union of common service UUIDs (Audio, HID, Heart Rate /
  Battery, Find My, Eddystone, Tile) and emits one
  `{"connected": true, ...}` JSON line per returned peripheral plus
  a `connected_snapshot` sentinel that lets the Python side prune
  rows when a device disappears. The BLE panel renders these as a
  separate `── Connected (N) ──` block above the existing
  `── Advertising (N) ──` block, with `—` in the RSSI column (we
  deliberately do not call `readRSSI()` against an active link —
  too invasive). Connected entries sort alphabetically by name and
  skip the fuzzy merger.
- **`Connected` diagnostic row** appears below the Categories line
  whenever at least one peripheral is connected, with a per-category
  breakdown (`Connected  3 peripherals · 2 Audio · 1 HID`). The
  Categories line itself folds in deep-ID types so iBeacons,
  AirTags, and labelled iPhones surface alongside Audio / HID /
  Heart Rate counts.
- **Schema-3 helper output.** Optional `type` and `device_class`
  fields on each advertisement JSON line; a separate `connected:
  true` channel for connected-peripheral rows. The Python TUI
  tolerates schema-2 helpers (no deep-ID, no connected list) so a
  freshly-upgraded TUI keeps working until the user rebuilds the
  helper bundle.
- **20 new BLE unit tests** in `tests/test_ble.py` plus 7 new TUI
  helper tests covering the deep-ID detection algorithm
  (parameterised across all six Apple device classes), the
  connected-dict routing, the `connected_snapshot` sentinel
  pruning, schema-2 back-compat, mixed-stream routing, and the
  `BLEScanUpdate.connected` propagation through the poller. Plus
  a smoke test that mounts the App, seeds both buffers, presses
  `n`, and asserts both sections render.
- **i18n catalog entries** for the section headers (`已连接` /
  `正在广播`), the peripherals-count phrasing, and the new
  `Find My target` label. Brand-name types (iBeacon, AirTag, Tile,
  SmartTag, Swift Pair, Eddystone-{UID,URL,TLM,EID}) and Apple's
  device-class names stay English in both locales by design — they
  are proper nouns.

### Changed
- BLE preview SVGs (English + Chinese) now show both the
  `Connected (2)` section (AirPods Pro + Magic Keyboard) and the
  `Advertising (8)` section with at least one of each Tier-1
  category labelled (iPhone / AirTag / iBeacon / Eddystone-URL /
  Tile / Mi Band 7 / etc.) so the README hero reflects the v0.6.0
  shape.
- `pyproject.toml` version bumped to 0.6.0.

### Known limitations
- **Apple Continuity encrypted bits stay opaque.** Lock state,
  Music-playing flag, AirDrop session info — all behind a per-device
  key Apple does not publish. We surface device_class via type
  `0x10` only.
- **Connected peripherals have no RSSI / vendor metadata.**
  `retrieveConnectedPeripherals` returns much less than a fresh
  advertisement; the panel renders `—` for the missing signal column
  and leaves the vendor blank rather than fabricating one.
- **Service-UUID enumeration in `retrieveConnectedPeripherals` is
  required.** The hard-coded service list will miss obscure
  peripherals (Bluetooth Mesh nodes, exotic Health Devices). That
  is acceptable for v0.6.0.
- **MAC randomisation persists.** Even with deeper labels, a phone
  seen across a 30-minute window may rotate identifiers several
  times. The fuzzy merger now has more signals to work with (`type`,
  `device_class`) but still cannot guarantee 1:1.

## [0.5.0] — 2026-05-06

The "what electronic devices are around me right now?" release.

### Added
- **Nearby BLE devices view**, toggled with the new `n` binding.
  Replaces the Nearby BSSIDs panel in the same vertical slot
  (Diagnostics, Connection, and Roam log are unchanged) with a
  scrollable list of every BLE peripheral advertising in range —
  AirPods, Apple Watches, BLE keyboards, Find My beacons, smart-home
  gadgets, iBeacons, etc. Both pollers run in parallel from app
  mount, so toggling between the two views is instant and never
  shows a stale "scanning…" state.
- **Bluetooth permission via the existing helper bundle.** The Swift
  sidecar at `helper/wifiscope-helper.app` gains a second TCC
  entitlement (`NSBluetoothAlwaysUsageDescription`) and a new
  `ble-scan` subcommand that streams advertisement events as JSON
  Lines. The helper's GUI mode now requests both Location Services
  and Bluetooth on launch — one Allow click covers both. No new
  Python deps; the existing "permission isolation" architecture
  stays intact.
- **Bundled Bluetooth SIG vendor snapshot** at
  `src/wifiscope/data/bluetooth_vendors.json` (4021 entries) plus a
  new `make update-vendors` target that fetches the upstream YAML,
  records the source commit hash, and rewrites the file. No network
  calls at runtime.
- **UUID-rotation fuzzy merger.** Modern BLE devices rotate their
  identifier for privacy; the merger folds entries sharing
  `(vendor_id, name)` with RSSI within ±10 dB into a single row and
  shows a `(merged N)` badge so the merge is visible, never
  silently. Anonymous beacons (no vendor, no name) are never merged
  to avoid conflating unrelated devices.
- **BLE preview SVGs** at `docs/preview-ble.svg` and
  `docs/preview-ble.zh.svg`, alongside the existing Wi-Fi preview.
  README hero block now shows both with a small caption indicating
  which view each represents.
- **8 new BLE unit tests** in `tests/test_ble.py` covering JSONL
  parsing, vendor lookup, service category inference (Heart Rate /
  HID / Audio / Find My), TTL expiry, fuzzy merging, permission
  denied handling, subprocess crash resilience, and malformed JSON
  recovery.
- **i18n catalog entries** for every new user-visible string —
  panel title, view subtitle, service categories (`音频` / `键盘` /
  `心率` / `查找网络`; iBeacon stays English per spec), placeholder
  messages, and the merged badge.

### Changed
- `make preview` now regenerates four SVGs instead of two; new
  `preview-ble-en` and `preview-ble-zh` sub-targets handle the BLE
  view individually. Wi-Fi targets unchanged.
- Help modal documents the new `n` binding.
- Header subtitle gains a `view: wifi` / `view: ble` segment so the
  active view is always visible.

### Known limitations
- macOS Bluetooth Classic / BR-EDR is out of scope; this release is
  BLE only.
- No Linux / Windows BLE backend yet.
- No GATT connect, pairing, or per-device deep-dive modal.
- Apple Continuity / Handoff payloads are shown as a generic Apple
  device — we do not reverse-engineer the proprietary format.

## [0.4.0] — 2026-05-06

The "speak Chinese too" release.

### Added
- **Simplified Chinese UI**. Every panel title, footer hint, status
  message, diagnostics line, roam-log tag, Help modal section, and
  Wi-Fi Basics term has a Chinese translation that reads naturally
  rather than as a word-for-word port. Industry acronyms (SSID /
  BSSID / RSSI / dBm / SNR / WPA2 / OPEN / ENT / MCS / NSS / Tx / Max)
  stay in English in both languages by design.
- **Static-at-launch language switch.** New `--lang en|zh` CLI flag
  and `WIFISCOPE_LANG` environment variable; with neither, wifiscope
  autodetects from `LC_ALL` / `LC_MESSAGES` / `LANG` (`zh_*` →
  Chinese, anything else → English).
- **CJK-aware column padding.** New `wifiscope.i18n.pad_cells` and
  `fit_cells` use `rich.cells.cell_len`, so a Chinese inventory name
  like `1F-书房` or a translated table header like `频段` consumes its
  two cells per glyph instead of one byte per char. The Connection
  panel labels and the Nearby BSSIDs table header / cells are routed
  through these helpers.
- **Chinese mirror of every doc** under `docs/zh/`: `README.md`,
  `CHANGELOG.md`, `TESTING.md`, `HELPER.md`. Each English original
  carries a `English · 中文` switcher at the top, and each Chinese
  doc links back.
- **Chinese preview SVG** at `docs/preview.zh.svg`, generated from
  the same fake backend as the English `preview.svg`. Run
  `WIFISCOPE_LANG=zh uv run python docs/_capture_preview.py` to
  refresh.

### Changed
- **AP-aliases default path** moves from
  `~/.config/wifiscope/aps.yaml` to `./aps.yaml` (resolved against
  the current working directory). This is a breaking change for
  anyone who already populated the XDG path; `WIFISCOPE_INVENTORY`
  still overrides, so `export WIFISCOPE_INVENTORY=~/.config/wifiscope/aps.yaml`
  preserves the old behaviour. Rationale: most uses run wifiscope
  from the cloned repo, so a CWD-local file lives next to
  `aps.example.yaml` and skips the `mkdir -p ~/.config/wifiscope`
  ceremony. Added `aps.yaml` to `.gitignore` so users do not
  accidentally commit their network topology.
- README's AP-config section reframed as **AP aliases (optional)**
  with a clearer explanation of where mgmt MACs come from (router /
  controller management UI), and an explicit "skip this on
  enterprise networks" note.
- Help modal "Tunables" section now lists `WIFISCOPE_LANG=en|zh` next
  to the existing scan / inventory / helper overrides.
- README "Configuration" table gains a `WIFISCOPE_LANG` row alongside
  the existing env vars.

### Added
- **Makefile** at the repo root with `test`, `test-all`, `preview`,
  `preview-en`, `preview-zh`, `helper`, and `help` targets so the
  bilingual workflow ("UI change → regenerate both preview SVGs")
  is one command instead of remembering an env var.
- README "Maintaining bilingual UI / docs" subsection codifying the
  three sync rules between English and Chinese surfaces (strings,
  docs, preview SVGs).

## [0.3.0] — 2026-05-06

The "make dense Wi-Fi scans understandable" release.

### Added
- **Diagnostics panel** with visible BSSID totals, band distribution,
  hidden-in-this-scan count, open/no-password BSSID count, wide
  2.4 GHz channel warnings, country-code spread, current-channel
  peer count, least-crowded channel hints, current-link health, and
  a simple roam score.
- **Same-SSID roam candidate scoring**. wifiscope now compares the
  current BSSID with clearly better same-name BSSIDs and explains
  when pressing `c` may help the Mac re-roam.
- **Wi-Fi Basics modal** on `b`, explaining SSID, BSSID, AP host,
  RSSI, noise/SNR, band, channel, width, security, roam, and roam
  score in plain language.
- **Scrollable Nearby BSSIDs panel**, so dense office scans can be
  inspected beyond the visible terminal height.
- **Security badges** in scan rows, including an obvious `OPEN`
  marker for no-password BSSIDs.
- **Security decoding** from the macOS helper scan payload.

### Changed
- Nearby scan terminology now uses **BSSID** instead of AP/network
  where the underlying row is one radio identity.
- The scan-list `ch` column is now `channel`, with wider spacing
  around `band`.
- Diagnostics wording distinguishes **hidden in this scan** from
  visible BSSID totals, since hidden SSID beacons can vary between
  CoreWLAN scan snapshots.
- Least-crowded channel hints say `(no AP heard)` when the suggested
  channel was absent from the current scan sample.

## [0.2.0] — 2026-05-06

The "macOS scan list is no longer redacted, and the tool grew up"
release.

### Added
- **Swift helper sidecar** at `helper/`. Tiny Cocoa `.app` whose only
  job is to own macOS Location Services permission so the Python
  TUI can read unredacted SSIDs and BSSIDs for every BSSID in the
  scan list. wifiscope auto-builds and `open`s it on first launch;
  the bundle window auto-quits 1.5 s after the user clicks Allow.
  Subsequent runs go straight to the TUI.
- **`c` binding** to force re-roam by cycling the WiFi radio off
  then on. Cleaner than `disassociate()` (which was unreliable on
  802.1X enterprise networks): the off/on path goes through full
  auto-join with Keychain credentials.
- **`s` binding** to cycle the Nearby APs sort between by-AP
  (default; groups every BSSID under its physical AP with a per-
  group summary line) and by-signal (flat RSSI-sorted).
- **`h` binding** opens a HelpScreen modal that documents the tool,
  the panels, every binding, the inventory schema, and the helper.
- **AP inventory model** refactored to AP-level entries: `aps` list
  with `name` + `mgmt_mac`, plus an optional `radio_overrides` map.
  Resolution is two rules: first-five-octet match with a last-byte
  proximity window (catches H3C controllers that allocate adjacent
  APs out of one OUI block), then octets-2..5 match (covers vendor
  alternate-OUI allocations like H3C `40:` vs `44:`).
- **Auto-discovered cluster labels** (`?XX:YY:ZZ`) for unaliased
  BSSIDs — every radio of one chip collapses under one label even
  without inventory configuration.
- **Connection panel** gained MCS index, NSS, `This Mac` (interface
  MAC), country code, IP / Router, and a Tx vs Max footnote.
- **Per-row signal bar** in the Nearby APs panel matching the
  Connection panel's colour bands (green / yellow / red).
- **Synthetic current-AP row** in the scan list when CoreWLAN's
  scan omits the associated AP, so the user always sees their own
  row at the top with star + inverted background.
- **Hidden network labelling**: empty-SSID beacons render as
  `(hidden)` rather than `(no SSID)`.
- **`WIFISCOPE_SCAN_INTERVAL` env var** to override the 7 s default
  scan cadence (3 s minimum).
- **Test suite under `tests/`** with 83 cases (58 functions; some
  parametrised) covering inventory resolution, helper JSON parsing,
  TUI merge / group helpers, and a headless `run_test` smoke pass
  over every binding. [`tests/TESTING.md`](tests/TESTING.md) is the
  canonical test plan — every automated case has a row in that
  document and changes start there.
- **GitHub Actions CI** running pytest on macOS-latest against
  Python 3.11 / 3.12 / 3.13 for every push and pull request to
  `main`.
- **`CHANGELOG.md`** (this file) and CI / release / license badges
  in the README.
- **User-first README**: hero screenshot, problem statement up
  front, technical design notes deferred. Logo + a deterministic
  TUI preview SVG live under `docs/`.

### Changed
- Scan-list `AP` column renamed to `AP host`. The original "AP" was
  ambiguous with the column to its right (`BSSID`, which also
  identifies an AP); the new label clearly identifies the physical
  device hosting the BSSID.
- Default sort mode is now by-AP. The grouped view is more readable
  on dense corporate scans.
- Scan interval default raised to 7 s. CoreWLAN's scan throttle is
  empirically ~5 s; running below it produces alternating empty
  scans (silent because of the panel's last-non-empty cache, but
  pure waste).
- Channel resolution now reads SCDynamicStore's top-level CHANNEL
  field (the OS's view of the radio's current associated channel),
  falling back to `CachedScanRecord.CHANNEL` only if absent. This
  fixes a mismatch where wifiscope reported the radio's mid-scan
  tune target while macOS's native WiFi panel showed the AP's
  actual operating channel.

### Fixed
- Three APs sharing a `40:fe:95:8a:3c:..` prefix used to all map to
  the first inventory entry. Last-byte proximity now disambiguates.
- `(redacted)` rows are now visually distinct from `(hidden)` and
  from real APs with empty SSIDs.
- `Tx` vs `Max` divergence in the Connection panel is documented in
  a footnote rather than hidden.
- Footer binding hints are no longer stolen by an over-eager
  attribution bar.

### Removed
- The `aliases.yaml` flat BSSID-to-name format. Replaced by the
  AP-level inventory described above; migration is documented in
  the README and on the help screen.

## [0.1.0] — 2026-05-05

First release. macOS-only TUI with three panels (Connection, Nearby
APs, Roam log), AP alias support via a flat `aliases.yaml`, and a
SCDynamicStore tunnel that surfaces the *current* connection's SSID
and BSSID even when CoreWLAN is fully redacted by Location Services
denial. Scan-list identity remains redacted in this release; v0.2's
helper bundle is the proper fix.

See the [v0.1.0 release notes](https://github.com/chenchaoyi/wifiscope/releases/tag/v0.1.0)
for the full changelog of the eight-step initial implementation.
