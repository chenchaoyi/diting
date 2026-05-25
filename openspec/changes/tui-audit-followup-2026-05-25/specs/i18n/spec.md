## ADDED Requirements

### Requirement: ZH catalog SHALL close the copy gaps surfaced by the 2026-05-25 ZH-locale `/tui-audit` pass
The ZH catalog in `src/diting/i18n.py` SHALL provide a translation for the public-scene LAN-probe help-modal line, SHALL stop self-mapping the Bonjour `service` sort token, SHALL translate the `Noise / SNR` glossary heading, SHALL preserve the leading space on the bare `" ago"` time-ago key, SHALL stop translating Apple Continuity protocol names (Apple Companion, Apple Nearby Info) with culturally-misleading Chinese ("配对" / "邻近"), and SHALL render the BLE detail Activity ad-interval hint with idiomatic value-last word order.

Concretely, the following catalog rows are normative for the 1.7.2 release:

| EN key | ZH value (normative) | Failure mode without the fix |
|---|---|---|
| `"LAN view, public scene only: open consent modal for a one-shot active probe (NBNS / SSDP / mDNS) — see below"` | `"LAN 视图（仅公共场景）：打开一次性主动探测（NBNS / SSDP / mDNS）的同意弹窗 —— 详见下方"` | Help modal mid-section reads raw English in the ZH UI |
| `"service"` (Bonjour sort-mode token) | `"服务"` | Bonjour panel renders `排序：service` |
| `"Noise / SNR"` (basics-modal section heading) | `"Noise / 信噪比"` | Glossary section heading sits in English while every peer is translated |
| `" ago"` (bare time-ago key) | `" 前"` (leading-space preserved) | `8s前` (no space) collides with `5s 前扫描` (space) on the same screen |
| `"Apple Companion"` (Bonjour service category) | `"Apple Companion"` (brand verbatim, NOT `Apple 配对`) | `配对` reads as Bluetooth pairing in Chinese — wrong mental model for Continuity handoff |
| `"Apple Nearby"` (BLE category) | `"Apple Nearby"` (brand verbatim, NOT `Apple 邻近`) | Half-translated incomplete adjective phrase |
| `"~{n} ms between ads"` (BLE detail Activity hint) | `"广告间隔约 {n} ms"` | EN word order preserved in ZH reads `(~1772 ms 两次广播间隔)` — value before noun |

The catalog SHALL NOT introduce new self-maps (where the ZH value equals the EN key) except for bare brand strings or protocol acronyms that the existing "Acronyms SHALL stay English in the ZH catalog" requirement already covers (e.g. `BSSID`, `NBNS`, `UPnP`).

#### Scenario: User runs `DITING_LANG=zh diting` and opens the help modal
- **WHEN** the help modal (`h`) renders the keybindings section
- **THEN** the shift-P / public-scene line reads in Chinese end-to-end; no raw English row leaks through

#### Scenario: User runs `DITING_LANG=zh diting` and cycles to the Bonjour panel
- **WHEN** the panel sorts by service-category
- **THEN** the border subtitle renders `附近 Bonjour 设备 (N)  ·  排序：服务` (the sort-mode token is translated)

#### Scenario: User runs `DITING_LANG=zh diting` and opens the basics modal
- **WHEN** the modal renders the `Noise / SNR` section
- **THEN** the heading reads `Noise / 信噪比`; the body underneath continues to translate fully

#### Scenario: User runs `DITING_LANG=zh diting` and reads a relative-time field
- **WHEN** the LAN diagnostics row, the LAN detail `可达` row, the BLE detail `首次见到 / 最近见到` rows, or any other site that concatenates `_format_duration_short(ago) + t(" ago")` renders
- **THEN** the value reads `8s 前` (with leading space), consistent with `"  · {n}s ago"` and `"  · scanned {n}s ago"` templates that already preserve the space

#### Scenario: User runs `DITING_LANG=zh diting` and opens the Bonjour panel against an Apple Continuity host
- **WHEN** a service categorised as `Apple Companion` appears in the top-services row OR in the Bonjour list's category column
- **THEN** the cell reads `Apple Companion` (brand string verbatim); the misleading `配对` translation SHALL NOT appear

#### Scenario: User runs `DITING_LANG=zh diting` and opens the BLE detail modal on an Apple device
- **WHEN** the Categories diagnostic row would have read `Apple Nearby` in EN
- **THEN** the ZH render also reads `Apple Nearby` (brand string verbatim); `Apple 邻近` SHALL NOT appear

#### Scenario: User runs `DITING_LANG=zh diting` and opens the BLE detail modal on an active advertiser
- **WHEN** the Activity section renders the ad-count row with ≥ 2 ads over a non-zero span
- **THEN** the parenthesised hint reads `（广告间隔约 1772 ms）` (or whatever computed value) — value last, noun first
