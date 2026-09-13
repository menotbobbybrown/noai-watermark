"""WebP metadata inspection and byte-preserving cleanup orchestration."""

from __future__ import annotations

from pathlib import Path

from riff import Chunk, parse_webp, rewrite_metadata
from webp_exif import filter_exif
from webp_xmp import filter_xmp

FILTERS = {b"EXIF": filter_exif, b"XMP ": filter_xmp}


def inspect_metadata(chunks: tuple[Chunk, ...]) -> dict:
    found = {}
    for index, chunk in enumerate(chunks):
        if chunk.fourcc == b"C2PA":
            found[f"C2PA:{index}"] = chunk.payload
        elif chunk.fourcc in FILTERS:
            _, removed = FILTERS[chunk.fourcc](chunk.payload)
            if removed:
                found[chunk.fourcc.decode().strip()] = removed
    return found


def clean_bytes(data: bytes, keep_standard: bool = True) -> bytes:
    chunks = parse_webp(data)
    replacements: dict[bytes, bytes | None] = {b"C2PA": None}
    if keep_standard:
        for chunk in chunks:
            if chunk.fourcc in FILTERS:
                payload, removed = FILTERS[chunk.fourcc](chunk.payload)
                if removed:
                    replacements[chunk.fourcc] = payload
    else:
        replacements.update({b"EXIF": None, b"XMP ": None, b"ICCP": None})
    return rewrite_metadata(chunks, replacements)


def clean_webp(source: Path, output: Path, keep_standard: bool = True) -> Path:
    from image_formats import validate_operation
    from image_output import atomic_output
    from verification import verify_image

    info = validate_operation(source, "clean", output)
    data = clean_bytes(source.read_bytes(), keep_standard)
    with atomic_output(output) as temporary:
        temporary.write_bytes(data)
        result = verify_image(temporary, info.size)
        if not result.inspection_complete or result.ai_metadata_present or result.c2pa_present or not result.dimensions_valid:
            raise ValueError(f"WebP metadata cleanup verification failed: {result.to_dict()}")
    return output
