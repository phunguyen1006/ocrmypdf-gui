# Changelog

## v0.1.1 — 2026-08-15

- Added the full pinned Tesseract language catalogue, multi-language selection, lazy language-pack downloads, and offline per-page language detection.
- Added Vietnamese and Simplified Chinese mixed-document OCR support.
- Added a resizable, vertically scrollable Advanced Settings dialog with a persistent action footer.
- Added a custom monochrome application icon for the window, taskbar, and Windows build.
- Prevented OCR, detection, download, and dependency subprocesses from opening console windows on Windows.
- Fixed queue jobs getting stuck at Waiting and fixed completion-event race conditions.
- Fixed selected-page indexing and reliable publishing across drives, including Google Drive folders.
- Automatically promotes image scans containing watermark or incidental text from Skip to Redo OCR.
- Validates that output PDFs contain a usable searchable text layer before reporting success.

## v0.1.0

- Initial public release.
