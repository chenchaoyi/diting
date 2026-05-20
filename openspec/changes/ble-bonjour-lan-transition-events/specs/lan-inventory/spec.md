## ADDED Requirements

### Requirement: `LANInventoryPoller` SHALL emit transition events for non-self / non-gateway hosts
`LANInventoryPoller` SHALL emit:

- `LANHostSeenEvent` when a new MAC enters `_state` via the ARP-merge path, EXCEPT when that MAC is the user's own interface MAC (`is_self`) or the gateway IP (`is_gateway`). Self and gateway populate state on every diting launch; emitting events for them would generate a noise event per session and pollute downstream analysis.
- `LANHostDHCPRotationEvent` when an existing tracked MAC is observed at a different IP than the one currently stored. The event is emitted BEFORE the state entry's `ip` field is updated, so the event carries both `previous_ip` and `new_ip`.
- `LANHostLeftEvent` when a tracked MAC's `last_reachable_at` is older than `_HOST_LEFT_TIMEOUT_S` (default 300 s) AND the MAC is absent from the latest ARP triples. The entry is removed from `_state` after the event is emitted, so a future re-appearance fires a fresh `LANHostSeenEvent`.

These transition events SHALL be carried out of the poller alongside the snapshot `LANInventoryUpdate` via the same async iterator. The consumer (TUI loop in `tui.py`) does `isinstance` dispatch.

#### Scenario: New non-self / non-gateway MAC fires seen
- **WHEN** a previously-untracked MAC (not equal to `Connection.interface_mac` and whose IP is not `Connection.router_ip`) enters `_state` after an ARP read
- **THEN** `LANHostSeenEvent` is emitted with the host's identity context (vendor, hostname, bonjour_name, is_randomised_mac)

#### Scenario: Self / gateway do NOT fire seen
- **WHEN** `LANInventoryPoller` runs its first sweep and populates self + gateway entries
- **THEN** no `LANHostSeenEvent` is emitted for either; the only events that flow on the first sweep are for "other" hosts the ARP cache had

#### Scenario: DHCP IP rotation fires before merge
- **WHEN** an existing tracked MAC `aa:bb:cc:11:22:33` (currently at `192.168.1.42`) is observed at `192.168.1.77`
- **THEN** `LANHostDHCPRotationEvent(previous_ip="192.168.1.42", new_ip="192.168.1.77", ...)` is emitted; THEN the state entry's `ip` field is updated to `192.168.1.77`

#### Scenario: Long-silent host departs once
- **WHEN** a tracked MAC's `last_reachable_at` is more than 300 s behind the latest sweep AND the MAC is absent from the latest ARP triples
- **THEN** `LANHostLeftEvent` is emitted ONCE with `seen_for_seconds = last_seen - first_seen` and `last_reachable_ago_seconds = now - last_reachable_at`; the entry is removed from `_state`

#### Scenario: Host that never responded to ICMP can still depart
- **WHEN** an entry whose `last_reachable_at is None` (it sat in ARP cache from before diting started, never responded to a sweep) is no longer in the latest ARP triples AND its `last_seen` is older than `_HOST_LEFT_TIMEOUT_S`
- **THEN** `LANHostLeftEvent` is emitted with `last_reachable_ago_seconds=None`; the entry is removed
