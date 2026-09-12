import pytest

from tests.webp_fixtures import credentialed, webp
from verification import verify_image


@pytest.mark.parametrize("data", [b"", b"not an image", b"RIFF\x04\0\0\0WEBP", webp() + b"trailing"])
def test_bad_input_never_clean(tmp_path, data):
    source = tmp_path / "bad.webp"
    source.write_bytes(data)
    result = verify_image(source)
    assert not result.inspection_complete
    assert result.ai_metadata_present is None
    assert result.inspection_errors


def test_verification_dimensions_and_nullable_detector(tmp_path):
    source = tmp_path / "source.webp"
    source.write_bytes(credentialed())
    result = verify_image(source, (18, 19), pixel_regeneration_applied=True)
    assert result.format_valid and result.inspection_complete
    assert result.dimensions_valid is False
    assert result.ai_metadata_present and result.c2pa_present
    assert result.pixel_regeneration_applied
    assert result.pixel_watermark_detector is result.pixel_watermark_present is None
    assert verify_image(source).dimensions_valid is None


def test_jpeg_coverage_explicit(sample_jpg):
    result = verify_image(sample_jpg)
    assert result.format_valid
    assert not result.inspection_complete
    assert result.c2pa_present is None


def test_png_crc_checked(sample_png):
    assert verify_image(sample_png).inspection_complete
    data = bytearray(sample_png.read_bytes())
    data[-1] ^= 1
    sample_png.write_bytes(data)
    assert not verify_image(sample_png).inspection_complete
