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

