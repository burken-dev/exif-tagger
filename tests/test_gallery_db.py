"""Tests for gallery database indexing and tag manipulation (exif_tagger.db)."""

import pytest
from PIL import Image as PILImage

from exif_tagger.db import (
    batch_update_tags,
    get_all_tags,
    get_gallery_images,
    get_image_by_id,
    init_db,
    remove_tag_globally,
    sync_gallery_index,
    update_image_tags_in_db_and_exif,
)
from exif_tagger.exif_writer import set_xptags


@pytest.fixture
def test_db_path(tmp_path):
    """Fixture providing a temporary SQLite database file path."""
    return tmp_path / "test_gallery.db"


@pytest.fixture
def image_gallery_dir(tmp_path):
    """Fixture creating a temporary directory populated with test images."""
    gallery_dir = tmp_path / "gallery"
    gallery_dir.mkdir()

    # Create image 1 with EXIF tags: landscape, nature
    img1_path = gallery_dir / "landscape1.jpg"
    img1 = PILImage.new("RGB", (100, 100), color="blue")
    img1.save(img1_path)
    set_xptags(img1_path, ["landscape", "nature"])

    # Create image 2 with EXIF tags: portrait, nature
    img2_path = gallery_dir / "portrait1.jpg"
    img2 = PILImage.new("RGB", (100, 100), color="red")
    img2.save(img2_path)
    set_xptags(img2_path, ["portrait", "nature"])

    # Create subfolder image with EXIF tag: architecture
    sub_dir = gallery_dir / "nested"
    sub_dir.mkdir()
    img3_path = sub_dir / "building1.jpg"
    img3 = PILImage.new("RGB", (100, 100), color="green")
    img3.save(img3_path)
    set_xptags(img3_path, ["architecture"])

    return gallery_dir, [img1_path, img2_path, img3_path]


class TestGalleryDatabase:
    def test_init_db(self, test_db_path):
        init_db(test_db_path)
        assert test_db_path.exists()

    def test_sync_gallery_index(self, test_db_path, image_gallery_dir):
        gallery_dir, img_paths = image_gallery_dir

        stats = sync_gallery_index(gallery_dir, db_path=test_db_path)
        assert stats["total"] == 3
        assert stats["updated"] == 3

        tags = get_all_tags(test_db_path)
        assert set(tags) == {"architecture", "landscape", "nature", "portrait"}

    def test_get_gallery_images_all(self, test_db_path, image_gallery_dir):
        gallery_dir, _ = image_gallery_dir
        sync_gallery_index(gallery_dir, db_path=test_db_path)

        images, total = get_gallery_images(db_path=test_db_path, offset=0, limit=10)
        assert total == 3
        assert len(images) == 3

    def test_get_gallery_images_tag_filter(self, test_db_path, image_gallery_dir):
        gallery_dir, _ = image_gallery_dir
        sync_gallery_index(gallery_dir, db_path=test_db_path)

        # Filter images with "landscape"
        images, total = get_gallery_images(db_path=test_db_path, tags=["landscape"])
        assert total == 1
        assert images[0]["filename"] == "landscape1.jpg"

        # Filter images with "nature" (should return landscape1 and portrait1)
        images_nature, total_nature = get_gallery_images(db_path=test_db_path, tags=["nature"])
        assert total_nature == 2

    def test_get_gallery_images_search(self, test_db_path, image_gallery_dir):
        gallery_dir, _ = image_gallery_dir
        sync_gallery_index(gallery_dir, db_path=test_db_path)

        images, total = get_gallery_images(db_path=test_db_path, search="building")
        assert total == 1
        assert images[0]["filename"] == "building1.jpg"

    def test_update_image_tags(self, test_db_path, image_gallery_dir):
        gallery_dir, _ = image_gallery_dir
        sync_gallery_index(gallery_dir, db_path=test_db_path)

        images, _ = get_gallery_images(db_path=test_db_path, limit=1)
        img_id = images[0]["id"]

        success = update_image_tags_in_db_and_exif(img_id, ["edited", "newtag"], db_path=test_db_path)
        assert success is True

        img_data = get_image_by_id(img_id, db_path=test_db_path)
        assert set(img_data["tags"]) == {"edited", "newtag"}

    def test_batch_update_tags(self, test_db_path, image_gallery_dir):
        gallery_dir, _ = image_gallery_dir
        sync_gallery_index(gallery_dir, db_path=test_db_path)

        images, _ = get_gallery_images(db_path=test_db_path)
        img_ids = [img["id"] for img in images]

        modified = batch_update_tags(
            image_ids=img_ids,
            add_tags=["batchtag"],
            remove_tags=["nature"],
            db_path=test_db_path,
        )
        assert modified > 0

        tags = get_all_tags(test_db_path)
        assert "batchtag" in tags
        assert "nature" not in tags

    def test_remove_tag_globally(self, test_db_path, image_gallery_dir):
        gallery_dir, _ = image_gallery_dir
        sync_gallery_index(gallery_dir, db_path=test_db_path)

        assert "nature" in get_all_tags(test_db_path)

        modified = remove_tag_globally("nature", db_path=test_db_path)
        assert modified == 2

        tags_after = get_all_tags(test_db_path)
        assert "nature" not in tags_after

    def test_update_image_in_db_from_file(self, test_db_path, tmp_path):
        from exif_tagger.db import update_image_in_db_from_file

        img_path = tmp_path / "single.jpg"
        img = PILImage.new("RGB", (100, 100), color="yellow")
        img.save(img_path)
        set_xptags(img_path, ["tag1", "tag2"])

        update_image_in_db_from_file(img_path, root_directory=tmp_path, db_path=test_db_path)

        images, total = get_gallery_images(db_path=test_db_path)
        assert total == 1
        assert images[0]["filename"] == "single.jpg"
        assert set(images[0]["tags"]) == {"tag1", "tag2"}


def test_get_db_path_data_dir(monkeypatch, tmp_path):
    from exif_tagger.db import get_db_path

    monkeypatch.delenv("EXIFTAGGER_DB_FILE", raising=False)
    monkeypatch.setenv("EXIFTAGGER_DATA_DIR", str(tmp_path))
    assert get_db_path() == tmp_path / "gallery.db"


def test_get_db_path_db_file_override(monkeypatch, tmp_path):
    from exif_tagger.db import get_db_path

    db_custom = tmp_path / "custom.db"
    monkeypatch.setenv("EXIFTAGGER_DB_FILE", str(db_custom))
    monkeypatch.setenv("EXIFTAGGER_DATA_DIR", str(tmp_path / "ignored"))
    assert get_db_path() == db_custom


def test_get_gallery_images_filesystem_unindexed(tmp_path):
    from exif_tagger.db import get_gallery_images, init_db, sync_single_image

    db_path = tmp_path / "test.db"
    init_db(db_path)

    # Create dummy images on disk
    img1 = tmp_path / "a.jpg"
    img2 = tmp_path / "sub" / "b.png"
    img2.parent.mkdir(parents=True, exist_ok=True)
    img1.write_bytes(b"dummy")
    img2.write_bytes(b"dummy")

    # Call get_gallery_images without tags (should list both from disk even though DB is empty)
    images, total = get_gallery_images(db_path=db_path, root_directory=tmp_path)
    assert total == 2
    assert images[0]["filename"] == "a.jpg"
    assert images[0]["indexed"] is False
    assert images[0]["id"] is None
    assert images[1]["relative_path"] == "sub/b.png"

    # Test sync_single_image
    synced = sync_single_image("a.jpg", db_path=db_path, root_directory=tmp_path)
    assert synced["indexed"] is True
    assert synced["id"] is not None

    # Query again: a.jpg should now be indexed, sub/b.png unindexed
    images, total = get_gallery_images(db_path=db_path, root_directory=tmp_path)
    assert images[0]["indexed"] is True
    assert images[1]["indexed"] is False


def test_get_gallery_images_untagged_folder_and_search(tmp_path):
    from exif_tagger.db import get_gallery_images, init_db

    db_path = tmp_path / "test.db"
    init_db(db_path)

    (tmp_path / "root.jpg").write_bytes(b"dummy")
    sub1 = tmp_path / "folder1"
    sub1.mkdir()
    (sub1 / "img1.jpg").write_bytes(b"dummy")
    (sub1 / "photo2.png").write_bytes(b"dummy")

    sub2 = tmp_path / "folder2"
    sub2.mkdir()
    (sub2 / "other.jpg").write_bytes(b"dummy")

    # Folder filter test
    images, total = get_gallery_images(db_path=db_path, folder="folder1", root_directory=tmp_path)
    assert total == 2
    filenames = [img["filename"] for img in images]
    assert filenames == ["img1.jpg", "photo2.png"]

    # Search filter test (glob)
    images_glob, total_glob = get_gallery_images(db_path=db_path, search="*.png", root_directory=tmp_path)
    assert total_glob == 1
    assert images_glob[0]["filename"] == "photo2.png"

    # Search filter test (substring)
    images_sub, total_sub = get_gallery_images(db_path=db_path, search="img1", root_directory=tmp_path)
    assert total_sub == 1
    assert images_sub[0]["filename"] == "img1.jpg"


def test_sync_single_image_not_found(tmp_path):
    from exif_tagger.db import init_db, sync_single_image

    db_path = tmp_path / "test.db"
    init_db(db_path)

    with pytest.raises(FileNotFoundError):
        sync_single_image("nonexistent.jpg", db_path=db_path, root_directory=tmp_path)
