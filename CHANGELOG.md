# Changes

## Unreleased

- Add byte-validated WebP metadata inspection and cleanup for static and animated files, including top-level C2PA credentials and recognized EXIF/XMP fields.
- Preserve compressed image and animation chunks during metadata cleanup; verify outputs before replacing destinations.
- Add static WebP regeneration with lossless output by default, explicit lossy quality, original dimensions, and unchanged alpha samples.
- Reject animated WebP regeneration before model setup. WebP metadata cloning/injection remains deferred.
- Add structured verification results and explicit CLI reporting for incomplete inspection and unavailable pixel-watermark detection.
- Reject unknown output extensions instead of silently encoding PNG.
- Add Python 3.10–3.14 CI and a minimum-Pillow compatibility job.
