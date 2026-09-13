# WebP Support Plan

Status: library implementation complete; validation and remaining integration gates recorded below

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
- [Pillow WebP reading and encoding options](https://pillow.readthedocs.io/en/stable/handbook/image-file-formats.html#webp)

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
- Detect and clean AI-related XMP and EXIF data using the explicit WebP field policy below. Existing PNG/JPEG behavior is a compatibility baseline, not evidence that those formats already have complete field filtering.
- Preserve non-AI ICC, EXIF, and XMP data when `keep_standard=True`.
- Remove standard metadata when `keep_standard=False` while retaining the minimum image-container structure needed for valid decoding.
- Preserve compressed image and animation chunks byte-for-byte in metadata-only mode.
- Run pixel regeneration on static WebP images and emit a valid static WebP with the original dimensions.
- Preserve a static WebP alpha channel by separating it before RGB regeneration and reattaching it unchanged.
- Reject animated WebP in pixel-regeneration mode with a stable, explicit error before any output is written.
- Keep existing PNG/JPEG public entrypoints and return types compatible. Replace the undocumented unknown-extension-to-PNG fallback with an explicit error and update its tests.

### Deferred

- Frame-by-frame pixel regeneration for animated WebP.
- Cryptographic validation of C2PA signatures and trust chains.
- Provider-specific pixel-watermark detection when no compatible detector is available.

Metadata-only cleaning can support animated WebP in the first release because a RIFF chunk rewrite does not decode or rebuild animation frames.

## Design

### 1. Replace implicit format fallback with explicit dispatch

Keep `get_image_format()` as an output-suffix helper with a strict mapping for PNG, JPEG, and WebP. Introduce separate byte-based input inspection and operation validation; output paths may not exist yet. Unknown output extensions, unsupported input bytes, and malformed recognized containers must raise informative errors. Introduce operation-specific capability checks where support differs:

- Metadata inspect/remove: existing PNG/JPEG behavior plus static and animated WebP. JPEG APP11 C2PA inspection is not implemented and must not be advertised as verified coverage.
- Pixel regeneration: PNG, JPEG, static WebP.
- Metadata clone/inject: retain PNG/JPEG support; defer public WebP cloning/injection to a separately tested follow-up. Reject any WebP donor or target in that operation before writing output.

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
- RIFF size and padding remain valid after removal; repeat these assertions for injection when that follow-up capability is enabled.
- Static regeneration returns a decodable WebP with matching dimensions and alpha.
- Animated regeneration fails before output creation and leaves the source unchanged.
- PNG/JPEG regression tests pass; update only tests for intentional contract changes such as the unknown-suffix fallback. Preserve PNG framed C2PA bytes and legacy return types.

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

1. Strict output-format dispatch, byte-based input inspection, and capability tests. Keep public WebP operations disabled until their implementation is complete.
2. RIFF/WebP C2PA detection, extraction, removal, and malformed-input tests; strict verification primitives.
3. WebP EXIF/XMP/ICC preservation and metadata-only cleaning.
4. Static WebP regeneration, alpha preservation, and animated rejection.
5. Structured verification results, CLI wording, README, and release notes.
6. Photarium integration in its own repository and commit series.

The upstream contribution can be submitted from this fork after the complete `noai-watermark` test suite passes. Photarium can pin the reviewed fork commit while that pull request is open.

## Acceptance criteria

Repository acceptance checks:

- The complete test suite passes locally and in the Python compatibility matrix specified below; record any unavailable environments explicitly.
- The synthetic OpenAI-style WebP is detected as containing AI metadata.
- Metadata-only cleanup removes its `C2PA` chunk without changing compressed image or animation chunks.
- Static demarking produces a valid WebP with matching dimensions and documented alpha/encoding behavior.
- Animated demarking fails explicitly without writing a partial output.
- Output verification parses the actual output bytes and cannot return a clean result solely because a format is unrecognized.
- README and CLI help list support per operation and describe the pixel-watermark verification boundary.

Subsequent integration acceptance checks:

- External-sample gate: the Photarium sample is detected before processing and has no embedded C2PA or recognized AI metadata after processing, verified independently with ExifTool.
- Photarium integration gate: Photarium reads back and verifies the hosted child original while retaining catalog provenance and source lineage.

## Implementation review and preparation

Reviewed against local commit `408ba84` on `codex/plan-webp-support`. This preparation changes the plan only; implementation has not started.

### Findings resolved in this revision

| Finding in the current code | Implementation consequence |
|---|---|
| `utils.get_image_format()` is called for destinations that do not exist. | Keep output suffix resolution separate from input byte inspection. |
| `extractor.has_ai_metadata()` checks exact top-level keys, while `extract_ai_metadata()` also checks keyword substrings. Neither inspects EXIF/XMP fields for AI content. | Use one WebP metadata classifier for detection, extraction, removal, and verification. |
| `cleaner._extract_non_ai_metadata()` loads EXIF wholesale, even with `keep_standard=False`. | Do not describe the existing implementation as a complete preservation/filtering policy. Test the new WebP policy explicitly. |
| C2PA APIs return false/empty for JPEG and swallow PNG read errors. | Add strict inspection for verification; preserve legacy PNG wrapper behavior where required by existing callers. JPEG C2PA absence remains unassessed. |
| C2PA summary tables omit `gpt-image` and `c2pa.watermarked.unbound`. | Add explicit signatures and synthetic assertions; label extracted summaries as heuristic, without asserting signature validity. |
| Regeneration catches metadata-cleanup failures and still reports success. | WebP cleanup or verification failure must prevent publication of the output. |
| CLI dependency installation and model discovery precede image validation. | Validate operation, source, animation, and destination before entering the heavyweight handler. |
| `remove_watermark_batch()` already includes `.webp` by default. | Exercise the batch path as well as the single-image API; failed items must never appear in its returned success list. |
| Existing regeneration mocks sometimes return objects whose `save()` writes no image. | Add tests with real Pillow output and stub only model inference. These tests must reopen actual bytes. |
| Release workflows build on Python 3.11; there is no test workflow. | Add a test matrix during implementation and distinguish local evidence from cross-version coverage. |

### Module and API boundaries

- `utils.py`: strict destination mapping, preserving valid PNG/JPEG calls. Keep `is_supported_format(path)` usable for nonexistent paths as a suffix hint; it is never proof of file validity or animation support.
- `image_formats.py`: inspect actual input bytes and decoded properties; validate operation capabilities. A supported byte signature takes precedence over a misleading input suffix. Metadata-only WebP output must use `.webp`; reject implicit transcoding and in-place writes through a mismatched suffix. Regeneration may retain existing PNG/JPEG conversions, but WebP with alpha must not be silently written to JPEG.
- `riff.py`: WebP container parsing and chunk rewriting, without importing metadata policy or diffusion code.
- `webp_metadata.py`: EXIF/XMP parsing, field classification, cleaning, and preservation. Keep this responsibility separate from the RIFF parser.
- `c2pa.py`: stable facade plus container-neutral payload extraction for internal use. Preserve PNG `extract_c2pa_chunk()` framing. Define WebP framed return bytes explicitly as its FourCC, little-endian length, payload, and optional padding; do not treat those bytes as a PNG chunk.
- `image_output.py`: alpha reattachment, explicit encoding, temporary-file lifecycle, and replacement after verification. Both regeneration profiles use this helper through `WatermarkRemover`; `ctrlregen/engine.py` remains responsible for RGB inference.
- `verification.py`: a typed result and strict output inspection, exported through `metadata_handler.py`. Existing cleaning and regeneration calls continue returning `Path`. Add a separate verification entrypoint; do not change those methods to return dictionaries or rely on a mutable last-result attribute.

### RIFF validation and safe writes

Validate the complete chunk stream before returning an absence result. Require exact declared size, complete headers/payloads/padding, and zero odd-length padding. Reject trailing bytes as this toolkit's stricter policy; the WebP specification allows readers to ignore them. Validate image-bearing structure, VP8X length/flags/canvas, essential chunk order, and animation frame structure. A header alone does not prove a decodable image.

Duplicate C2PA chunks remain inspectable: report presence, expose every payload internally, and remove every occurrence. Unrecognized or empty C2PA payloads still count as embedded credentials. Reject duplicate EXIF/XMP/ICCP chunks in the first release to avoid conflicting field interpretations. Preserve unknown chunks and their order; removal of all metadata means the documented C2PA/EXIF/XMP/ICCP set, not a promise to classify arbitrary private chunks.

Only metadata feature bits in VP8X may change during cleanup. Preserve canvas, alpha, animation, and all compressed image/frame bytes. Keep VP8X after metadata removal when valid. Follow-up injection must create VP8X when required by added EXIF/XMP/ICCP, preserve reconstruction order, and append C2PA last. C2PA has no VP8X feature bit.

Write to a unique sibling temporary file, close all input handles, verify the temporary artifact, then replace the destination atomically. Any parse, encode, cleanup, or verification failure leaves the source and any existing destination unchanged and removes the temporary file. Cover both explicit destinations and default in-place use. Do not suppress cleanup exceptions on the WebP path.

### WebP metadata policy

Use explicit field identity and structured values. Do not apply broad substrings such as `model` to standard camera fields: EXIF Make/Model, Artist, Copyright, DateTime, Orientation, exposure fields, GPS, and ICC data must survive when retaining standard metadata.

- EXIF: inspect Software, ImageDescription, UserComment, and Windows XP text fields for recognized generator names or structured generation parameters. Decode their declared text encodings. Remove an entire matching text field; retain unrelated fields and embedded thumbnails. Support TIFF-form EXIF and the common `Exif` prefix. Preserve an untouched EXIF chunk byte-for-byte; when filtering is required, verify retained tag values and fail if the serializer cannot preserve them.
- XMP: parse XML without external-entity resolution; match property namespace/local name and recognized generator values. Handle both attributes and child elements, including RDF collections. Remove recognized AI parameter properties, generator-valued CreatorTool, and algorithmic digital-source declarations. Preserve unrelated creator, rights, title, description, dates, and camera properties. Pin exact names and namespace URIs in a policy table and paired positive/negative fixtures before implementing the classifier.
- `keep_standard=True`: preserve ICCP and unchanged EXIF/XMP bytes. Modified packets may be reserialized, but retained values must survive. Unparseable metadata raises an explicit error; it cannot produce a clean verdict.
- `keep_standard=False`: remove C2PA, EXIF, XMP, and ICCP chunks wholesale. This permits removing malformed metadata payloads when the RIFF container itself is valid. Removing ICC can affect color interpretation even though compressed image bytes remain unchanged.

C2PA presence alone does not establish AI authorship. Retain the existing compatibility policy that AI cleanup strips embedded C2PA credentials, while reporting `c2pa_present` separately and documenting that policy. Claims of AI-metadata absence refer to recognized fields under the declared policy; they do not cover arbitrary private payloads.

### Regeneration and result contract

Use lossless WebP output by default. Add keyword-only `webp_quality: int | None = None` to the applicable APIs and `--webp-quality` to the CLI: `None` selects lossless; an integer from 0 through 100 explicitly selects lossy color encoding. Reject the option for non-WebP destinations. Document that quality 100 remains lossy. Preserve alpha samples exactly under either encoding mode. Set `exact=True` to retain RGB values under fully transparent pixels in lossless output; verify alpha on the minimum supported Pillow version as well as the current environment.

Preflight animated WebP before RGB conversion or model discovery. Use both container animation declarations and decoded frame information, including a single-frame animation container. Raise `ValueError` with the stable message `Animated WebP is not supported for pixel regeneration` before output creation. In `watermark_remover.remove_watermark()`, run preflight ahead of the `WatermarkRemover(...)` constructor because that constructor may auto-install dependencies.

Pad RGB input when a model requires dimensions divisible by eight, then remove only the added padding. Never crop original edges or resample the saved alpha. Test odd dimensions, dimensions below eight, and both default/CtrlRegen profiles. Reopen the saved image, load its pixels, and compare format, canvas, frame count, and alpha samples.

The verification result includes the seven fields listed above plus `inspection_complete` and `inspection_errors`. Presence fields are nullable when inspection is unavailable or incomplete. `dimensions_valid` is nullable without an expected size. `pixel_regeneration_applied` comes from the operation that actually ran, not inference from output bytes. With no independent detector, both detector fields are null. Malformed/unsupported inputs must yield an explicit failure, never an all-clear result. JPEG C2PA coverage must remain marked incomplete in this new verifier until an APP11 implementation exists.

Keep existing check-mode exit codes for detected/absent metadata (`0`/`1`); use `2` for invalid input or incomplete inspection. Catch check-mode errors so they do not escape as tracebacks. Emit verified-absence text only after complete inspection. Otherwise print the limited result and the reason. Replace unconditional regeneration-success wording with the actual operation and inspection results.

### Test and delivery preparation

Start with `tests/test_image_formats.py`, `tests/test_riff.py`, and `tests/test_verification.py`. Then add focused metadata, output, and CLI tests; keep fixture builders in a small test helper if `conftest.py` becomes unwieldy. Fixtures must be independently constructed, not exclusively produced by the implementation under test.

Extend the original matrix with misleading suffixes, invalid image payloads inside valid RIFF framing, trailing data, nonzero/missing padding, conflicting metadata chunks, unknown chunks, all C2PA occurrences, standard camera Model, mixed EXIF/XMP properties, malformed metadata, partial alpha values, single-frame animation containers, in-place errors, existing destination preservation, repeated cleanup, batch failures, and CLI errors before any model/network calls. Test only the stubbed inference boundary for routine regression runs; real model execution is a separate integration check.

Add CI for Python 3.10 through 3.14, recording dependency-resolution failures separately from code failures. Run the complete suite before each implementation commit. Exercise the installed CLI from the same virtual environment and verify a built wheel contains every new flat `src` module. Keep package version changes for the release step.

Implement the RIFF/parser and strict verification foundation first, enable metadata operations after the field-policy tests pass, and enable static regeneration after transactional output tests pass. Public WebP clone/inject support remains deferred; do not silently discard unsupported metadata. Preserve the container-neutral payload boundary for that follow-up.

The external Photarium sample remains an integration requirement from the earlier diagnosis; its hosted bytes have not been rechecked during this plan review. Obtain it through the Photarium MCP when implementation reaches that gate. Record source/output hashes, dimensions, chunk inventory, and ExifTool observations outside the repository. Real regeneration, Photarium changes, uploads, and hosted readback belong to that later verification work.

### Baseline verification record

- Command: `.venv/bin/python -m pytest -ra` at commit `408ba84`.
- Result: **227 passed, 13 warnings, 11.79 seconds**, with no skipped tests.
- Warnings include PyTorch's Python 3.14 JIT deprecation, missing optional MediaPipe, SciPy/timm deprecations, and duplicate model registrations; the passing suite does not establish real inference compatibility.
- Runtime: Python 3.14.3, Pillow 12.3.0, libwebp 1.6.0, piexif 1.1.3, pytest 9.1.1. Pillow reports WebP support available.
- ExifTool 12.70 is installed. It was not run against the external sample during preparation.
- Other Python versions, real model inference, a built-wheel install, and Photarium hosted readback have not been verified in this review.
- Local test log: `/private/tmp/noai-webp-review-pytest.log` (temporary evidence; the result above is the durable record).

## Implementation record

The library changes implement strict input inspection, RIFF validation, C2PA payload dispatch, WebP EXIF/XMP/ICC handling, transactional cleanup, static regeneration, alpha retention, quality selection, structured verification, and CLI reporting. Public WebP cloning/injection remains deferred as specified. Detailed field coverage is documented in `WEBP_METADATA_POLICY.md`; release notes are in `CHANGELOG.md`.

Implementation commits:

- `6cb9faa`: format dispatch and RIFF validation.
- `267c053`: C2PA, metadata filtering, preservation, and verification.
- `9e80bcd`: static regeneration, CLI reporting, and regression tests.

Validation completed:

- Full suite on Python 3.14.3 / Pillow 12.3.0: **343 passed**, 13 pre-existing dependency warnings.
- New WebP suites on Python 3.11.7 / Pillow 10.0.0: **115 passed**.
- Full suite on Python 3.11.7 / Pillow 10.0.0: **343 passed** after installing Torch and Hugging Face Hub for existing tests. The initial lightweight-environment run failed 30 tests on those missing dependencies; the failures were resolved. Inference remains stubbed in regeneration tests.
- Wheel built outside the repository and checked for all **29** top-level Python modules.
- Installed wheel CLI exercised from `/private/tmp`, importing `metadata_handler` from its isolated `site-packages`; its cleaned output is byte-identical to the development CLI output.
- Installed development CLI detected the real Photarium sample and cleaned its credentials; ExifTool **12.70** independently reported no C2PA fields afterward.
- Sample dimensions remain **1168 × 1456**. Its compressed `VP8L` chunk is byte-identical. The original contains `VP8L` and `C2PA`; the cleaned file contains `VP8L` only.
- Source SHA-256: `6bb907e66f0f9b666f420a336e20dc8b3f9d7494468c072eef6ba61461b6e976`.
- Cleaned SHA-256: `58e70a7c17df683fadfa2d01cf602b5ea343e5cda2f36402d6035b2fd7ce20ff`.
- External sample, ExifTool dumps, and JSON verification record are under `/private/tmp/noai-webp-integration/`; no external image was added to the repository.

The Python 3.10–3.14 CI matrix and minimum-Pillow job are configured but have not run remotely. Regeneration tests use real encoding with stubbed inference; a real model run and independent pixel-watermark detection have not been performed. Photarium adapter changes, child upload, and hosted-original readback remain the subsequent consuming-repository integration phase.
