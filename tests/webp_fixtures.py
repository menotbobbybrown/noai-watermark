"""Independent WebP fixture assembly; no production RIFF helpers used."""

import io
import struct

from PIL import Image


def chunk(kind: bytes, data: bytes) -> bytes:
    return kind + struct.pack("<I", len(data)) + data + b"\0" * (len(data) % 2)


def riff(body: bytes) -> bytes:
    return b"RIFF" + struct.pack("<I", len(body) + 4) + b"WEBP" + body


def webp(*, alpha=False, animated=False, lossless=True, size=(17, 19), **metadata) -> bytes:
    image = Image.new("RGBA" if alpha else "RGB", size, (45, 80, 140, 123) if alpha else (45, 80, 140))
    if alpha:
        image.putalpha(Image.frombytes("L", size, bytes(i % 256 for i in range(size[0] * size[1]))))
    stream = io.BytesIO()
    options = dict(format="WEBP", lossless=lossless, exact=True, **metadata)
    if animated:
        options.update(save_all=True, append_images=[Image.new(image.mode, size, "red")], duration=[70, 130], loop=3)
    image.save(stream, **options)
    return stream.getvalue()


def credentialed(**kwargs) -> bytes:
    base = webp(**kwargs)
    payload = b"jumb\0c2pa\0OpenAI\0gpt-image 2.0\0c2pa.created\0c2pa.watermarked.unbound\0trainedAlgorithmicMedia"
    return riff(base[12:] + chunk(b"C2PA", payload))
