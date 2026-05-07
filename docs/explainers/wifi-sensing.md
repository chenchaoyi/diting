<sub>**English** · [中文](../zh/explainers/wifi-sensing.md)</sub>

# Wi-Fi sensing and where wifiscope sits

If you've heard about Wi-Fi being able to "detect motion through
walls", "count people in a room", or "monitor breathing without a
camera" — yes, that's a real research field. It's called **Wi-Fi
sensing**. Whether wifiscope can do it is a question we get asked
often enough to deserve a written answer.

## Short answer

**No, and on purpose.** wifiscope is a macOS terminal monitor for
Wi-Fi roaming and signal quality. The fancy sensing capabilities
above all require **Channel State Information (CSI)** — per-
subcarrier amplitude and phase data — which macOS does not expose
to user-space code. We work with what CoreWLAN gives us: RSSI,
channel, BSSID, etc. That's enough to build a useful dashboard;
it's not enough to do pose estimation.

## The capability ladder

Wi-Fi sensing isn't one thing. It's a spectrum from "feasible
today" to "research demo only":

| Tier | What | Hardware needed | Reliability |
|---|---|---|---|
| **0. RSSI variance** | "RF environment is stirring" / coarse motion | Any Wi-Fi card | Decent for line-of-sight motion |
| **1. CSI presence** | Empty vs occupied, distinguish 1 person walking | ESP32, Intel 5300, or research NIC | Good with calibration |
| **2. CSI activity recognition** | Walking / sitting / falling, gestures | Above + trained ML model | Decent in trained environment |
| **3. CSI vital signs** | Breathing rate, heart rate | Above + clean SNR + bandpass filtering | Real research, controlled environments |
| **4. CSI pose / through-wall** | 17-point body pose, multi-person tracking | Multistatic mesh + heavy ML | Research only, no production-grade implementation |

wifiscope sits **firmly in tier 0**, and only because RSSI is the
data we already collect for the roaming dashboard.

## Why CSI is not available on macOS

Apple's Wi-Fi driver and firmware are signed, closed, and accessed
only via private frameworks that don't expose CSI. The
[`nexmon_csi`](https://github.com/seemoo-lab/nexmon_csi) firmware-
patching project — which is the canonical way to get CSI from
Broadcom chips — supports Raspberry Pi and certain Linux laptops
but **not** macOS or Apple Silicon Macs. There is no public CSI
API on macOS today. Apple Silicon makes the path harder, not
easier.

For real CSI work, the practical options are:

- **ESP32** + [`espressif/esp-csi`](https://github.com/espressif/esp-csi)
  or [`StevenMHernandez/ESP32-CSI-Tool`](https://github.com/StevenMHernandez/ESP32-CSI-Tool)
  — $5 hardware, well-documented, broadly used in research.
- **Intel 5300 / AX200 / AX210** NIC under Linux — research-grade.
- [`Gi-z/CSIKit`](https://github.com/Gi-z/CSIKit) for Python
  processing of CSI from any of the above.

These projects exist; we link to them rather than reimplementing
them poorly inside wifiscope.

## What you should ignore

Search results on this topic are noisy. Be careful with projects
that promise tier-3 or tier-4 capabilities (vital signs, pose,
through-wall sensing) as turn-key open-source code. The pattern to
recognise:

- Long technical-sounding pipelines with named stages
  ("gestalt / sensory / topology / coherence / search / model")
- Specific accuracy numbers cited without paper / benchmark links
- Claims that work "with any Wi-Fi router" out of the box
- Star count not matched by working demos or third-party
  reproductions

These are red flags for AI-generated boilerplate that doesn't run.
The 2025-2026 [Hacker News thread on RuView](https://news.ycombinator.com/item?id=46388904)
is one extended example. The underlying *science* is real (CMU's
WiFi-DensePose paper, MIT's vital-radio work) — but turning that
into a `pip install` is a research-grade project, not a weekend.

## What wifiscope adds at tier 0 (v0.7.0)

Without overclaiming, the RSSI / Tx-rate data we already poll
supports — and as of **v0.7.0 actually drives** — three concrete
surfaces:

- An **environment-stability indicator**, the new `Environment`
  line in the Diagnostics panel. Format: `Environment  stable σ
  1.2 dB / 5s`. The label is one of `stable` / `active` / `quiet`
  (the last only when an opt-in calibration baseline from
  `wifiscope calibrate` is loaded). NEVER "N people" or "motion
  direction" — the wording rule is non-negotiable.
- **Motion event logging** — when current 5 s σ exceeds 2.5 ×
  trailing 5-min median σ AND the absolute σ exceeds 3 dB, an
  `rf_stir` event is appended to the unified events ring. Confidence
  is `high` when the spike shows up on >= 2 co-located APs at once
  (RSSI >= -65 dBm), `medium` otherwise. Open the events modal with
  `m` to browse the last 100; consume them as JSONL via `wifiscope
  monitor`.
- **Occupancy `quiet` vs `active`** — `wifiscope calibrate`
  records 5 minutes of "the room is empty" baseline RSSI and
  writes `./wifiscope-baseline.json`. With that file present, the
  Environment line label becomes `quiet` / `active` instead of
  `stable` / `active`. Anything beyond binary occupancy is
  unreliable on RSSI alone and we deliberately do not implement
  it.

These are not "Wi-Fi sensing" in the academic sense; they are
honest derivative metrics from the data we already have. The
`Environment` line is the live example of what you can
responsibly derive from RSSI alone — anything richer (presence
behind walls, body pose, vital signs) needs CSI hardware that
macOS does not expose.

## If you want real Wi-Fi sensing

It's a separate project. Get an ESP32-S3, flash the ESP-CSI
toolkit, and visualise the stream. wifiscope's scope ends at
"what your Mac's radio sees"; CSI sensing starts where you add
external dedicated hardware. We may write a companion repo for
that some day, but it will not live inside this codebase.
