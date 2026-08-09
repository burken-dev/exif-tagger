import tempfile
from pathlib import Path

from PIL import Image

import exif_tagger  # noqa: F401
from exif_tagger.ai_client import _image_to_base64
from exif_tagger.exif_writer import get_existing_xptags, write_xptags


def test_heic_opener_is_registered():
    registered = Image.registered_extensions()
    assert ".heic" in registered, ".heic format must be registered in Pillow"
    assert ".heif" in registered, ".heif format must be registered in Pillow"


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


def test_heic_gallery_image_file_conversion(tmp_path, monkeypatch):
    import io

    from fastapi.testclient import TestClient

    from exif_tagger.server import app

    test_heic = tmp_path / "test_sample.heic"
    img = Image.new("RGB", (80, 80), color="green")
    img.save(test_heic, format="HEIF")

    client = TestClient(app)

    class DummyConfig:
        root_directory = str(tmp_path)

    monkeypatch.setattr("exif_tagger.server.load_config", lambda path: DummyConfig())

    res = client.get(f"/api/gallery/image/file?path={test_heic.name}")
    assert res.status_code == 200
    assert res.headers["content-type"] == "image/jpeg"

    output_img = Image.open(io.BytesIO(res.content))
    assert output_img.format == "JPEG"
    assert output_img.size == (80, 80)


def test_heic_gallery_image_file_by_id_conversion(tmp_path, monkeypatch):
    import io

    from fastapi.testclient import TestClient

    from exif_tagger.server import app

    test_heic = tmp_path / "test_sample2.heic"
    img = Image.new("RGB", (60, 60), color="red")
    img.save(test_heic, format="HEIF")

    client = TestClient(app)

    monkeypatch.setattr("exif_tagger.server.get_image_by_id", lambda img_id: {"file_path": str(test_heic)})

    res = client.get("/api/gallery/image/42/file")
    assert res.status_code == 200
    assert res.headers["content-type"] == "image/jpeg"

    output_img = Image.open(io.BytesIO(res.content))
    assert output_img.format == "JPEG"
    assert output_img.size == (60, 60)


