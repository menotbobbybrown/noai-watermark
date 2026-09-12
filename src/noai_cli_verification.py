"""CLI reporting for metadata inspection and regeneration outcomes."""

from pathlib import Path
import sys

from verification import verify_image


def report_inspection(path: Path, *, regenerated: bool = False, cleaned: bool = False) -> int:
    result = verify_image(path, pixel_regeneration_applied=regenerated)
    if regenerated:
        print(f"Pixel regeneration applied: {path}")
        print("Invisible pixel watermark: not independently verified (no detector ran).")
    if not result.inspection_complete:
        print(f"Metadata inspection incomplete: {'; '.join(result.inspection_errors)}", file=sys.stderr)
        return 2
    if result.ai_metadata_present or result.c2pa_present:
        print(f"Recognized AI metadata or C2PA credentials are present: {path}")
        return 1 if cleaned else 0
    if cleaned:
        print(f"AI metadata removed and verified absent under the supported field policy: {path}")
        return 0
    print(f"No recognized AI metadata or C2PA credentials found: {path}")
    return 1


def check_ai(path: Path) -> int:
    return report_inspection(path)
