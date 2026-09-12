"""Transactional image output and WebP encoding, independent of model inference."""

from __future__ import annotations

import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from PIL import Image


@contextmanager
def atomic_output(destination: Path) -> Iterator[Path]:
    """Publish a completed sibling temporary file; preserve targets on failure."""
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f".{destination.stem}-", suffix=destination.suffix, dir=destination.parent)
    os.close(descriptor)
    temporary = Path(name)
    try:
        yield temporary
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def pad_rgb(image: Image.Image) -> Image.Image:
    """Extend right/bottom edges to multiples of eight without resampling input."""
    w, h = image.size
    width, height = max(8, (w + 7) // 8 * 8), max(8, (h + 7) // 8 * 8)
    if (width, height) == image.size:
        return image
    padded = Image.new("RGB", (width, height))
    padded.paste(image, (0, 0))
    if width > w:
        padded.paste(image.crop((w - 1, 0, w, h)).resize((width - w, h), Image.Resampling.NEAREST), (w, 0))
    if height > h:
        padded.paste(padded.crop((0, h - 1, width, h)).resize((width, height - h), Image.Resampling.NEAREST), (0, h))
    return padded


def retained_webp_metadata(source: Path) -> dict[str, bytes]:
    from riff import parse_webp
    from webp_metadata import clean_bytes
    mapping = {b"EXIF": "exif", b"XMP ": "xmp", b"ICCP": "icc_profile"}
    return {mapping[c.fourcc]: c.payload for c in parse_webp(clean_bytes(source.read_bytes())) if c.fourcc in mapping}


def save_regenerated_image(
    image: Image.Image,
    destination: Path,
    expected_size: tuple[int, int],
    *,
    alpha: Image.Image | None = None,
    webp_quality: int | None = None,
    metadata: dict[str, bytes] | None = None,
) -> Path:
    from image_formats import inspect_image, validate_webp_quality
    from utils import get_image_format
    from verification import verify_image
    from webp_metadata import clean_bytes

    validate_webp_quality(destination, webp_quality)
    if image.size != expected_size:
        raise ValueError("Regenerated image dimensions do not match the source")
    image = image.convert("RGB")
    image.info.clear()
    if alpha is not None:
        if alpha.size != expected_size:
            raise ValueError("Alpha dimensions do not match the source")
        image.putalpha(alpha)
    fmt = get_image_format(destination)
    if alpha is not None and fmt == "JPEG":
        raise ValueError("Cannot preserve alpha in JPEG output")
    options = dict(metadata or {})
    if fmt == "WEBP":
        options.update(lossless=webp_quality is None, quality=100 if webp_quality is None else webp_quality, exact=True)
    elif fmt == "PNG":
        # Pillow requires PngInfo for XMP; do not drop retained packets on conversion.
        from PIL.PngImagePlugin import PngInfo
        if "xmp" in options:
            pnginfo = PngInfo()
            pnginfo.add_itxt("XML:com.adobe.xmp", options.pop("xmp").decode("utf-8"))
            options["pnginfo"] = pnginfo
    with atomic_output(destination) as temporary:
        image.save(temporary, format=fmt, **options)
        if fmt == "WEBP":
            temporary.write_bytes(clean_bytes(temporary.read_bytes()))
        info = inspect_image(temporary)
        if info.format != fmt or info.size != expected_size or info.frames != 1 or info.animated:
            raise ValueError("Regenerated output format, dimensions, or frame count is invalid")
        if alpha is not None:
            with Image.open(temporary) as saved:
                if saved.convert("RGBA").getchannel("A").tobytes() != alpha.tobytes():
                    raise ValueError("Regenerated output did not preserve alpha samples")
        verification = verify_image(temporary, expected_size, pixel_regeneration_applied=True)
        if verification.ai_metadata_present or verification.c2pa_present:
            raise ValueError("Regenerated output still contains recognized AI metadata")
        if fmt == "WEBP" and not verification.inspection_complete:
            raise ValueError(f"Regenerated output inspection failed: {verification.inspection_errors}")
    return destination
