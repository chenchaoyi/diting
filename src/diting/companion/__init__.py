"""Companion bridge — desktop-side pairing + event forwarding to a
paired diting-mobile consumer over an end-to-end-encrypted relay.

The wire contract this package implements is defined canonically in
``openspec/specs/companion-protocol`` (in flight:
``openspec/changes/add-companion-bridge``). The machine-readable half
of that contract — JSON Schema + golden fixtures — lives under
``diting.companion.protocol`` and is vendored by diting-mobile.

This top-level package is intentionally thin during group 1
(protocol artifacts). The sender behaviour (pairing, sink, relay
client, offline queue) lands in later task groups.
"""

from __future__ import annotations
