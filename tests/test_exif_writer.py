"""Tests for the EXIF XPTags writer module (via PIL/Pillow)."""

from __future__ import annotations

from pathlib import Path

import pytest

from exif_tagger.exif_writer import (
    get_existing_xptags,
    set_xptags,
)


def _make_jpeg_with_exif(tmp_path: Path, xptags: str | None = None) -> Path:
    """Create a real JPEG file, optionally with XPTags set."""
    from PIL import Image as PILImage

    img_path = tmp_path / "photo.jpg"
    with PILImage.new("RGB", (10, 10), color=(255, 0, 0)) as pil_img:
        if xptags is not None:
            tags_str = ";".join(sorted(xptags.split(";")))
            utf16le_value = tags_str.encode("utf-16-le") + b"\x00\x00"
            exif_data = pil_img.getexif()
            exif_data[40094] = utf16le_value
            pil_img.save(str(img_path), format="JPEG", exif=exif_data.tobytes())
        else:
            pil_img.save(str(img_path), format="JPEG")
    return img_path


class TestGetExistingXptags:
    """Test reading XPTags from real image files via PIL."""

    def test_new_image_has_no_xptags(self, tmp_path):
        """A newly created image should have no existing tags."""
        img = _make_jpeg_with_exif(tmp_path)
        result = get_existing_xptags(img)
        assert result == set()

    def test_image_with_tags(self, tmp_path):
        """Image that already has XPTags should return them."""
        img = _make_jpeg_with_exif(tmp_path, xptags="landscape;portrait")
        result = get_existing_xptags(img)
        assert result == {"landscape", "portrait"}

    def test_single_tag(self, tmp_path):
        """Image with a single tag should return it."""
        img = _make_jpeg_with_exif(tmp_path, xptags="sunset")
        result = get_existing_xptags(img)
        assert result == {"sunset"}

    def test_empty_tags_string(self, tmp_path):
        """Image with an empty XPTags string should return empty set."""
        img = _make_jpeg_with_exif(tmp_path, xptags="")
        result = get_existing_xptags(img)
        assert result == set()

    def test_nonexistent_file_returns_empty(self):
        """Non-existent file should return empty set (graceful degradation)."""
        result = get_existing_xptags(Path("/tmp/nonexistent_abc123.jpg"))
        assert result == set()


class TestSetXptags:
    """Test writing XPTags to image files via PIL."""

    def test_write_single_tag(self, tmp_path):
        """Writing one tag should persist and be readable back."""
        img = _make_jpeg_with_exif(tmp_path)

        modified = set_xptags(img, ["landscape"])

        assert modified is True
        result = get_existing_xptags(img)
        assert result == {"landscape"}

    def test_set_overwrites_existing(self, tmp_path):
        """set_xptags writes exactly the given set, replacing previous tags."""
        img = _make_jpeg_with_exif(tmp_path)

        set_xptags(img, ["landscape"])
        set_xptags(img, ["portrait"])

        result = get_existing_xptags(img)
        assert result == {"portrait"}

    def test_rewrite_is_idempotent(self, tmp_path):
        """Rewriting the same tag set should still succeed."""
        img = _make_jpeg_with_exif(tmp_path)

        assert set_xptags(img, ["landscape"]) is True
        assert set_xptags(img, ["landscape"]) is True

    def test_empty_tag_list_clears(self, tmp_path):
        """Passing an empty tag list should clear existing XPTags."""
        img = _make_jpeg_with_exif(tmp_path, xptags="landscape")
        modified = set_xptags(img, [])
        assert modified is True
        assert get_existing_xptags(img) == set()

    def test_case_insensitive(self, tmp_path):
        """Writing a tag with uppercase should be stored lowercase."""
        img = _make_jpeg_with_exif(tmp_path)

        set_xptags(img, ["LANDSCAPE"])
        result = get_existing_xptags(img)
        assert "landscape" in result


class TestSetXptagsIntegrity:
    """Test that writes preserve image integrity."""

    def test_write_preserves_image(self, tmp_path):
        """After writing XPTags the image should still be valid."""
        img = _make_jpeg_with_exif(tmp_path)

        set_xptags(img, ["landscape"])

        from PIL import Image as PILImage

        with PILImage.open(str(img)) as pil_img:
            pil_img.verify()


class TestVerifyImageIntegrity:
    """Test the post-write integrity check helper."""

    def test_valid_image_passes(self, tmp_path):
        """A valid JPEG should pass verification."""
        from PIL import Image as PILImage

        img = tmp_path / "valid.jpg"
        with PILImage.new("RGB", (1, 1), color=(255, 0, 0)) as pil_img:
            pil_img.save(str(img), format="JPEG")

        from exif_tagger.exif_writer import _verify_image_integrity

        # Should not raise
        _verify_image_integrity(img.resolve())

    def test_non_image_raises(self, tmp_path):
        """A random file should fail PIL verification."""
        img = tmp_path / "not_an_image.txt"
        img.write_text("this is not an image")

        from exif_tagger.exif_writer import _verify_image_integrity

        with pytest.raises(Exception):  # PIL raises on corrupt/unreadable images
            _verify_image_integrity(img.resolve())


class TestPathValidation:
    """Test path validation security checks."""

    def test_graceful_degradation_no_base_dir(self):
        """Without base_dir, non-existent paths return empty set (graceful degradation)."""
        result = get_existing_xptags(Path("/tmp/nonexistent_xyz.jpg"))
        assert result == set()

    def test_write_returns_false_on_validation_error(self, tmp_path):
        """set_xptags should return False when path validation fails."""
        fake_path = tmp_path / "does_not_exist.jpg"
        modified = set_xptags(fake_path, base_dir=tmp_path, tags=["tag"])
        assert modified is False


class TestSetXptagsErrorHandling:
    """Test error handling when writes fail."""

    def test_write_to_unreadable_file(self, tmp_path):
        """Writing to a file that can't be opened should raise RuntimeError."""
        bad_file = tmp_path / "not_a_real_image.jpg"
        bad_file.write_bytes(b"\x00\x01\x02\x03")

        with pytest.raises(RuntimeError, match="Failed to set XPTags"):
            set_xptags(bad_file, ["landscape"])
