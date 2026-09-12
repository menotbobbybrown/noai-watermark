import pytest

from image_formats import ANIMATED_WEBP_ERROR, inspect_image, validate_operation, validate_webp_quality
from tests.webp_fixtures import credentialed, webp


def test_input_signature_wins_over_name(tmp_path):
    source = tmp_path / "misleading.png"
    source.write_bytes(credentialed())
    assert inspect_image(source).format == "WEBP"
    with pytest.raises(ValueError, match="requires WebP"):
        validate_operation(source, "clean", source)


def test_animation_supported_only_for_metadata(tmp_path):
    source = tmp_path / "animated.webp"
    source.write_bytes(webp(animated=True))
    assert validate_operation(source, "clean", source).frames == 2
    with pytest.raises(ValueError, match=ANIMATED_WEBP_ERROR):
        validate_operation(source, "regenerate", source)
    with pytest.raises(ValueError, match="cloning"):
        validate_operation(source, "clone", source)


def test_alpha_jpeg_conversion_rejected(tmp_path):
    source = tmp_path / "alpha.webp"
    source.write_bytes(webp(alpha=True))
    with pytest.raises(ValueError, match="alpha"):
        validate_operation(source, "regenerate", tmp_path / "output.jpg")


@pytest.mark.parametrize("value", [-1, 101, True, 4.5])
def test_invalid_quality(tmp_path, value):
    with pytest.raises(ValueError, match="integer"):
        validate_webp_quality(tmp_path / "out.webp", value)


def test_quality_requires_webp(tmp_path):
    with pytest.raises(ValueError, match=".webp output"):
        validate_webp_quality(tmp_path / "out.png", 80)
