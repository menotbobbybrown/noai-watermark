import sys
from unittest.mock import Mock

import pytest

from tests.webp_fixtures import credentialed, webp


def run_cli(monkeypatch, *arguments):
    from noai_cli import main
    monkeypatch.setattr(sys, "argv", ["noai-watermark", *(str(a) for a in arguments)])
    return main()


def test_check_clean_check(tmp_path, monkeypatch, capsys):
    source, output = tmp_path / "source.webp", tmp_path / "output.webp"
    source.write_bytes(credentialed())
    assert run_cli(monkeypatch, source, "--check-ai") == 0
    assert run_cli(monkeypatch, source, "--remove-ai", "-o", output) == 0
    assert "verified absent" in capsys.readouterr().out
    assert run_cli(monkeypatch, output, "--check-ai") == 1


@pytest.mark.parametrize("data", [b"broken", webp(animated=True)])
def test_regeneration_preflight_never_reaches_downloads(tmp_path, monkeypatch, data):
    import download_ui
    source = tmp_path / "bad.webp"
    source.write_bytes(data)
    downloads = Mock(side_effect=AssertionError("must not discover models"))
    monkeypatch.setattr(download_ui, "get_models_to_download", downloads)
    assert run_cli(monkeypatch, source) == 2
    downloads.assert_not_called()


def test_check_malformed_returns_two(tmp_path, monkeypatch, capsys):
    source = tmp_path / "bad.webp"
    source.write_bytes(b"RIFF\x04\0\0\0WEBP")
    assert run_cli(monkeypatch, source, "--check-ai") == 2
    assert "incomplete" in capsys.readouterr().err


def test_verbose_remove_all_can_strip_malformed_metadata(tmp_path, monkeypatch):
    source = tmp_path / "bad.webp"
    source.write_bytes(webp(xmp=b"broken XML"))
    assert run_cli(monkeypatch, source, "--remove-ai", "--remove-all-metadata", "-v") == 0


def test_jpeg_check_reports_incomplete(monkeypatch, sample_jpg):
    assert run_cli(monkeypatch, sample_jpg, "--check-ai") == 2
