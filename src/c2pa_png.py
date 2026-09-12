"""C2PA (Coalition for Content Provenance and Authenticity) metadata handling.

C2PA metadata is embedded in PNG files as a JUMBF container chunk
(``caBX``).  This module can detect, extract, and re-inject those
chunks.  Supported issuers:

- Google Imagen
- Adobe Firefly
- Microsoft Designer
- OpenAI (ChatGPT, GPT-4o, Sora, DALL-E)
- Truepic (signing authority)

The parser uses byte-level scanning — it does not validate JUMBF/CBOR
structure but reliably identifies known signatures, issuers, tools,
and actions.
"""

from __future__ import annotations

import struct
from pathlib import Path
from typing import Any

from c2pa_summary import parse_c2pa_payload as _parse_c2pa_chunk

from constants import (
    C2PA_ACTIONS,
    C2PA_AI_TOOLS,
    C2PA_CHUNK_TYPE,
    C2PA_ISSUERS,
    C2PA_SIGNATURES,
    PNG_SIGNATURE,
)


def has_c2pa_metadata(image_path: Path) -> bool:
    """
    Check if an image contains C2PA metadata.

    Args:
        image_path: Path to the image file.

    Returns:
        True if C2PA metadata is detected, False otherwise.
    """
    image_path = Path(image_path)

    try:
        with open(image_path, "rb") as f:
            signature = f.read(8)
            if signature != PNG_SIGNATURE:
                return False

            while True:
                chunk_header = f.read(8)
                if len(chunk_header) < 8:
                    break

                length = struct.unpack(">I", chunk_header[:4])[0]
                chunk_type = chunk_header[4:8]

                if chunk_type == C2PA_CHUNK_TYPE:
                    chunk_data = f.read(length)
                    # Check for any C2PA signature
                    for sig in C2PA_SIGNATURES:
                        if sig in chunk_data:
                            return True
                    # Also check if chunk_data itself contains C2PA-like patterns
                    if b"jumb" in chunk_data.lower() or b"c2pa" in chunk_data.lower():
                        return True
                    f.read(4)
                else:
                    f.read(length + 4)

                if chunk_type == b"IEND":
                    break
    except Exception:
        pass

    return False


def extract_c2pa_info(image_path: Path) -> dict[str, Any]:
    """
    Extract basic C2PA metadata information from an image.

    Args:
        image_path: Path to the image file.

    Returns:
        Dictionary containing C2PA metadata info.
    """
    c2pa_info: dict[str, Any] = {}

    if not has_c2pa_metadata(image_path):
        return c2pa_info

    c2pa_info["has_c2pa"] = True
    c2pa_info["type"] = "C2PA (Coalition for Content Provenance and Authenticity)"

    try:
        with open(image_path, "rb") as f:
            signature = f.read(8)
            if signature != PNG_SIGNATURE:
                return c2pa_info

            while True:
                chunk_header = f.read(8)
                if len(chunk_header) < 8:
                    break

                length = struct.unpack(">I", chunk_header[:4])[0]
                chunk_type = chunk_header[4:8]

                if chunk_type == C2PA_CHUNK_TYPE:
                    chunk_data = f.read(length)
                    _parse_c2pa_chunk(chunk_data, c2pa_info)
                    f.read(4)
                else:
                    f.read(length + 4)

                if chunk_type == b"IEND":
                    break
    except Exception:
        pass

    return c2pa_info



def extract_c2pa_chunk(image_path: Path) -> bytes | None:
    """
    Extract the raw C2PA JUMBF chunk from a PNG file.

    Args:
        image_path: Path to the source PNG file.

    Returns:
        Raw bytes of the C2PA chunk or None.
    """
    try:
        with open(image_path, "rb") as f:
            signature = f.read(8)
            if signature != PNG_SIGNATURE:
                return None

            while True:
                chunk_header = f.read(8)
                if len(chunk_header) < 8:
                    break

                length = struct.unpack(">I", chunk_header[:4])[0]
                chunk_type = chunk_header[4:8]

                if chunk_type == C2PA_CHUNK_TYPE:
                    chunk_data = f.read(length)
                    crc = f.read(4)

                    # Check for any C2PA signature
                    for sig in C2PA_SIGNATURES:
                        if sig in chunk_data:
                            return chunk_header + chunk_data + crc
                    
                    # Also check lowercase variants
                    if b"jumb" in chunk_data.lower() or b"c2pa" in chunk_data.lower():
                        return chunk_header + chunk_data + crc
                else:
                    f.read(length + 4)

                if chunk_type == b"IEND":
                    break
    except Exception:
        pass

    return None


def inject_c2pa_chunk(target_path: Path, output_path: Path, c2pa_chunk: bytes) -> None:
    """
    Inject a C2PA JUMBF chunk into a PNG file.

    Args:
        target_path: Path to the target PNG file.
        output_path: Path where the output file will be saved.
        c2pa_chunk: Raw bytes of the C2PA chunk to inject.

    Raises:
        ValueError: If not PNG files.
    """
    if target_path.suffix.lower() != ".png" or output_path.suffix.lower() != ".png":
        raise ValueError("C2PA chunk injection is only supported for PNG files")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(target_path, "rb") as f_in:
        with open(output_path, "wb") as f_out:
            f_out.write(f_in.read(8))

            c2pa_injected = False
            while True:
                chunk_header = f_in.read(8)
                if len(chunk_header) < 8:
                    break

                length = struct.unpack(">I", chunk_header[:4])[0]
                chunk_type = chunk_header[4:8]
                chunk_data = f_in.read(length)
                crc = f_in.read(4)

                if chunk_type == b"IDAT" and not c2pa_injected:
                    f_out.write(c2pa_chunk)
                    c2pa_injected = True

                if chunk_type == C2PA_CHUNK_TYPE:
                    continue

                f_out.write(chunk_header)
                f_out.write(chunk_data)
                f_out.write(crc)

                if chunk_type == b"IEND":
                    break
