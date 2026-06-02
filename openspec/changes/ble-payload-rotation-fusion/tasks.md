# Tasks

- [x] 1. `_payload_fuses` pure fn: identical non-trivial payload, same
  (vendor,name), non-Apple, under active-member cap; RSSI-independent.
- [x] 2. `_BLECluster.anchor_mfg_hex` + set in `_create_cluster`.
- [x] 3. `_assign_to_cluster` tries the payload path before the RSSI heuristic.
- [x] 4. Tests: identical-payload fuses across RSSI gap; different payload
  doesn't; Apple excluded; active cap; trivial payload; end-to-end assign.
- [x] 5. TESTING.md EN/ZH.
- [ ] 6. Gates: pytest, snapshot regression, openspec validate (specs + change).
