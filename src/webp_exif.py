"""EXIF text filtering with retained-tag verification and unknown-tag protection."""

from __future__ import annotations

import copy
import struct

import piexif

from metadata_policy import is_ai_text

TEXT_TAGS = {"0th": {270, 305, 40091, 40092, 40093, 40094, 40095}, "Exif": {37510}}
POINTER_TAGS = {34665, 34853, 40965, 513, 514}


def _validate_tiff(payload: bytes) -> list[int]:
    """Check IFD bounds and unknown tags before a potentially lossy serialization."""
    data = payload[6:] if payload.startswith(b"Exif\0\0") else payload
    if len(data) < 8 or data[:2] not in (b"II", b"MM"):
        raise ValueError("Invalid WebP EXIF TIFF header")
    order = "<" if data[:2] == b"II" else ">"
    if struct.unpack_from(order + "H", data, 2)[0] != 42:
        raise ValueError("Invalid WebP EXIF TIFF marker")
    sizes = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2, 9: 4, 10: 8, 11: 4, 12: 8}
    seen = set()
    unknown = []

    def walk(offset: int, name: str) -> None:
        if not offset:
            return
        if offset in seen or offset < 8 or offset + 2 > len(data):
            raise ValueError("Invalid or cyclic EXIF IFD offset")
        seen.add(offset)
        count = struct.unpack_from(order + "H", data, offset)[0]
        end = offset + 2 + count * 12
        if end + (4 if name in ("0th", "1st") else 0) > len(data):
            raise ValueError("Truncated EXIF IFD")
        tags = set()
        for pos in range(offset + 2, end, 12):
            tag, kind, length, value = struct.unpack_from(order + "HHII", data, pos)
            if tag in tags or kind not in sizes:
                raise ValueError("Duplicate EXIF tag or unsupported TIFF type")
            tags.add(tag)
            size = sizes[kind] * length
            if size > 4 and (value < 8 or value + size > len(data)):
                raise ValueError("EXIF value exceeds TIFF bounds")
            if tag not in piexif.TAGS[name]:
                unknown.append(tag)
            if tag in (34665, 34853, 40965):
                if kind != 4 or length != 1:
                    raise ValueError("Invalid EXIF IFD pointer")
                walk(value, {34665: "Exif", 34853: "GPS", 40965: "Interop"}[tag])
        next_ifd = struct.unpack_from(order + "I", data, end)[0] if name in ("0th", "1st") else 0
        if next_ifd:
            if name != "0th":
                raise ValueError("Unsupported EXIF IFD chain")
            walk(next_ifd, "1st")

    walk(struct.unpack_from(order + "I", data, 4)[0], "0th")
    return unknown


def _text(tag: int, value, little_endian: bool) -> str:
    raw = bytes(value) if not isinstance(value, str) else value.encode()
    if 40091 <= tag <= 40095:
        return raw.decode("utf-16-le").rstrip("\0")
    if tag == 37510:
        prefix, raw = raw[:8], raw[8:]
        if prefix == b"UNICODE\0":
            codec = "utf-16" if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else ("utf-16-le" if little_endian else "utf-16-be")
            return raw.decode(codec).rstrip("\0")
        if prefix == b"JIS\0\0\0\0\0":
            return raw.decode("shift_jis").rstrip("\0")
        if prefix not in (b"ASCII\0\0\0", b"\0" * 8):
            raise ValueError("Unsupported EXIF UserComment encoding")
    return raw.decode("utf-8").rstrip("\0")


def _logical(metadata: dict) -> dict:
    result = copy.deepcopy(metadata)
    for value in result.values():
        if isinstance(value, dict):
            for tag in POINTER_TAGS:
                value.pop(tag, None)
    return result


def filter_exif(payload: bytes) -> tuple[bytes, dict[str, str]]:
    try:
        unknown = _validate_tiff(payload)
        raw = payload if payload.startswith(b"Exif\0\0") else b"Exif\0\0" + payload
        metadata = piexif.load(raw)
        removed = {}
        for ifd, tags in TEXT_TAGS.items():
            for tag in tags & metadata[ifd].keys():
                text = _text(tag, metadata[ifd][tag], raw[6:8] == b"II")
                if is_ai_text(text):
                    removed[f"{ifd}:{tag}"] = text
                    del metadata[ifd][tag]
        if not removed:
            return payload, removed
        if unknown:
            raise ValueError("Cannot safely rewrite EXIF containing unknown tags")
        encoded = piexif.dump(metadata)
        if _logical(piexif.load(encoded)) != _logical(metadata):
            raise ValueError("EXIF rewrite changed retained tag values")
        return (encoded if payload.startswith(b"Exif\0\0") else encoded[6:]), removed
    except Exception as error:
        raise ValueError(f"Invalid or unsupported WebP EXIF: {error}") from error
