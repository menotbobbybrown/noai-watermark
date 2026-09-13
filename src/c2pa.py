"""C2PA container dispatch preserving the legacy PNG framed-byte API."""

from pathlib import Path

import c2pa_png
from c2pa_summary import parse_c2pa_payload
from image_formats import detect_format
from riff import parse_webp


def _format(path: Path) -> str | None:
    # Preserve the legacy missing-file result; recognized malformed WebP raises.
    try:
        return detect_format(path)
    except FileNotFoundError:
        return None
    except ValueError:
        with Path(path).open("rb") as stream:
            if stream.read(4) == b"RIFF":
                raise
        return None


def extract_c2pa_payloads(image_path: Path) -> list[bytes]:
    fmt = _format(image_path)
    if fmt == "WEBP":
        return [c.payload for c in parse_webp(Path(image_path).read_bytes()) if c.fourcc == b"C2PA"]
    if fmt == "PNG":
        from png_chunks import credential_payloads
        return credential_payloads(Path(image_path).read_bytes())
    return []


def has_c2pa_metadata(image_path: Path) -> bool:
    if _format(image_path) == "WEBP":
        return bool(extract_c2pa_payloads(image_path))
    return c2pa_png.has_c2pa_metadata(image_path)


def extract_c2pa_info(image_path: Path) -> dict:
    if _format(image_path) != "WEBP":
        return c2pa_png.extract_c2pa_info(image_path)
    payloads = extract_c2pa_payloads(image_path)
    if not payloads:
        return {}
    info = {"has_c2pa": True, "type": "C2PA (Coalition for Content Provenance and Authenticity)",
            "summary_method": "heuristic byte signatures", "signature_validated": False,
            "chunk_count": len(payloads)}
    parse_c2pa_payload(b"\0".join(payloads), info)
    return info


def extract_c2pa_chunk(image_path: Path) -> bytes | None:
    """Return first framed credential: PNG header/payload/CRC or WebP header/payload/pad."""
    if _format(image_path) == "WEBP":
        for chunk in parse_webp(Path(image_path).read_bytes()):
            if chunk.fourcc == b"C2PA":
                return chunk.to_bytes()
        return None
    return c2pa_png.extract_c2pa_chunk(image_path)


def inject_c2pa_chunk(target_path: Path, output_path: Path, c2pa_chunk: bytes) -> None:
    if _format(target_path) == "WEBP" or Path(output_path).suffix.lower() == ".webp":
        raise ValueError("WebP metadata cloning and injection are not supported")
    c2pa_png.inject_c2pa_chunk(target_path, output_path, c2pa_chunk)
