from PIL import Image
import exif_tagger  # noqa: F401


def test_heic_opener_is_registered():
    registered = Image.registered_extensions()
    assert ".heic" in registered, ".heic format must be registered in Pillow"
    assert ".heif" in registered, ".heif format must be registered in Pillow"
