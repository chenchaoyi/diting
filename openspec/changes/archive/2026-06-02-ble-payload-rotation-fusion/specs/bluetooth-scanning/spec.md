# bluetooth-scanning — delta

## ADDED Requirements

### Requirement: Rotation merge SHALL fuse identifiers sharing an identical manufacturer payload
The transition-event cluster merger SHALL treat two adverts under the same
`(vendor_id, name)` that carry an identical, non-trivial manufacturer-data
payload as the SAME physical device and fuse them into one cluster,
INDEPENDENT of RSSI — because a privacy-rotating device keeps its payload
across MAC/UUID rotations while the signal may drift past the RSSI window. This
payload-equality path SHALL run before the RSSI/services heuristic.

It SHALL exclude Apple (company-id 0x004C), whose Continuity status payloads
are generic (one payload broadcast by many distinct devices and so would
over-merge); SHALL ignore header-only / near-empty payloads (no body beyond the
company-id prefix); and SHALL NOT fuse when the number of concurrently-active
members already sharing the payload exceeds a fixed cap, as a backstop against
any other generic broadcaster.

#### Scenario: Wearable rotation with drifted signal fuses
- **WHEN** a Huami advert rotates to a new UUID with the same manufacturer payload but an RSSI 40 dB from the cluster anchor (outside the ±10 dB window)
- **THEN** it joins the existing cluster (no new seen / left), where the RSSI heuristic alone would have started a fresh cluster

#### Scenario: Distinct same-vendor devices stay separate
- **WHEN** two anonymous same-vendor adverts carry different manufacturer payloads and signals outside the RSSI window
- **THEN** they remain separate clusters — different payload, no fusion

#### Scenario: Apple payloads are not fused
- **WHEN** two Apple adverts share an identical Continuity status payload at different RSSI
- **THEN** payload fusion does NOT apply (Apple is excluded), so generic shared status frames never merge distinct devices
