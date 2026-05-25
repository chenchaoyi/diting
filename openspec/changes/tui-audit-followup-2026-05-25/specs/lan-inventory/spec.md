## MODIFIED Requirements

### Requirement: The poller SHALL read the kernel ARP cache via `arp -an` and parse it for MAC ↔ IP pairs
After the ping sweep completes, the poller SHALL run `arp -an` and parse the output. Each line matching the regex `\(([\d.]+)\)\s+at\s+([0-9a-f:]+)\s+on\s+(\w+)` yields one `(ip, mac, iface)` triple. Lines with `at <incomplete>` SHALL be skipped — those are sweep attempts that got no ARP reply.

macOS `arp -an` strips leading zeros from each MAC octet (e.g. emits `14:51:7e:71:5a:1` rather than `14:51:7e:71:5a:01`). The poller SHALL re-pad each octet to exactly two lowercase hex digits before the triple leaves `_read_arp_cache`. Concretely, every MAC string returned by the function SHALL match the regex `^([0-9a-f]{2}:){5}[0-9a-f]{2}$`. Every downstream consumer (`LANHost.mac`, the LAN list column, the detail modal, the JSONL event log) SHALL receive the canonical zero-padded form.

The poller SHALL NOT read `/proc/net/arp` (Linux path) or attempt any other privileged access. `arp -an` is unprivileged on macOS and the canonical access point.

#### Scenario: Healthy ARP line
- **WHEN** the parser sees `? (192.168.1.42) at de:ad:be:ef:00:01 on en0 ifscope [ethernet]`
- **THEN** it extracts `ip=192.168.1.42`, `mac=de:ad:be:ef:00:01`, `iface=en0`

#### Scenario: Incomplete ARP entry
- **WHEN** the parser sees `? (192.168.1.99) at <incomplete> on en0 ifscope [ethernet]`
- **THEN** the line is skipped silently (no host added to state)

#### Scenario: macOS strips leading zeros
- **WHEN** the parser sees `? (11.10.128.1) at 14:51:7e:71:5a:1 on en0 ifscope [ethernet]`
- **THEN** the returned triple's `mac` field is `14:51:7e:71:5a:01` — every octet zero-padded to two hex digits

#### Scenario: Already-padded line is left alone
- **WHEN** the parser sees `? (192.168.1.42) at de:ad:be:ef:00:01 on en0 ifscope [ethernet]`
- **THEN** the returned triple's `mac` field is `de:ad:be:ef:00:01` (idempotent — no double-padding, no truncation)

#### Scenario: Padded MAC reaches the detail modal
- **WHEN** the LAN view's detail modal opens against the gateway whose raw ARP line emitted `14:51:7e:71:5a:1`
- **THEN** the modal's `MAC` row renders `14:51:7e:71:5a:01`
