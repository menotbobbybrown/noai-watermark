"""Low-level utility helpers used across the metadata pipeline.

Kept deliberately small — only format detection lives here so that
higher-level modules can import without circular dependencies.
"""

from __future__ import annotations

from pathlib import Path

from constants import SUPPORTED_FORMATS


def is_supported_format(file_path: Path) -> bool:
    """
    Check if the file format is supported.

    Args:
        file_path: Path to the image file.

    Returns:
        True if the format is supported, False otherwise.
    """
    return file_path.suffix.lower() in SUPPORTED_FORMATS


def get_image_format(file_path: Path) -> str:
    """
    Get the image format from file path.

    Args:
        file_path: Path to the image file.

    Returns:
        Format string (PNG, JPEG, etc.).
    """
    formats = {".png": "PNG", ".jpg": "JPEG", ".jpeg": "JPEG", ".webp": "WEBP"}
    try:
        return formats[Path(file_path).suffix.lower()]
    except KeyError:
        raise ValueError(f"Unsupported output extension: {Path(file_path).suffix or '(none)'}") from None
