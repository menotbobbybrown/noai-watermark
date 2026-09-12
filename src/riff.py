"""Strict WebP RIFF framing and lossless container rewrites."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class Chunk:
    fourcc: bytes
    payload: bytes

    def to_bytes(self) -> bytes:
        return self.fourcc + struct.pack("<I", len(self.payload)) + self.payload + b"\0" * (len(self.payload) % 2)


def unpack_chunks(data: bytes) -> tuple[Chunk, ...]:
    chunks = []
    offset = 0
    while offset < len(data):
        if len(data) - offset < 8:
            raise ValueError("Truncated RIFF chunk header")
        kind, size = struct.unpack_from("<4sI", data, offset)
        end = offset + 8 + size
        padded_end = end + size % 2
        if padded_end > len(data):
            raise ValueError("Truncated RIFF chunk payload or padding")
        if size % 2 and data[end] != 0:
            raise ValueError("Nonzero RIFF padding")
        chunks.append(Chunk(kind, data[offset + 8:end]))
        offset = padded_end
    return tuple(chunks)


def parse_webp(data: bytes) -> tuple[Chunk, ...]:
    if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        raise ValueError("Invalid RIFF/WEBP header")
    size = struct.unpack_from("<I", data, 4)[0]
    if size != len(data) - 8 or size % 2 or size > 0xFFFFFFF6:
        raise ValueError("Invalid RIFF size or trailing data")
    chunks = unpack_chunks(data[12:])
    from webp_structure import validate_structure
    validate_structure(chunks)
    return chunks


def encode_webp(chunks: Iterable[Chunk]) -> bytes:
    body = b"WEBP" + b"".join(c.to_bytes() for c in chunks)
    if len(body) > 0xFFFFFFF6:
        raise ValueError("WebP container exceeds RIFF size limit")
    return b"RIFF" + struct.pack("<I", len(body)) + body


def rewrite_metadata(chunks: Iterable[Chunk], replacements: dict[bytes, bytes | None]) -> bytes:
    """Replace/remove metadata without altering image, frame, or unknown chunks."""
    result = []
    for chunk in chunks:
        if chunk.fourcc in replacements:
            payload = replacements[chunk.fourcc]
            if payload is None:
                continue
            chunk = Chunk(chunk.fourcc, payload)
        result.append(chunk)
    present = {c.fourcc for c in result}
    for i, chunk in enumerate(result):
        if chunk.fourcc == b"VP8X":
            flags = chunk.payload[0] & ~0x2C
            for kind, flag in ((b"ICCP", 0x20), (b"EXIF", 0x08), (b"XMP ", 0x04)):
                if kind in present:
                    flags |= flag
            result[i] = Chunk(b"VP8X", bytes([flags]) + chunk.payload[1:])
    data = encode_webp(result)
    parse_webp(data)
    return data
