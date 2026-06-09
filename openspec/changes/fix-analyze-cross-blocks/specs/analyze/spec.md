# analyze delta — fix-analyze-cross-blocks

## ADDED Requirements

### Requirement: Cross-session render blocks SHALL honor locale and rank BLE by stable identity
The cross-session render blocks SHALL render their section headers and labels
in the active UI language — hour-of-day chart, day×hour heatmap, per-network
ranking, daily trend, and top contributors — no block SHALL emit untranslated
English under `--lang zh`. The top-contributors BLE sub-ranking SHALL key on the
stable familiarity identity (the same ladder the population aggregate uses),
NOT the rotating BLE `identifier`, so it ranks distinct physical devices by
total sightings rather than producing one row per rotated address. Sightings
with no stable identity SHALL be skipped, not ranked.

#### Scenario: Cross-session blocks are localized
- **WHEN** `diting analyze <long-log> --lang zh` renders the temporal / cross-session blocks
- **THEN** their headers (hour-of-day, heatmap, networks, trend, top contributors) are in Chinese, not English

#### Scenario: BLE contributors rank physical devices, not rotated addresses
- **WHEN** one physical BLE device is seen many times across many rotated `identifier` values
- **THEN** the top-contributors BLE ranking lists it once with its total sighting count, not many rows each counting one
