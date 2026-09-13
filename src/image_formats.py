"""Byte-based input inspection and operation-specific image capabilities."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from constants import PNG_SIGNATURE
from riff import parse_webp
from utils import get_image_format

ANIMATED_WEBP_ERROR = "Animated WebP is not supported for pixel regeneration"


@dataclass(frozen=True)
class ImageProperties:
    format: str
    size: tuple[int, int]
    frames: int
    has_alpha: bool
    animated: bool


def detect_format(path: Path) -> str:
    with Path(path).open("rb") as stream:
        header = stream.read(12)
    if header.startswith(PNG_SIGNATURE):
        return "PNG"
    if header.startswith(b"\xff\xd8\xff"):
        return "JPEG"
    if header.startswith(b"RIFF"):
        if len(header) != 12 or header[8:12] != b"WEBP":
            raise ValueError("Invalid RIFF/WEBP header")
        return "WEBP"
    raise ValueError("Unsupported image bytes; expected PNG, JPEG, or WebP")


def inspect_image(path: Path) -> ImageProperties:
    fmt = detect_format(path)
    declared_animation = False
    if fmt == "WEBP":
        chunks = parse_webp(Path(path).read_bytes())
        declared_animation = any(c.fourcc == b"ANIM" for c in chunks)
    elif fmt == "PNG":
        from png_chunks import credential_payloads
        credential_payloads(Path(path).read_bytes())
    with Image.open(path) as image:
        if image.format != fmt:
            raise ValueError("Decoded image format differs from byte signature")
        size = image.size
        frames = getattr(image, "n_frames", 1)
        alpha = "A" in image.getbands() or "transparency" in image.info
        for frame in range(frames):
            image.seek(frame)
            image.load()
        return ImageProperties(fmt, size, frames, alpha, declared_animation or frames > 1)


def validate_operation(path: Path, operation: str, output: Path | None = None) -> ImageProperties:
    if operation not in {"inspect", "clean", "regenerate", "clone", "inject"}:
        raise ValueError(f"Unknown image operation: {operation}")
    info = inspect_image(path)
    if info.format == "WEBP" and operation in {"clone", "inject"}:
        raise ValueError("WebP metadata cloning and injection are not supported")
    if operation == "regenerate" and info.format == "WEBP" and info.animated:
        raise ValueError(ANIMATED_WEBP_ERROR)
    if output is not None:
        fmt = get_image_format(output)
        if operation in {"clone", "inject"} and fmt == "WEBP":
            raise ValueError("WebP metadata cloning and injection are not supported")
        if operation == "clean" and "WEBP" in (info.format, fmt) and info.format != fmt:
            raise ValueError("WebP metadata cleaning requires WebP input and a .webp output")
        if operation == "regenerate" and info.format == "WEBP" and info.has_alpha and fmt == "JPEG":
            raise ValueError("Cannot preserve WebP alpha in JPEG output")
    return info


def validate_webp_quality(output: Path, quality: int | None) -> None:
    if quality is None:
        return
    if type(quality) is not int or not 0 <= quality <= 100:
        raise ValueError("WebP quality must be an integer from 0 through 100")
    if get_image_format(output) != "WEBP":
        raise ValueError("WebP quality requires a .webp output")
