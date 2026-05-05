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

## License

MIT. See [LICENSE](LICENSE).
