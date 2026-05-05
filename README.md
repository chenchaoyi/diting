# wifiscope

A terminal WiFi monitor for macOS, focused on **roaming visibility**.

Built for inspecting which AP a Mac is associated with on a multi-AP WiFi 6
deployment (AC + panel APs), watching roaming events as they happen, and
giving each BSSID a friendly alias so the human reading the screen does not
have to memorize MAC addresses.

## Status

v0.1, work in progress. macOS only. Linux support is unconfirmed and not
present in this version.

## Stack

- Python 3.11+
- [CoreWLAN](https://developer.apple.com/documentation/corewlan) via `pyobjc`
  (required: `wdutil info` redacts BSSIDs on macOS 14.4+)
- [Textual](https://textual.textualize.io/) for the TUI
- [PyYAML](https://pyyaml.org/) for the BSSID alias config
- [uv](https://docs.astral.sh/uv/) for packaging and environment management

## Quick start

> TODO — wired up once the CLI entry point lands (step 4 of implementation).

## macOS 26 caveats

CoreWLAN's `bssid()` / `ssid()` are redacted to None on macOS 14.4+
unless the host process has been granted Location Services. On
macOS 26, terminal apps (Warp, Apple's Terminal.app, iTerm) often
do not appear in the Location Services list at all — there is no
"+" to add them, and the responsibility-chain trick that used to
register a parent terminal via a child CLI's CoreWLAN call has
been tightened.

wifiscope works around this by reading `CachedScanRecord` from
SCDynamicStore (`State:/Network/Interface/<iface>/AirPort`). The
top-level BSSID and SSID fields there are also redacted, but the
nested NSKeyedArchiver bplist describing the currently associated
AP is not — almost certainly an Apple oversight that may be closed
in a future release. When the fallback is in use, the CLI prints
a one-line `note:`. If both paths fail, BSSID is reported as `n/a`
and the CLI prints a `WARNING:` with remediation steps.

A `.app` bundle distribution that owns its own TCC entry is the
intended long-term fix and is on the roadmap for v0.2.

## License

MIT. See [LICENSE](LICENSE).
