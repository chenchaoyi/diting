## Why

Cycling Wi-Fi → BLE → mDNS exposes a noticeable pause on the second
`n` press: ~300 ms – 1 s of unresponsive TUI while the `zeroconf`
package finishes its first import, the `Zeroconf()` constructor opens
a UDP multicast socket and joins 224.0.0.251:5353, and the
`ServiceBrowser` background threads come up. Both of those stages
run inline on the asyncio event loop today, so the BLE view stays
frozen and `n` taps queue up until the work clears.

Almost everyone who reaches BLE also reaches mDNS — they are the two
non-Wi-Fi surfaces the same key cycles through. Paying the cost
during the BLE step (when the user is reading a list of devices) is
imperceptible; paying it on the `n` keystroke that should reveal
mDNS is the only place it hurts.

## What Changes

- Pre-warm the Bonjour stack as soon as the user leaves the Wi-Fi
  view (i.e. on the wifi → BLE step). The poller is built in the
  background; the BLE view is rendered immediately.
- Run the two heavy stages off the asyncio event loop via
  `asyncio.to_thread`:
  - `from .mdns import BonjourPoller` (first import of the
    `zeroconf` package — dominant cost on cold interpreters)
  - `Zeroconf(...)` inside `BonjourPoller._start_browser`
    (multicast socket setup)
- When the consumer task exits via an unexpected exception, reset
  `self._mdns_poller = None` so the next `n` press can re-create it.
  Today the gate sees a non-None poller and refuses, leaving the
  view dead until restart.
- **BREAKING (spec-only)**: the `mdns-scanning` requirement "user
  who only uses Wi-Fi and BLE views never imports `zeroconf`" no
  longer holds. As soon as the user leaves Wi-Fi, the import runs.
  The TUI binding cost is unchanged (we never import `diting.mdns`
  at TUI module load); only the trigger moves from "second `n`
  press" to "first `n` press".

## Capabilities

### New Capabilities
<!-- none -->

### Modified Capabilities
- `mdns-scanning`: relax the lazy-import requirement from "first
  activation of the mDNS view" to "first transition away from
  Wi-Fi view"; add a requirement that the slow init stages run off
  the asyncio event loop; add a requirement that a poller crash is
  recoverable across `n` presses.

## Impact

- `src/diting/tui.py`: `_ensure_mdns_poller`, `_consume_mdns_events`,
  `action_toggle_view`; new module-level `_import_bonjour_poller`
  helper; new `_mdns_starting` instance flag.
- `src/diting/mdns.py`: `BonjourPoller.events()` awaits
  `asyncio.to_thread(self._start_browser)` instead of calling it
  inline.
- No new dependencies, no API surface change, no user-visible UI
  change beyond "the second `n` press no longer pauses".
