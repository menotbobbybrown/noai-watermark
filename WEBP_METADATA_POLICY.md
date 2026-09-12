# WebP metadata policy

WebP inspection uses RIFF bytes and decoded image properties. A filename suffix is a hint. Output filenames must match the selected encoder. Metadata-only cleanup requires WebP input and a `.webp` destination.

## Operations

| Operation | Static WebP | Animated WebP |
|---|---|---|
| Inspect metadata | Supported | Supported |
| Remove metadata | Supported | Supported; compressed frames and timing retained |
| Pixel regeneration | Supported | Rejected before model setup and output creation |
| Clone or inject metadata | Deferred | Deferred |

C2PA presence means embedded credentials are present. It does not, by itself, establish AI authorship. For compatibility with the existing toolkit, AI cleanup removes every top-level C2PA chunk, including empty or unfamiliar payloads. Summary fields use heuristic byte signatures; no signature or trust-chain validation runs.

## Field matching

Detection, extraction, cleaning, and verification use the same WebP policy.

| Container | Fields inspected | Matching rule |
|---|---|---|
| EXIF 0th IFD | ImageDescription (270), Software (305), XPTitle through XPSubject (40091–40095) | Recognized generator name or at least two structured parameter keys |
| EXIF Exif IFD | UserComment (37510) | Same rule, after decoding ASCII/UTF-8, Unicode, or JIS text |
| XMP basic namespace `http://ns.adobe.com/xap/1.0/` | CreatorTool | Recognized generator text or structured parameters |
| XMP basic namespace or no namespace | Canonical AI parameter names | Case-insensitive exact property name |
| IPTC extension namespace `http://iptc.org/std/Iptc4xmpExt/2008-02-29/` | DigitalSourceType | `trainedAlgorithmicMedia`, `algorithmicMedia`, or `compositeWithTrainedAlgorithmicMedia`, including URI values |

Canonical parameter names are `parameters`, `postprocessing`, `extras`, `workflow`, `prompt`, `Dream`, `SD:mode`, `StableDiffusionVersion`, `generation_time`, `Model`, `Model hash`, `Seed`, `sampler`, `steps`, `cfg_scale`, and `negative_prompt`. Generator names include OpenAI, gpt-image, GPT-4o, ChatGPT, DALL-E, Midjourney, Stable Diffusion, ComfyUI, AUTOMATIC1111, Adobe Firefly, Google Imagen, and DreamStudio. `src/metadata_policy.py` defines the executable rules.

XMP attributes, elements, RDF collections, and resource URIs are inspected. Unrelated creator, rights, title, description, dates, and camera properties survive. Parameter-like names in other namespaces are outside this policy. Standard EXIF Make/Model, Artist, Copyright, DateTime, Orientation, exposure, GPS, and embedded thumbnails are retained.

## Preservation and errors

With `keep_standard=True`, ICCP and unchanged EXIF/XMP chunks retain their original bytes. Modified EXIF is checked for retained tag values; unknown tags prevent serialization that could discard them. Modified XMP may use different XML whitespace or namespace prefixes while preserving retained property values. Unparseable metadata produces an explicit error.

With `keep_standard=False`, all C2PA, EXIF, XMP, and ICCP chunks are removed. Malformed metadata payloads can be removed in this mode if the image container remains valid. Removing ICC can change color interpretation. Unknown private chunks survive in both modes; “all metadata” refers to the four documented chunk types.

Compressed image data, alpha chunks, animation frames, delays, and loop settings are preserved byte-for-byte during metadata cleanup. Only RIFF size and applicable VP8X metadata bits change around removed or rewritten packets. Invalid RIFF sizes, padding, frame structure, or conflicting metadata chunks are rejected. The toolkit rejects trailing data even though WebP readers may choose to ignore it.

Output is written to a unique sibling temporary file, inspected, and atomically moved to the destination. Failures preserve both the source and any existing destination.

## Regeneration

WebP output is lossless by default. `--webp-quality 0` through `--webp-quality 100` explicitly selects lossy color encoding; 100 is still lossy. The Python APIs accept keyword-only `webp_quality`. Alpha samples remain unchanged in either mode. RGB input is padded at the right/bottom edges for model alignment, and only that padding is removed afterward. Both regeneration profiles use the same output helper.

## Verification

`metadata_handler.verify_image(path, expected_size=None, pixel_regeneration_applied=False)` returns a `VerificationResult`; `to_dict()` produces JSON-compatible values. The operation supplies whether regeneration actually ran. A file inspection cannot establish that historical fact.

| Field | Meaning |
|---|---|
| `format_valid` | Recognized bytes, valid checked container structure, and successful decoding |
| `dimensions_valid` | Canvas matches expected size; null when no size was supplied |
| `ai_metadata_present` | Recognized AI fields or C2PA found; null if unknown |
| `c2pa_present` | Embedded credential chunks found; null if unassessed |
| `pixel_regeneration_applied` | Caller-provided operation outcome |
| `pixel_watermark_detector` | Null; no detector is integrated |
| `pixel_watermark_present` | Null; no independent pixel verdict is available |
| `inspection_complete` | Every applicable inspection completed |
| `inspection_errors` | Reasons inspection was unavailable or incomplete |

An absence claim requires complete inspection. PNG EXIF/XMP field inspection and JPEG APP11/EXIF/XMP inspection remain incomplete in this verifier. Existing PNG/JPEG metadata APIs retain their prior behavior and `Path` return types. CLI check mode returns 0 for detected metadata, 1 for absence, and 2 for invalid input or incomplete inspection. Successful cleaning returns 0 after complete verification; incomplete verification returns 2.
