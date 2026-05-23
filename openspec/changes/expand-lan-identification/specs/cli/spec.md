## ADDED Requirements

### Requirement: `DITING_LAN_PROBE=0|1` env var SHALL override the scene's `lan_active_probe` default at process startup
The CLI SHALL read the env var `DITING_LAN_PROBE` at process startup. Accepted values:

- `1` — force active LAN probing ON regardless of the active scene's default (overrides `public`'s passive default).
- `0` — force active LAN probing OFF regardless of the active scene's default (overrides `home`/`office`/`audit` defaults).
- unset (or blank) — fall through to the scene default from `scene_defaults(scene)["lan_active_probe"]`.

Any other value (e.g. `true`, `yes`, `on`) SHALL print a one-line stderr warning and fall through as if unset. The env var SHALL be documented in `diting --help` under the global-options section alongside `DITING_LANG`, `DITING_SCENE`, `DITING_LAN_INVENTORY_WIDE`.

A companion env var `DITING_LAN_UPNP_FETCH=0|1` SHALL gate the optional HTTP fetch of UPnP LOCATION URLs. Default is `1` (fetch enabled). Setting `0` keeps M-SEARCH active but skips the follow-up HTTP GET. Same parse rules as `DITING_LAN_PROBE`.

#### Scenario: Public scene forced to probe via env
- **WHEN** `DITING_LAN_PROBE=1 diting` is invoked on a public Wi-Fi (auto-detected scene `public`)
- **THEN** the LAN poller runs NBNS + SSDP + mDNS-meta every sweep tick despite the scene's default `lan_active_probe=False`

#### Scenario: Home scene forced silent via env
- **WHEN** `DITING_LAN_PROBE=0 diting` is invoked at home
- **THEN** the LAN poller runs ICMP + ARP only; no NBNS / SSDP / mDNS-meta packets are emitted

#### Scenario: UPnP LOCATION fetch disabled via env
- **WHEN** `DITING_LAN_UPNP_FETCH=0 diting` is invoked
- **THEN** SSDP M-SEARCH still runs (when scene/env permit) and `LANHost.upnp_server` is populated, but `upnp_friendly_name` / `upnp_model` remain None (no HTTP GET fired)

#### Scenario: Invalid value warns and falls through
- **WHEN** `DITING_LAN_PROBE=yes diting` is invoked in `home` scene
- **THEN** a single stderr warning is printed; the LAN poller defaults to the scene knob (probing ON, since home defaults to active)

#### Scenario: Both env vars documented in --help
- **WHEN** the user runs `diting --help`
- **THEN** the global-options section includes a line for `DITING_LAN_PROBE` and a line for `DITING_LAN_UPNP_FETCH` with brief descriptions, in the same style as `DITING_LANG` and `DITING_SCENE`
