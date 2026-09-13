import xml.etree.ElementTree as ET

import piexif
import pytest

from c2pa import extract_c2pa_chunk, extract_c2pa_info, extract_c2pa_payloads, has_c2pa_metadata
from cleaner import remove_ai_metadata
from cloner import clone_metadata
from extractor import extract_ai_metadata, has_ai_metadata
from injector import inject_metadata
from riff import parse_webp
from tests.webp_fixtures import chunk, credentialed, riff, webp
from verification import verify_image
from webp_exif import filter_exif
from webp_xmp import filter_xmp

XMP_PACKET = b'''<x:xmpmeta xmlns:x="adobe:ns:meta/" xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
 xmlns:xmp="http://ns.adobe.com/xap/1.0/" xmlns:dc="http://purl.org/dc/elements/1.1/"
 xmlns:tiff="http://ns.adobe.com/tiff/1.0/" xmlns:iptc="http://iptc.org/std/Iptc4xmpExt/2008-02-29/">
 <rdf:RDF><rdf:Description xmp:CreatorTool="OpenAI gpt-image 2.0" tiff:Model="Camera model 7" dc:rights="Julian">
 <dc:title><rdf:Alt><rdf:li xml:lang="x-default">Standard title</rdf:li></rdf:Alt></dc:title>
 <xmp:prompt><rdf:Seq><rdf:li>A test prompt</rdf:li></rdf:Seq></xmp:prompt>
 <iptc:DigitalSourceType rdf:resource="http://cv.iptc.org/newscodes/digitalsourcetype/trainedAlgorithmicMedia"/>
 </rdf:Description></rdf:RDF></x:xmpmeta>'''


def mixed_exif():
    return piexif.dump({"0th": {piexif.ImageIFD.Make: b"Nikon", piexif.ImageIFD.Model: b"Camera model 7",
                               piexif.ImageIFD.Artist: b"Julian", piexif.ImageIFD.Software: b"OpenAI gpt-image"},
                        "Exif": {piexif.ExifIFD.UserComment: b"ASCII\0\0\0prompt: test, seed: 42"}})


@pytest.mark.parametrize("options", [{}, {"alpha": True}, {"animated": True}, {"lossless": False}])
def test_metadata_cleanup_preserves_image_chunks(tmp_path, options):
    source, output = tmp_path / "source.webp", tmp_path / "out.webp"
    source.write_bytes(credentialed(exif=mixed_exif(), xmp=XMP_PACKET, icc_profile=b"profile", **options))
    original = source.read_bytes()
    assert has_ai_metadata(source)
    assert has_c2pa_metadata(source)
    summary = extract_c2pa_info(source)
    assert summary["ai_tool"] == "gpt-image"
    assert "OpenAI" in summary["issuer"]
    assert "watermarked.unbound" in summary["actions"]
    assert "trainedAlgorithmicMedia" in summary["source_type"]
    assert summary["signature_validated"] is False
    assert extract_c2pa_chunk(source)[:4] == b"C2PA"
    assert len(extract_c2pa_payloads(source)) == 1
    assert {"EXIF", "XMP", "c2pa"} <= extract_ai_metadata(source).keys()
    assert remove_ai_metadata(source, output) == output
    assert source.read_bytes() == original
    assert not has_ai_metadata(output)
    assert not has_c2pa_metadata(output)
    before, after = parse_webp(original), parse_webp(output.read_bytes())
    pixels = {b"VP8 ", b"VP8L", b"ALPH", b"ANIM", b"ANMF", b"ICCP"}
    assert [c.to_bytes() for c in before if c.fourcc in pixels] == [c.to_bytes() for c in after if c.fourcc in pixels]
    exif = next(c.payload for c in after if c.fourcc == b"EXIF")
    assert piexif.load(exif)["0th"][piexif.ImageIFD.Model] == b"Camera model 7"
    xmp = next(c.payload for c in after if c.fourcc == b"XMP ")
    assert b"Standard title" in xmp and b"Julian" in xmp and b"Camera model 7" in xmp
    assert b"OpenAI" not in xmp and b"A test prompt" not in xmp
    saved = output.read_bytes()
    remove_ai_metadata(output)
    assert output.read_bytes() == saved
    assert verify_image(output, (17, 19)).inspection_complete


def test_standard_packets_survive_verbatim():
    exif = piexif.dump({"0th": {piexif.ImageIFD.Model: b"Stable model camera", piexif.ImageIFD.Software: b"Lightroom"}})
    assert filter_exif(exif) == (exif, {})
    xmp = XMP_PACKET.replace(b"OpenAI gpt-image 2.0", b"Lightroom").replace(b"<xmp:prompt>", b"<dc:description>").replace(b"</xmp:prompt>", b"</dc:description>").replace(b"trainedAlgorithmicMedia", b"digitalCapture")
    assert filter_xmp(xmp) == (xmp, {})


@pytest.mark.parametrize("metadata", [{"exif": b"broken exif"}, {"xmp": b"broken xml"}, {"xmp": b'<!DOCTYPE x [<!ENTITY e "test">]><x>&e;</x>'}])
def test_malformed_metadata_never_reports_absence(tmp_path, metadata):
    source, output = tmp_path / "source.webp", tmp_path / "output.webp"
    source.write_bytes(webp(**metadata))
    output.write_bytes(b"existing destination")
    original = source.read_bytes()
    result = verify_image(source)
    assert not result.inspection_complete and result.ai_metadata_present is None
    for destination in (source, output):
        with pytest.raises(ValueError):
            remove_ai_metadata(source, destination)
    assert source.read_bytes() == original
    assert output.read_bytes() == b"existing destination"
    remove_ai_metadata(source, output, keep_standard=False)
    assert verify_image(output).inspection_complete
    assert not has_ai_metadata(output)
    assert not list(tmp_path.glob(".*.webp"))


def test_strip_all_standard_chunks(tmp_path):
    source = tmp_path / "source.webp"
    source.write_bytes(credentialed(exif=mixed_exif(), xmp=XMP_PACKET, icc_profile=b"profile"))
    remove_ai_metadata(source, keep_standard=False)
    assert not {b"C2PA", b"EXIF", b"XMP ", b"ICCP"} & {c.fourcc for c in parse_webp(source.read_bytes())}


def test_all_credentials_including_empty_removed(tmp_path):
    source = tmp_path / "source.webp"
    data = webp()
    source.write_bytes(riff(data[12:] + chunk(b"C2PA", b"") + chunk(b"C2PA", b"unknown")))
    assert has_c2pa_metadata(source) and has_ai_metadata(source)
    assert len(extract_c2pa_payloads(source)) == 2
    remove_ai_metadata(source)
    assert not has_c2pa_metadata(source)


def test_webp_clone_and_inject_rejected(tmp_path, sample_png):
    source, output = tmp_path / "source.webp", tmp_path / "output.png"
    source.write_bytes(webp())
    for donor, target in ((source, sample_png), (sample_png, source)):
        with pytest.raises(ValueError, match="cloning"):
            clone_metadata(donor, target, output)
    with pytest.raises(ValueError, match="injection"):
        inject_metadata(source, output, {})
    assert not output.exists()


def test_xmp_attribute_and_element_equivalence():
    packet = XMP_PACKET.replace(b'xmp:CreatorTool="OpenAI gpt-image 2.0"', b'').replace(b"</rdf:Description>", b"<xmp:CreatorTool>OpenAI gpt-image 2.0</xmp:CreatorTool></rdf:Description>")
    encoded, fields = filter_xmp(packet)
    assert b"OpenAI" not in encoded
    assert any("CreatorTool" in name for name in fields)
    ET.fromstring(encoded)


@pytest.mark.parametrize("comment", [
    b"UNICODE\0" + "OpenAI gpt-image".encode("utf-16-be"),
    b"UNICODE\0" + "OpenAI gpt-image".encode("utf-16"),
    b"JIS\0\0\0\0\0" + "OpenAI".encode("shift_jis"),
])
def test_exif_user_comment_encodings(comment):
    exif = piexif.dump({"Exif": {37510: comment}})
    cleaned, removed = filter_exif(exif)
    assert removed and 37510 not in piexif.load(cleaned)["Exif"]


def test_exif_thumbnail_and_gps_preserved():
    import io
    from PIL import Image
    thumbnail = io.BytesIO()
    Image.new("RGB", (8, 8), "red").save(thumbnail, "JPEG")
    exif = piexif.dump({"0th": {305: b"OpenAI"}, "GPS": {1: b"N", 2: ((51, 1), (30, 1), (0, 1))}, "1st": {}, "thumbnail": thumbnail.getvalue()})
    cleaned, _ = filter_exif(exif)
    assert piexif.load(cleaned)["thumbnail"] == piexif.load(exif)["thumbnail"]
    assert piexif.load(cleaned)["GPS"] == piexif.load(exif)["GPS"]


def test_unknown_exif_tags_prevent_lossy_rewrite():
    import struct
    exif = bytearray(mixed_exif())
    # piexif emits big-endian TIFF; replace the first known tag with a private tag.
    first = 6 + struct.unpack_from(">I", exif, 10)[0] + 2
    struct.pack_into(">H", exif, first, 65000)
    with pytest.raises(ValueError, match="unknown tags"):
        filter_exif(bytes(exif))


def test_failed_verification_does_not_publish(tmp_path, monkeypatch):
    import verification
    source, output = tmp_path / "source.webp", tmp_path / "out.webp"
    source.write_bytes(credentialed())
    original = source.read_bytes()
    output.write_bytes(b"existing")
    monkeypatch.setattr(verification, "verify_image", lambda *a: verification.VerificationResult())
    with pytest.raises(ValueError, match="verification failed"):
        remove_ai_metadata(source, output)
    assert source.read_bytes() == original and output.read_bytes() == b"existing"
    assert not list(tmp_path.glob(".*.webp"))
