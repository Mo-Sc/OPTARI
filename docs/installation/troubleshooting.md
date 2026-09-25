# Troubleshooting

## "OPTARI could not be verified" / "app is damaged" on first run

OPTARI's standalone executables aren't code-signed. This is expected — see the OS-specific workaround in
[Installation](index.md#option-a-standalone-executable-recommended-for-clinical-use).

## First launch is slow / needs internet access

On first run, OPTARI downloads the rest of its runtime dependencies. Segmentation and DeepMB reconstruction
models are downloaded separately, the first time each is actually used. All of these are one-time downloads,
cached locally afterward.

## Segmentation or DeepMB reconstruction is slow / not using my GPU

Both run via ONNX Runtime, which silently falls back to CPU execution if a compatible GPU/driver isn't detected
— there's no error, just slower inference. Confirm your ONNX Runtime GPU providers are installed and available to
the app's Python environment if you expect GPU acceleration.

## Something else

Search or open an issue on [GitHub](https://github.com/Mo-Sc/OPTARI/issues) — bug report, feature request, and
documentation-gap templates are all available there.
