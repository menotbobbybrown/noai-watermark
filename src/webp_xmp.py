"""Filter XMP attributes and RDF properties while preserving unrelated values."""

from __future__ import annotations

import xml.etree.ElementTree as ET

from metadata_policy import RDF, is_ai_property


def filter_xmp(payload: bytes) -> tuple[bytes, dict[str, str]]:
    # XML permits UTF-16/32 encodings; normalize only for rejecting declarations.
    declaration_scan = payload.replace(b"\0", b"").upper()
    if b"<!DOCTYPE" in declaration_scan or b"<!ENTITY" in declaration_scan:
        raise ValueError("XMP DTD/entity declarations are not supported")
    try:
        root = ET.fromstring(payload)
    except (ET.ParseError, ValueError) as error:
        raise ValueError(f"Invalid WebP XMP: {error}") from error
    removed: dict[str, str] = {}

    def visit(element: ET.Element) -> None:
        for name, value in list(element.attrib.items()):
            if is_ai_property(name, value):
                removed[name] = value
                del element.attrib[name]
        for child in list(element):
            text = " ".join(child.itertext()).strip()
            values = list(child.itertext()) + [value for node in child.iter() for value in node.attrib.values()]
            # RDF resource attributes can carry a DigitalSourceType URI.
            if any(is_ai_property(child.tag, value) for value in values):
                removed[child.tag] = text or child.get(f"{{{RDF}}}resource", "")
                element.remove(child)
            else:
                visit(child)

    # The root can itself be a metadata property, rather than an xmpmeta wrapper.
    if is_ai_property(root.tag, " ".join(root.itertext())):
        removed[root.tag] = " ".join(root.itertext())
        root = ET.Element(f"{{{RDF}}}RDF")
    else:
        visit(root)
    return (ET.tostring(root, encoding="utf-8") if removed else payload), removed
