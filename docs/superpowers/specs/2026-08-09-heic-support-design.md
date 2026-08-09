# Design Document: HEIC Image Support

**Date:** 2026-08-09  
**Status:** Approved  
**Topic:** Full Native HEIC/HEIF Image Support Across Vision API, EXIF Tagging, and Web Gallery

---

## 1. Overview & Context

`exif-tagger` accepts image file extensions including `.heic` and `.heif` in `IMAGE_EXTENSIONS`. However, standard Pillow (`Pillow>=10.0`) cannot read or write HEIC/HEIF files without `pillow-heif` registered.

This document outlines the design for full native HEIC image support across the application:
1. Vision API image conversion to base64 JPEG/WebP.
2. EXIF `XPTags` (tag 40094) reading and writing on `.heic` and `.heif` files.
3. Web gallery file serving via on-the-fly JPEG conversion for browser compatibility (Chrome/Firefox/Edge).

---

## 2. Component Design & Changes

### 2.1 Dependencies & HEIC Opener Registration
* **`pyproject.toml`**:
  - Add `"pillow-heif>=0.15.0"` under `[project.dependencies]`.
* **`src/exif_tagger/__init__.py`**:
  - Register `pillow_heif.register_heif_opener()` on package import so Pillow automatically recognizes `.heic` and `.heif` formats.

### 2.2 Vision API Base64 Conversion (`ai_client.py`)
* Functions using `Image.open()` (e.g. `_image_to_base64()`) will transparently open `.heic`/`.heif` files.
* Convert color mode to `RGB` if needed, resize to `max_dim`, and serialize to `JPEG` or `WEBP` base64 string for OpenAI-compatible vision model endpoints.

### 2.3 EXIF Metadata Tagging (`exif_writer.py`)
* `get_existing_xptags()` reads `exif.get(40094)` from HEIC images.
* `write_xptags()` and `set_xptags()` update `XPTags` with UTF-16LE null-terminated strings and save back to the HEIC file via Pillow (`img.save(path, exif=exif_bytes)`).
* Integrity check (`_verify_image_integrity`) verifies that written HEIC images remain readable.

### 2.4 Gallery Web Server (`server.py`)
* `/api/gallery/image/file` and `/api/gallery/image/{image_id}/file`:
  - When the requested file extension is `.heic` or `.heif`, open the image with Pillow, convert to RGB, encode to JPEG in memory (`io.BytesIO`), and return a `Response(content=jpeg_bytes, media_type="image/jpeg")`.
  - Non-HEIC image formats continue to be served directly as static files via `FileResponse`.

---

## 3. Testing & Verification Plan

1. **Unit Tests**:
   - `test_heic_support.py`:
     - Generate test HEIC image using `pillow_heif`.
     - Test `_image_to_base64()` with `.heic` path.
     - Test `write_xptags()` and `get_existing_xptags()` with `.heic` path.
     - Verify EXIF tags persist and image remains valid.
2. **Integration Tests**:
   - Test gallery endpoints `/api/gallery/image/file` and `/api/gallery/image/{image_id}/file` serving `.heic` files with `image/jpeg` content type.
3. **Regression Tests**:
   - Run full pytest test suite to ensure JPEG, PNG, WEBP, and TIFF functionality is unaffected.

---

## 4. Security & Error Handling

* File paths for HEIC files continue to be validated against path traversal (`_validate_image_path`).
* If HEIC conversion or EXIF writing encounters corrupted image data, appropriate exceptions (`RuntimeError`, `HTTPException`) are raised and logged.
