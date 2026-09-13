"""Recognized WebP AI fields; standard camera and descriptive fields are protected."""

import re

from constants import AI_METADATA_KEYS

XMP = "http://ns.adobe.com/xap/1.0/"
IPTC = "http://iptc.org/std/Iptc4xmpExt/2008-02-29/"
RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
# Parameter keys apply only to unqualified properties and the XMP basic namespace.
# Unknown namespaces are retained, with coverage limited to this declared policy.
PARAMETER_NAMESPACES = {"", XMP}
PARAMETER_KEYS = {key.lower() for key in AI_METADATA_KEYS} | {"sampler", "steps", "cfg_scale", "negative_prompt"}
GENERATOR = re.compile(
    r"\b(?:openai|gpt[- ]image|gpt-4o|chatgpt|dall[ -]?e|midjourney|"
    r"stable[ _-]?diffusion|comfyui|automatic1111|adobe firefly|google imagen|dreamstudio)\b",
    re.IGNORECASE,
)
PARAMETERS = re.compile(r"(?:^|[\n,{;])\s*[\"']?(?:prompt|negative_prompt|seed|sampler|cfg_scale|steps|model)[\"']?\s*[:=]", re.I)
SOURCE_TYPES = {"trainedAlgorithmicMedia", "algorithmicMedia", "compositeWithTrainedAlgorithmicMedia"}


def is_ai_text(text: str) -> bool:
    return bool(GENERATOR.search(text) or len(PARAMETERS.findall(text)) >= 2)


def split_name(name: str) -> tuple[str, str]:
    if name.startswith("{"):
        namespace, local = name[1:].split("}", 1)
        return namespace, local
    return "", name


def is_ai_property(name: str, value: str) -> bool:
    namespace, local = split_name(name)
    if namespace in PARAMETER_NAMESPACES and local.lower() in PARAMETER_KEYS:
        return True
    if (namespace, local) == (XMP, "CreatorTool"):
        return is_ai_text(value)
    if (namespace, local) == (IPTC, "DigitalSourceType"):
        return value.strip().rsplit("/", 1)[-1] in SOURCE_TYPES
    return False
