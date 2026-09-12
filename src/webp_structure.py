"""Validate WebP image and animation structure independently of metadata policy."""

from __future__ import annotations

from riff import Chunk, unpack_chunks


def uint24(data: bytes) -> int:
    return int.from_bytes(data, "little")


def bitstream_size(chunk: Chunk) -> tuple[int, int, bool]:
    data = chunk.payload
    if chunk.fourcc == b"VP8L":
        if len(data) < 5 or data[0] != 0x2F or data[4] & 0xE0:
            raise ValueError("Invalid VP8L header")
        bits = int.from_bytes(data[1:5], "little")
        return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1, bool(bits & (1 << 28))
    if len(data) < 10 or data[0] & 1 or data[3:6] != b"\x9d\x01\x2a":
        raise ValueError("Invalid VP8 key frame header")
    w = int.from_bytes(data[6:8], "little") & 0x3FFF
    h = int.from_bytes(data[8:10], "little") & 0x3FFF
    if not w or not h:
        raise ValueError("Invalid VP8 dimensions")
    return w, h, False


def validate_frame(chunks: tuple[Chunk, ...]) -> tuple[int, int, bool]:
    images = [c for c in chunks if c.fourcc in (b"VP8 ", b"VP8L")]
    alpha = [c for c in chunks if c.fourcc == b"ALPH"]
    if len(images) != 1 or len(alpha) > 1:
        raise ValueError("WebP frame must contain exactly one image bitstream")
    w, h, has_alpha = bitstream_size(images[0])
    if alpha:
        if images[0].fourcc != b"VP8 " or chunks.index(alpha[0]) > chunks.index(images[0]):
            raise ValueError("Invalid ALPH chunk order or bitstream")
        if not alpha[0].payload or alpha[0].payload[0] & 0xC0 or alpha[0].payload[0] & 3 > 1:
            raise ValueError("Invalid ALPH header")
    return w, h, has_alpha or bool(alpha)


def validate_structure(chunks: tuple[Chunk, ...]) -> None:
    kinds = [c.fourcc for c in chunks]
    for kind in (b"VP8X", b"ICCP", b"EXIF", b"XMP ", b"ANIM"):
        if kinds.count(kind) > 1:
            raise ValueError(f"Duplicate WebP {kind.decode().strip()} chunk")
    extended = b"VP8X" in kinds
    if not extended:
        if any(k in kinds for k in (b"ICCP", b"EXIF", b"XMP ", b"ANIM", b"ANMF", b"ALPH")):
            raise ValueError("WebP features require a VP8X chunk")
        validate_frame(chunks)
        return
    if kinds[0] != b"VP8X":
        raise ValueError("VP8X must be the first WebP chunk")
    header = chunks[0].payload
    if len(header) != 10 or header[0] & 0xC1 or header[1:4] != b"\0\0\0":
        raise ValueError("Invalid VP8X header or reserved bits")
    flags = header[0]
    canvas = uint24(header[4:7]) + 1, uint24(header[7:10]) + 1
    if canvas[0] * canvas[1] > 0xFFFFFFFF:
        raise ValueError("Invalid WebP canvas area")
    for kind, flag in ((b"ICCP", 0x20), (b"EXIF", 8), (b"XMP ", 4)):
        if bool(flags & flag) != (kind in kinds):
            raise ValueError("WebP metadata feature flag mismatch")
    reconstruction = [k for k in kinds if k in (b"ICCP", b"ANIM", b"ANMF", b"ALPH", b"VP8 ", b"VP8L")]
    if b"ICCP" in reconstruction and reconstruction[0] != b"ICCP":
        raise ValueError("ICCP must precede image and animation data")
    if flags & 2:
        if kinds.count(b"ANIM") != 1 or b"ANMF" not in kinds or any(k in kinds for k in (b"VP8 ", b"VP8L", b"ALPH")):
            raise ValueError("Invalid WebP animation structure")
        anim_index = kinds.index(b"ANIM")
        if len(chunks[anim_index].payload) != 6 or anim_index > kinds.index(b"ANMF"):
            raise ValueError("Invalid ANIM header or order")
        alpha = False
        for chunk in chunks:
            if chunk.fourcc != b"ANMF":
                continue
            data = chunk.payload
            if len(data) < 16 or data[15] & 0xFC:
                raise ValueError("Invalid ANMF header")
            x, y = uint24(data[:3]) * 2, uint24(data[3:6]) * 2
            w, h = uint24(data[6:9]) + 1, uint24(data[9:12]) + 1
            if x + w > canvas[0] or y + h > canvas[1]:
                raise ValueError("ANMF frame exceeds canvas")
            inner = unpack_chunks(data[16:])
            if any(c.fourcc in (b"VP8X", b"ANIM", b"ANMF", b"ICCP", b"EXIF", b"XMP ", b"C2PA") for c in inner):
                raise ValueError("Invalid chunk inside ANMF frame")
            fw, fh, fa = validate_frame(inner)
            if (fw, fh) != (w, h):
                raise ValueError("ANMF bitstream dimensions mismatch")
            alpha |= fa
    else:
        if b"ANIM" in kinds or b"ANMF" in kinds:
            raise ValueError("Animation chunks require the VP8X animation flag")
        w, h, alpha = validate_frame(chunks)
        if (w, h) != canvas:
            raise ValueError("VP8X canvas and image dimensions mismatch")
    if alpha and not flags & 0x10:
        raise ValueError("Missing VP8X alpha flag")
