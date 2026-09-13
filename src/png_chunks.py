"""Strict PNG credential inspection for verification; legacy wrappers stay compatible."""

import struct
import zlib

from constants import PNG_SIGNATURE


def credential_payloads(data: bytes) -> list[bytes]:
    if not data.startswith(PNG_SIGNATURE):
        raise ValueError("Invalid PNG signature")
    offset = 8
    result = []
    first = True
    seen_image = False
    while offset < len(data):
        if len(data) - offset < 12:
            raise ValueError("Truncated PNG chunk")
        size, kind = struct.unpack_from(">I4s", data, offset)
        end = offset + 12 + size
        if end > len(data):
            raise ValueError("Truncated PNG payload")
        payload = data[offset + 8:end - 4]
        crc = struct.unpack_from(">I", data, end - 4)[0]
        if zlib.crc32(kind + payload) & 0xFFFFFFFF != crc:
            raise ValueError("Invalid PNG chunk CRC")
        if first and (kind != b"IHDR" or size != 13):
            raise ValueError("Missing PNG IHDR")
        first = False
        if kind == b"caBX":
            result.append(payload)
        if kind == b"IDAT":
            seen_image = True
        if kind == b"IEND":
            if size or end != len(data) or not seen_image:
                raise ValueError("Invalid PNG termination")
            return result
        offset = end
    raise ValueError("Missing PNG IEND")
