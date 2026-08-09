# HEIC Image Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enable full native HEIC/HEIF image support for scanning, Vision API base64 payload generation, EXIF `XPTags` reading and writing, and web gallery JPEG conversion.

**Architecture:** Use `pillow-heif` registered via Pillow's plugin opener on package import. Vision API conversion in `ai_client.py` and EXIF writing in `exif_writer.py` operate via standard Pillow calls once HEIC opener is registered. Server endpoints `/api/gallery/image/file` and `/api/gallery/image/{image_id}/file` convert `.heic`/`.heif` files on-the-fly to JPEG so web browsers can render them in the gallery UI.

**Tech Stack:** Python 3.12, Pillow, pillow-heif, FastAPI, pytest

## Global Constraints

- Python floor: `>=3.12`
- Dependency: `pillow-heif>=0.15.0`
- EXIF Tag: 40094 (`XPTags`), UTF-16LE null-terminated string
- Response type for HEIC gallery endpoint: `Response(content=jpeg_bytes, media_type="image/jpeg")`

---

### Task 1: Add `pillow-heif` Dependency & Register HEIC Opener

**Files:**
- Modify: `pyproject.toml:12-17`
- Modify: `src/exif_tagger/__init__.py:1-4`
- Test: `tests/test_heic_support.py`

**Interfaces:**
- Consumes: `pillow_heif.register_heif_opener()`
- Produces: Registered `.heic` and `.heif` extensions in `PIL.Image.registered_extensions()`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_heic_support.py
from PIL import Image
import exif_tagger  # noqa: F401


def test_heic_opener_is_registered():
    registered = Image.registered_extensions()
    assert ".heic" in registered, ".heic format must be registered in Pillow"
    assert ".heif" in registered, ".heif format must be registered in Pillow"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_heic_support.py -v`  
Expected: FAIL with assertion error (`.heic` not in registered extensions)

- [ ] **Step 3: Write minimal implementation**

Add `pillow-heif>=0.15.0` to `pyproject.toml`:
```toml
dependencies = [
    "pydantic>=2.5",
    "PyYAML>=6.0",
    "Pillow>=10.0",
    "pillow-heif>=0.15.0",
    "openai>=1.10",
]
```

Add registration call to `src/exif_tagger/__init__.py`:
```python
"""exif-tagger: AI-powered image tagging with EXIF XPTags metadata."""

import pillow_heif

pillow_heif.register_heif_opener()

__version__ = "0.1.0"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_heic_support.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml src/exif_tagger/__init__.py tests/test_heic_support.py
git commit -m "feat: add pillow-heif dependency and register HEIC opener"
```

---

### Task 2: Verify & Ensure HEIC Support in Vision API and EXIF Writer

**Files:**
- Modify: `src/exif_tagger/exif_writer.py:150-160` (if format argument needed for saving)
- Test: `tests/test_heic_support.py`

**Interfaces:**
- Consumes: `exif_tagger.ai_client._image_to_base64()`, `exif_tagger.exif_writer.write_xptags()`, `exif_tagger.exif_writer.get_existing_xptags()`
- Produces: Base64 string for Vision API and verified EXIF XPTags in `.heic` files

- [ ] **Step 1: Write the failing tests for Vision API base64 and EXIF tag writing**

Append to `tests/test_heic_support.py`:
```python
import tempfile
from pathlib import Path
from PIL import Image
from exif_tagger.ai_client import _image_to_base64
from exif_tagger.exif_writer import get_existing_xptags, write_xptags


def test_heic_vision_api_base64():
    img = Image.new("RGB", (120, 120), color="blue")
    with tempfile.NamedTemporaryFile(suffix=".heic", delete=False) as f:
        heic_path = Path(f.name)

    img.save(heic_path, format="HEIF")

    b64 = _image_to_base64(heic_path, max_dim=100)
    assert isinstance(b64, str)
    assert len(b64) > 0


def test_heic_exif_write_and_read():
    img = Image.new("RGB", (100, 100), color="red")
    with tempfile.NamedTemporaryFile(suffix=".heic", delete=False) as f:
        heic_path = Path(f.name)

    img.save(heic_path, format="HEIF")

    modified, count = write_xptags(heic_path, ["nature", "outdoor"])
    assert modified is True
    assert count == 2

    tags = get_existing_xptags(heic_path)
    assert tags == {"nature", "outdoor"}
```

- [ ] **Step 2: Run test to verify it passes or check format handling**

Run: `.venv/bin/pytest tests/test_heic_support.py -v`  
Expected: Test runs and passes if format parameter handling in `write_xptags` works as expected. If format option is required in `exif_writer.py`, `img.save` should explicitly pass `format=img.format`.

- [ ] **Step 3: Ensure format preservation in `exif_writer.py`**

In `src/exif_tagger/exif_writer.py` inside `write_xptags` and `set_xptags`:
```python
        with PILImage.open(str(validated_path)) as img:
            exif_data = img.getexif()
            utf16le_value = tags_str.encode("utf-16-le") + b"\x00\x00"  # null-terminated
            exif_data[40094] = utf16le_value

            save_fmt = img.format or "HEIF" if validated_path.suffix.lower() in (".heic", ".heif") else None
            if save_fmt:
                img.save(str(validated_path), format=save_fmt, exif=exif_data.tobytes())
            else:
                img.save(str(validated_path), exif=exif_data.tobytes())
```

- [ ] **Step 4: Run tests to verify all pass**

Run: `.venv/bin/pytest tests/test_heic_support.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/exif_tagger/exif_writer.py tests/test_heic_support.py
git commit -m "feat: handle HEIC format explicitly when writing EXIF XPTags"
```

---

### Task 3: On-the-Fly HEIC JPEG Conversion in Web Gallery Endpoints

**Files:**
- Modify: `src/exif_tagger/server.py:601-668`
- Test: `tests/test_heic_support.py`

**Interfaces:**
- Consumes: `/api/gallery/image/file` and `/api/gallery/image/{image_id}/file`
- Produces: `Response(content=jpeg_bytes, media_type="image/jpeg")` for `.heic` and `.heif` files

- [ ] **Step 1: Write the failing tests for gallery endpoints serving HEIC files**

Append to `tests/test_heic_support.py`:
```python
import io
from fastapi.testclient import TestClient
from exif_tagger.server import app


def test_heic_gallery_image_file_conversion(tmp_path, monkeypatch):
    test_heic = tmp_path / "test_sample.heic"
    img = Image.new("RGB", (80, 80), color="green")
    img.save(test_heic, format="HEIF")

    client = TestClient(app)

    # Mock config root_directory
    class DummyConfig:
        root_directory = str(tmp_path)

    monkeypatch.setattr("exif_tagger.server.load_config", lambda path: DummyConfig())

    res = client.get(f"/api/gallery/image/file?path={test_heic.name}")
    assert res.status_code == 200
    assert res.headers["content-type"] == "image/jpeg"

    # Verify returned bytes form a valid JPEG image
    output_img = Image.open(io.BytesIO(res.content))
    assert output_img.format == "JPEG"
    assert output_img.size == (80, 80)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_heic_support.py::test_heic_gallery_image_file_conversion -v`  
Expected: FAIL (content-type is `image/heic` instead of `image/jpeg` or unrenderable by standard image readers)

- [ ] **Step 3: Implement HEIC to JPEG conversion in `server.py`**

In `src/exif_tagger/server.py`:
Import `Response` and `io` if not already present:
```python
import io
from fastapi import Response
from PIL import Image
```

Update `api_get_gallery_image_file_by_path` (line 621) and `api_get_gallery_image_file` (line 666):
```python
    if resolved_path.suffix.lower() in (".heic", ".heif"):
        with Image.open(resolved_path) as img:
            if img.mode != "RGB":
                img = img.convert("RGB")
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=85)
            return Response(content=buf.getvalue(), media_type="image/jpeg")

    return FileResponse(resolved_path)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_heic_support.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/exif_tagger/server.py tests/test_heic_support.py
git commit -m "feat: convert HEIC images to JPEG on-the-fly in gallery endpoints"
```
