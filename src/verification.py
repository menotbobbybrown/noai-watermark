"""Explicit image verification with incomplete inspection represented separately."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path

from image_formats import inspect_image
from png_chunks import credential_payloads
from riff import parse_webp


@dataclass
class VerificationResult:
    format_valid: bool = False
    dimensions_valid: bool | None = None
    ai_metadata_present: bool | None = None
    c2pa_present: bool | None = None
    pixel_regeneration_applied: bool = False
    pixel_watermark_detector: str | None = None
    pixel_watermark_present: bool | None = None
    inspection_complete: bool = False
    inspection_errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def verify_image(
    path: Path,
    expected_size: tuple[int, int] | None = None,
    *,
    pixel_regeneration_applied: bool = False,
) -> VerificationResult:
    """Inspect output bytes; the caller supplies whether it performed regeneration.

    No pixel detector runs here. Inspection failures remain explicit and cannot
    produce a complete absence verdict. Expected size means encoded canvas size.
    """
    result = VerificationResult(pixel_regeneration_applied=pixel_regeneration_applied)
    try:
        info = inspect_image(path)
        result.format_valid = True
        if expected_size is not None:
            result.dimensions_valid = info.size == expected_size
        if info.format == "WEBP":
            chunks = parse_webp(Path(path).read_bytes())
            result.c2pa_present = any(c.fourcc == b"C2PA" for c in chunks)
            from webp_metadata import inspect_metadata
            result.ai_metadata_present = bool(inspect_metadata(chunks))
        elif info.format == "PNG":
            result.c2pa_present = bool(credential_payloads(Path(path).read_bytes()))
            from extractor import extract_ai_metadata
            from PIL import Image
            result.ai_metadata_present = result.c2pa_present or bool(extract_ai_metadata(path))
            with Image.open(path) as image:
                if "exif" in image.info or any("xmp" in key.lower() for key in image.info):
                    result.inspection_errors.append("PNG EXIF/XMP field inspection is not implemented")
                    if not result.ai_metadata_present:
                        result.ai_metadata_present = None
        else:
            result.inspection_errors.append("JPEG APP11 C2PA and EXIF/XMP field inspection is not implemented")
            from extractor import has_ai_metadata
            if has_ai_metadata(path):
                result.ai_metadata_present = True
        result.inspection_complete = not result.inspection_errors
    except Exception as error:
        result.inspection_errors.append(str(error))
    return result
