# WebP Support Plan

Status: implementation plan

Date: 2026-09-11

Target repository: `~/Code/noai-watermark`

Baseline: upstream `main` at `3bd94c6` (`v0.1.30`), including merged PR [#6](https://github.com/mertizci/noai-watermark/pull/6), “Fix CtrlRegen partial tile blending.”

Working branch: `codex/plan-webp-support`

## Objective

Add truthful WebP support to `noai-watermark` so callers can detect and remove embedded AI provenance from WebP files and run the pixel-regeneration workflow on static WebP images. Keep the public distinction between these outcomes:

1. Embedded AI metadata was detected or removed.
2. Pixel regeneration was applied to disrupt an invisible watermark.
3. An independent detector confirmed that a pixel watermark is absent.

The first two outcomes are within this repository. The third requires a provider-specific or compatible detector and must remain “not independently verified” when no detector is available.

## Why this work belongs here

`noai-watermark` owns image-format support, metadata extraction and cleaning, C2PA container handling, image encoding, and the regeneration workflow. Photarium should download the source, call this tool, upload the result, preserve catalog lineage, and verify the hosted artifact. Implementing WebP metadata logic inside Photarium would create a second format engine with different behavior from the CLI and Python API.

Photarium already resolves this checkout through `PHOTARIUM_NOAI_WATERMARK_ROOT`, so it can consume a tested commit from this fork before an upstream release includes the change.

## Verified trigger case

The Photarium source that exposed the gap is:

- Image ID: `e7fafb81-3126-4efb-00bc-e041da8e7d00`
- Filename: `HumboSocialRadioVumeterPoweredOn-demarked-expand-4x5-openai.webp`
- Media type: `image/webp`
- Dimensions: `1168x1456`
- Generator recorded by Photarium: OpenAI `gpt-image-2`

Inspection of the stored original with ExifTool 12.70 found an embedded RIFF `C2PA` chunk containing a JUMBF manifest. The manifest identifies `gpt-image 2.0`, `trainedAlgorithmicMedia`, the OpenAI Media Service API, and the action `c2pa.watermarked.unbound`.

This file proves that WebP can carry the AI-production provenance the current tool is intended to detect and remove. It should be used as an external integration sample during verification. Do not copy it into this repository. Unit fixtures should be generated synthetically.

Authoritative format references:

- [WebP container specification](https://developers.google.com/speed/webp/docs/riff_container)
- [C2PA 2.4, embedding manifests into RIFF-based assets](https://spec.c2pa.org/specifications/specifications/2.4/specs/C2PA_Specification.html#_embedding_manifests_into_riff_based_assets)

## Current limitations

The current code has several connected PNG/JPEG assumptions:

- `src/constants.py` limits `SUPPORTED_FORMATS` to `.png`, `.jpg`, and `.jpeg`.
- `src/utils.py:get_image_format()` treats JPEG explicitly and defaults every other extension to PNG. Adding `.webp` only to the allowlist would therefore write PNG bytes through a `.webp` path during metadata cleaning.
- `src/c2pa.py` recognizes only PNG signatures and `caBX` chunks. It returns `False` for every non-PNG path, which would create a false “clean” result for a WebP containing a valid `C2PA` chunk.
- `src/cleaner.py`, `src/extractor.py`, `src/injector.py`, and `src/cloner.py` assume PNG/JPEG metadata and container behavior.
- `src/watermark_remover.py` can ask Pillow to open a WebP, but its save and cleanup path is not WebP-aware. It also converts the source to RGB, which drops alpha, and the first-frame behavior would silently damage an animated WebP.
- Tests currently assert that WebP is unsupported.

## Scope and capability contract

### Required in the first release

- Detect static and animated WebP by validated RIFF/WEBP bytes, with the suffix used only as a caller-facing hint.
- Detect, extract, and remove top-level RIFF `C2PA` chunks.
- Detect and clean AI-related XMP and EXIF data using the same documented field policy as PNG/JPEG.
- Preserve non-AI ICC, EXIF, and XMP data when `keep_standard=True`.
- Remove standard metadata when `keep_standard=False` while retaining the minimum image-container structure needed for valid decoding.
- Preserve compressed image and animation chunks byte-for-byte in metadata-only mode.
- Run pixel regeneration on static WebP images and emit a valid static WebP with the original dimensions.
- Preserve a static WebP alpha channel by separating it before RGB regeneration and reattaching it unchanged.
- Reject animated WebP in pixel-regeneration mode with a stable, explicit error before any output is written.
- Keep all existing PNG/JPEG public entrypoints and behavior compatible.

### Deferred

- Frame-by-frame pixel regeneration for animated WebP.
- Cryptographic validation of C2PA signatures and trust chains.
- Provider-specific pixel-watermark detection when no compatible detector is available.

Metadata-only cleaning can support animated WebP in the first release because a RIFF chunk rewrite does not decode or rebuild animation frames.

## Design

### 1. Replace implicit format fallback with explicit dispatch

Change `get_image_format()` into a strict mapping for PNG, JPEG, and WebP. Unknown extensions or byte signatures must raise an informative error. Introduce operation-specific capability checks where support differs:

- Metadata inspect/remove: PNG, JPEG, static WebP, animated WebP.
- Pixel regeneration: PNG, JPEG, static WebP.
- Metadata clone/inject: advertise WebP only after its container-specific tests pass.

This avoids presenting one global “supported” set when individual operations have different guarantees.

### 2. Isolate RIFF/WebP container handling

Add a focused module such as `src/c2pa_webp.py` or `src/riff.py`. It should:

- Validate the `RIFF` header, declared little-endian size, and `WEBP` form type.
- Iterate chunks using four-byte IDs, little-endian payload lengths, and even-byte padding.
- Reject truncated, overflowing, or otherwise malformed chunk layouts.
- Locate every top-level `C2PA` chunk.
- Extract the C2PA payload for the existing summary parser.
- Remove selected chunks and recalculate the RIFF size without changing unrelated chunk bytes or order.
- Inject a `C2PA` payload as the final subchunk when cloning/injection support is enabled, following C2PA 2.4.

Keep the public functions in `src/c2pa.py` as format-dispatch entrypoints. Move PNG-specific iteration into private helpers or a sibling module so the public API remains stable.

The current `extract_c2pa_chunk()` returns container-framed PNG bytes. Cross-format cloning needs a container-neutral payload internally. Add an internal payload representation while preserving the existing public return behavior for PNG callers.

### 3. Make metadata-only cleaning pixel-preserving

For WebP metadata-only operations, rewrite the RIFF container instead of decoding and re-encoding the image. The VP8/VP8L, ALPH, ANIM, and ANMF chunks must remain byte-identical.

Handle metadata chunks deliberately:

- Remove `C2PA` when removing AI metadata.
- Parse EXIF and XMP through focused helpers that remove known AI fields while preserving allowed standard fields.
- Preserve ICCP when `keep_standard=True`.
- Define and test `keep_standard=False` for ICCP, EXIF, and XMP rather than relying on Pillow defaults.
- Rebuild VP8X feature flags when removing or adding metadata chunks so the container remains internally consistent.

Pillow can continue to supply decoded-image access. Container mutation and verification should use the byte-level WebP path because Pillow does not preserve unknown RIFF chunks reliably.

### 4. Add format-correct static WebP regeneration

Update `WatermarkRemover.remove_watermark()` and the CtrlRegen path to use a format-aware output helper:

- Detect animation before converting the image.
- Refuse animated WebP for regeneration.
- Separate and retain alpha when present.
- Process RGB pixels through the selected regeneration profile.
- Reattach alpha without resampling.
- Save as WebP with explicit encoding settings.
- Run AI-metadata cleanup on the finished WebP.
- Reopen the result and verify format, dimensions, frame count, and alpha expectations.

Choose and document the WebP encoding contract: use lossless output by default for testability, and expose an explicit quality option when output-size requirements call for lossy encoding.

### 5. Return precise verification results

The worker-facing result should report independent fields rather than one broad “verified” state:

- `format_valid`
- `dimensions_valid`
- `ai_metadata_present`
- `c2pa_present`
- `pixel_regeneration_applied`
- `pixel_watermark_detector`
- `pixel_watermark_present`, nullable when no detector ran

CLI text should say “AI metadata removed and verified absent” when the byte-level checks pass. It may also say “pixel regeneration applied.” It must not claim that an invisible pixel watermark was verified absent unless an independent detector produced that result.

## Test plan

Generate fixtures in `tests/conftest.py`; do not commit generated-image samples from Photarium.

### Container fixtures

- Plain lossy WebP.
- Plain lossless WebP.
- Static WebP with alpha.
- Animated WebP with multiple frames and known delays.
- WebP with ICCP, EXIF, and XMP.
- WebP with a synthetic OpenAI-style `C2PA` payload.
- WebP containing both standard metadata and `C2PA`.
- Odd-sized chunks that require RIFF padding.
- Truncated chunks, invalid declared sizes, missing `WEBP` form type, and duplicate `C2PA` chunks.

### Required assertions

- `is_supported_format(Path("image.webp"))` reflects the operation being requested.
- `has_c2pa_metadata()` returns true for the synthetic credentialed WebP.
- `extract_c2pa_info()` identifies the expected issuer, tool, actions, and digital source type.
- `has_ai_metadata()` returns true before cleanup and false afterward.
- Metadata-only removal leaves image and animation chunks byte-identical.
- Standard ICC/EXIF/XMP survives with `keep_standard=True`.
- AI fields and C2PA are absent after cleanup.
- `keep_standard=False` produces the documented reduced metadata set.
- RIFF size and padding remain valid after removal and injection.
- Static regeneration returns a decodable WebP with matching dimensions and alpha.
- Animated regeneration fails before output creation and leaves the source unchanged.
- PNG/JPEG tests remain unchanged and pass.

### Commands

Run targeted tests during implementation:

```bash
pytest tests/test_utils.py tests/test_c2pa.py tests/test_extractor.py tests/test_cleaner.py tests/test_injector.py tests/test_cloner.py tests/test_watermark_remover.py
```

Run the full suite before each implementation commit:

```bash
pytest
```

Exercise the installed CLI against generated fixtures:

```bash
noai-watermark credentialed.webp --check-ai
noai-watermark credentialed.webp --remove-ai -o metadata-clean.webp
noai-watermark credentialed.webp -o demarked.webp
```

For the external Photarium sample, verify source and output with ExifTool or a C2PA-aware inspector in addition to the library’s own checks. Record the tool version and observed fields. Keep the sample outside this repository.

## Photarium integration after the fork is ready

The consuming repository is `~/Code/cloud-flare-image-handler`. Update it only after a pinned fork commit passes this repository’s tests.

Required Photarium changes:

- Add WebP to the source and output MIME contracts in both the image-detail adapter and direct MCP service.
- Derive filenames from validated output bytes.
- Reject animated WebP for the `demark` effect while permitting supported metadata-only handling.
- Propagate the structured verification fields.
- Replace “verified no-AI” wording with the specific metadata and pixel-regeneration results.
- Preserve the Photarium parent, namespace, folder, URLs, tags, alt text, description, and tool-run provenance.
- Read back the hosted original and repeat the byte-level metadata check before reporting completion.

Relevant Photarium files found during diagnosis:

- `src/server/image-tools/noAiDemarkAdapter.ts`
- `src/server/image-tools/noAiDemarkRunner.ts`
- `mcp-server/src/runtime/demark/naming.ts`
- `mcp-server/src/runtime/demark/service.ts`
- `mcp-server/worker/demark_worker.py`
- `docs/photarium-mcp-tools.md`

## Delivery sequence

Keep the work reviewable in focused commits:

1. Strict format dispatch and capability tests.
2. RIFF/WebP C2PA detection, extraction, removal, and malformed-input tests.
3. WebP EXIF/XMP/ICC preservation and metadata-only cleaning.
4. Static WebP regeneration, alpha preservation, and animated rejection.
5. Structured verification results, CLI wording, README, and release notes.
6. Photarium integration in its own repository and commit series.

The upstream contribution can be submitted from this fork after the complete `noai-watermark` test suite passes. Photarium can pin the reviewed fork commit while that pull request is open.

## Acceptance criteria

The `noai-watermark` work is ready when all of the following are true:

- The complete test suite passes on the supported Python versions.
- The synthetic OpenAI-style WebP is detected as containing AI metadata.
- Metadata-only cleanup removes its `C2PA` chunk without changing compressed image or animation chunks.
- Static demarking produces a valid WebP with matching dimensions and documented alpha/encoding behavior.
- Animated demarking fails explicitly without writing a partial output.
- Output verification parses the actual output bytes and cannot return a clean result solely because a format is unrecognized.
- README and CLI help list support per operation and describe the pixel-watermark verification boundary.
- The external Photarium sample is detected before processing and has no embedded C2PA or AI metadata after processing.
- Photarium reads back and verifies the hosted child original while retaining catalog provenance and source lineage.
