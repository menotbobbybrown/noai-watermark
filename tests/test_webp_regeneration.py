from types import SimpleNamespace
from unittest.mock import Mock

from PIL import Image
import pytest

from image_formats import ANIMATED_WEBP_ERROR, inspect_image
from image_output import pad_rgb
from riff import parse_webp
from tests.webp_fixtures import credentialed, webp
from verification import verify_image


@pytest.fixture
def remover(monkeypatch):
    import watermark_remover as module
    monkeypatch.setattr(module, "is_watermark_removal_available", lambda: True)
    instance = module.WatermarkRemover(device="cpu", torch_dtype="float32")
    monkeypatch.setattr(instance, "_run_img2img", lambda image, *args: image.copy())
    monkeypatch.setattr(instance, "_run_ctrlregen", lambda image, *args: image.copy())
    return instance


@pytest.mark.parametrize("profile", ["default", "ctrlregen"])
@pytest.mark.parametrize("size", [(1, 1), (7, 5), (17, 19), (64, 64), (513, 519)])
@pytest.mark.parametrize("quality", [None, 0, 80, 100])
def test_regeneration_preserves_canvas_and_alpha(tmp_path, remover, size, profile, quality):
    source, output = tmp_path / "source.webp", tmp_path / "out.webp"
    source.write_bytes(credentialed(alpha=True, size=size))
    original = source.read_bytes()
    with Image.open(source) as image:
        expected_alpha = image.getchannel("A").tobytes()
        expected_pixels = image.convert("RGBA").tobytes()
    remover.model_profile = profile
    assert remover.remove_watermark(source, output, webp_quality=quality) == output
    assert source.read_bytes() == original
    info = inspect_image(output)
    assert info.format == "WEBP" and info.size == size and info.frames == 1
    with Image.open(output) as image:
        assert image.convert("RGBA").getchannel("A").tobytes() == expected_alpha
        if quality is None:
            assert image.convert("RGBA").tobytes() == expected_pixels
    kinds = {c.fourcc for c in parse_webp(output.read_bytes())}
    assert (b"VP8L" if quality is None else b"VP8 ") in kinds
    result = verify_image(output, size, pixel_regeneration_applied=True)
    assert result.inspection_complete and not result.ai_metadata_present
    assert result.pixel_watermark_present is None


def test_padding_keeps_every_original_pixel():
    image = Image.new("RGB", (3, 5), "red")
    image.putpixel((2, 4), (1, 2, 3))
    padded = pad_rgb(image)
    assert padded.size == (8, 8)
    assert padded.crop((0, 0, 3, 5)).tobytes() == image.tobytes()
    assert padded.getpixel((7, 7)) == (1, 2, 3)


def test_animated_preflight_before_constructor_and_output(tmp_path, monkeypatch):
    import watermark_remover
    source, output = tmp_path / "animated.webp", tmp_path / "out.webp"
    source.write_bytes(webp(animated=True))
    original = source.read_bytes()
    constructor = Mock(side_effect=AssertionError("Model construction must not happen"))
    monkeypatch.setattr(watermark_remover, "WatermarkRemover", constructor)
    with pytest.raises(ValueError, match=ANIMATED_WEBP_ERROR):
        watermark_remover.remove_watermark(source, output)
    assert not output.exists() and source.read_bytes() == original
    constructor.assert_not_called()


@pytest.mark.parametrize("failure", ["inference", "encoding", "cleanup", "verification", "dimensions"])
def test_failures_preserve_source_and_destination(tmp_path, remover, monkeypatch, failure):
    import image_output
    import verification
    import webp_metadata
    source, output = tmp_path / "source.webp", tmp_path / "out.webp"
    source.write_bytes(webp(alpha=True))
    original = source.read_bytes()
    output.write_bytes(b"existing destination")
    if failure == "inference":
        monkeypatch.setattr(remover, "_run_img2img", Mock(side_effect=RuntimeError("inference failed")))
    elif failure == "encoding":
        monkeypatch.setattr(Image.Image, "save", Mock(side_effect=OSError("encoding failed")))
    elif failure == "cleanup":
        real_clean = webp_metadata.clean_bytes
        calls = []
        def fail_output(data, *args):
            calls.append(1)
            if len(calls) % 2 == 0:
                raise ValueError("cleanup failed")
            return real_clean(data, *args)
        monkeypatch.setattr(webp_metadata, "clean_bytes", fail_output)
    elif failure == "dimensions":
        monkeypatch.setattr(remover, "_run_img2img", lambda image, *args: Image.new("RGB", (8, 8)))
    else:
        monkeypatch.setattr(verification, "verify_image", lambda *args, **kwargs: verification.VerificationResult(inspection_errors=["verification failed"]))
    for destination in (output, source):
        with pytest.raises((OSError, ValueError, RuntimeError)):
            remover.remove_watermark(source, destination)
    assert source.read_bytes() == original
    assert output.read_bytes() == b"existing destination"
    assert not list(tmp_path.glob(".*.webp"))


def test_batch_reports_only_successes(tmp_path, remover):
    inputs, outputs = tmp_path / "inputs", tmp_path / "outputs"
    inputs.mkdir()
    (inputs / "static.webp").write_bytes(webp())
    (inputs / "animated.webp").write_bytes(webp(animated=True))
    paths = remover.remove_watermark_batch(inputs, outputs)
    assert paths == [outputs / "static.webp"]
    assert not (outputs / "animated.webp").exists()


def test_png_to_webp_uses_webp_encoding(tmp_path, remover, sample_png_rgba):
    output = tmp_path / "output.webp"
    remover.remove_watermark(sample_png_rgba, output)
    assert inspect_image(output).format == "WEBP"


def test_zero_strength_is_not_replaced(tmp_path, remover, monkeypatch):
    source = tmp_path / "source.webp"
    source.write_bytes(webp())
    inference = Mock(side_effect=lambda image, *args: image.copy())
    monkeypatch.setattr(remover, "_run_img2img", inference)
    remover.remove_watermark(source, strength=0)
    assert inference.call_args.args[1] == 0
