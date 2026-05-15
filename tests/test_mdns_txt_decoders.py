"""Tests for `diting.mdns_txt_decoders`.

Each decoder takes a raw TXT value, returns `(label, value)` or
abstains with `None`. The harness wraps every invocation in a
try-except as a safety net — decoders MUST not raise even on
malformed input.
"""
from __future__ import annotations

from diting.mdns_txt_decoders import decode_txt, decoded_keys


def test_decoded_keys_includes_starter_set():
    """The registry SHALL contain at minimum the starter-set keys
    (`model` / `osxvers` / `srcvers` / `deviceid`)."""
    keys = decoded_keys()
    assert "model" in keys
    assert "osxvers" in keys
    assert "srcvers" in keys
    assert "deviceid" in keys


def test_decode_model_known_apple_id_maps_to_friendly_name():
    """A registered model identifier (`MacBookPro18,1`) decodes to a
    human-readable product name with the raw id in parens."""
    out = decode_txt({"model": "MacBookPro18,1"})
    assert ("model", "MacBook Pro 16-inch (M1 Pro, 2021) (MacBookPro18,1)") in out


def test_decode_model_unknown_id_passes_through_raw():
    """Unknown model ids still surface — the raw identifier is
    meaningful even without a friendly mapping."""
    out = decode_txt({"model": "FutureMac99,1"})
    assert ("model", "FutureMac99,1") in out


def test_decode_model_empty_string_abstains():
    """Empty value → abstain. Decoders MUST return None rather than
    surface an empty row."""
    out = decode_txt({"model": ""})
    assert all(label != "model" for label, _ in out)


def test_decode_osxvers_known_major_renders_macos_name():
    """macOS 26 (Tahoe) and earlier majors render with the codename."""
    out = decode_txt({"osxvers": "26"})
    assert ("macOS", "Tahoe (26)") in out
    out = decode_txt({"osxvers": "15"})
    assert ("macOS", "Sequoia (15)") in out


def test_decode_osxvers_non_integer_abstains():
    """Non-digit value → not a valid macOS major. Abstain."""
    out = decode_txt({"osxvers": "abc"})
    assert all(label != "macOS" for label, _ in out)


def test_decode_srcvers_passes_through():
    """Firmware version is opaque; render verbatim."""
    out = decode_txt({"srcvers": "405.6"})
    assert ("firmware", "405.6") in out


def test_decode_deviceid_recognises_canonical_mac():
    """A 17-char colon-separated MAC parses; lower-case normalised."""
    out = decode_txt({"deviceid": "AA:BB:CC:DD:EE:FF"})
    assert ("device MAC", "aa:bb:cc:dd:ee:ff") in out


def test_decode_deviceid_rejects_non_mac_value():
    """Strings that don't match the MAC shape abstain rather than
    surface a bogus 'device MAC' row."""
    out = decode_txt({"deviceid": "not-a-mac"})
    assert all(label != "device MAC" for label, _ in out)


def test_decode_txt_preserves_registration_order():
    """`decode_txt` iterates the registry in registration order so
    the rendered output is stable across runs."""
    out = decode_txt({
        "model": "MacBookPro18,1",
        "osxvers": "15",
        "srcvers": "405.6",
        "deviceid": "aa:bb:cc:dd:ee:ff",
    })
    labels = [label for label, _ in out]
    # All four expected fields land in registration order
    # (model → osxvers → srcvers → deviceid).
    assert labels == ["model", "macOS", "firmware", "device MAC"]


def test_decode_txt_ignores_unknown_keys():
    """Keys without a registered decoder are silently skipped."""
    out = decode_txt({"unknown_key": "value"})
    assert out == []


def test_decode_txt_decoder_exception_does_not_propagate():
    """Belt-and-braces: even if a decoder raises (which it MUSTN'T),
    the harness catches it and continues. We register a buggy
    decoder, prove it doesn't break the harness."""
    from diting.mdns_txt_decoders import register
    # Register a decoder that always raises. Use a key unlikely to
    # collide with a real TXT field.
    @register("__test_buggy__")
    def _buggy(_raw):
        raise ValueError("boom")
    try:
        # Harness MUST not raise.
        out = decode_txt({"__test_buggy__": "anything", "model": "Mac16,1"})
        # Other decoders still produce output.
        assert any(label == "model" for label, _ in out)
    finally:
        # Clean up the global registry so other tests are not affected.
        from diting.mdns_txt_decoders import _REGISTRY
        _REGISTRY.pop("__test_buggy__", None)
