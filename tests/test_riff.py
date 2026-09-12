import struct

import pytest

from riff import encode_webp, parse_webp, rewrite_metadata
from tests.webp_fixtures import chunk, credentialed, riff, webp


@pytest.mark.parametrize("options", [{}, {"lossless": False}, {"alpha": True}, {"animated": True}, {"animated": True, "alpha": True}])
def test_roundtrip_preserves_every_byte(options):
    data = credentialed(**options)
    assert encode_webp(parse_webp(data)) == data


def test_remove_every_credential_preserve_unknown_and_frames():
    data = credentialed(animated=True)
    data = riff(data[12:] + chunk(b"C2PA", b"") + chunk(b"zzzz", b"odd"))
    chunks = parse_webp(data)
    cleaned = parse_webp(rewrite_metadata(chunks, {b"C2PA": None}))
    assert [c.to_bytes() for c in cleaned] == [c.to_bytes() for c in chunks if c.fourcc != b"C2PA"]


@pytest.mark.parametrize("mutate", [
    lambda b: b[:4], lambda b: b[:8] + b"WAVE" + b[12:],
    lambda b: b + b"trailing", lambda b: b[:4] + struct.pack("<I", 4) + b[8:],
    lambda b: riff(b[12:] + b"head"),
    lambda b: riff(b[12:] + b"C2PA" + struct.pack("<I", 100)),
    lambda b: riff(b[12:] + b"C2PA\x01\0\0\0X\x01"),
    lambda b: riff(b[12:] + b"C2PA\x01\0\0\0X"),
    lambda b: riff(chunk(b"VP8L", b"broken")),
    lambda b: riff(chunk(b"C2PA", b"empty image")),
])
def test_malformed_rejected(mutate):
    with pytest.raises(ValueError):
        parse_webp(mutate(webp()))


def test_duplicate_metadata_and_bad_flags():
    data = webp(xmp=b"<x/>")
    with pytest.raises(ValueError, match="Duplicate"):
        parse_webp(riff(data[12:] + chunk(b"XMP ", b"<y/>")))
    body = bytearray(data[12:])
    body[8] &= ~4
    with pytest.raises(ValueError, match="flag mismatch"):
        parse_webp(riff(bytes(body)))


def test_metadata_removal_only_changes_flags():
    data = webp(alpha=True, xmp=b"<x/>", icc_profile=b"test profile")
    original = parse_webp(data)
    result = parse_webp(rewrite_metadata(original, {b"XMP ": None, b"ICCP": None}))
    assert result[0].payload[0] == original[0].payload[0] & ~0x24
    assert result[0].payload[1:] == original[0].payload[1:]
    assert result[1:] == tuple(c for c in original[1:] if c.fourcc not in (b"XMP ", b"ICCP"))
