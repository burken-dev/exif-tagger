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

    def test_init_db_creates_dir_mtimes_and_exif_mtime(self, test_db_path):
        from exif_tagger.db import get_connection, init_db

        init_db(test_db_path)
        conn = get_connection(test_db_path)
        try:
            tables = {r["name"] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            assert "dir_mtimes" in tables
            cols = {r["name"] for r in conn.execute("PRAGMA table_info(images)")}
            assert "exif_mtime" in cols
        finally:
            conn.close()

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
    """Every file on disk is discovered (with an id) once the index is reconciled."""
    from exif_tagger.db import get_gallery_images, init_db, reconcile_gallery_index

    db_path = tmp_path / "test.db"
    init_db(db_path)

    img1 = tmp_path / "a.jpg"
    img2 = tmp_path / "sub" / "b.png"
    img2.parent.mkdir(parents=True, exist_ok=True)
    img1.write_bytes(b"dummy")
    img2.write_bytes(b"dummy")

    reconcile_gallery_index(tmp_path, db_path=db_path)
    images, total = get_gallery_images(db_path=db_path, root_directory=tmp_path)
    assert total == 2
    assert all(img["id"] is not None for img in images)
    assert all(img["indexed"] is True for img in images)
    assert images[0]["filename"] == "a.jpg"
    assert images[1]["relative_path"] == "sub/b.png"


def test_get_gallery_images_untagged_folder_and_search(tmp_path):
    from exif_tagger.db import get_gallery_images, init_db, reconcile_gallery_index

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

    reconcile_gallery_index(tmp_path, db_path=db_path)

    images, total = get_gallery_images(db_path=db_path, folder="folder1", root_directory=tmp_path)
    assert total == 2
    assert [img["filename"] for img in images] == ["img1.jpg", "photo2.png"]

    images_glob, total_glob = get_gallery_images(db_path=db_path, search="*.png", root_directory=tmp_path)
    assert total_glob == 1
    assert images_glob[0]["filename"] == "photo2.png"

    images_sub, total_sub = get_gallery_images(db_path=db_path, search="img1", root_directory=tmp_path)
    assert total_sub == 1
    assert images_sub[0]["filename"] == "img1.jpg"


def test_sync_single_image_not_found(tmp_path):
    from exif_tagger.db import init_db, sync_single_image

    db_path = tmp_path / "test.db"
    init_db(db_path)

    with pytest.raises(FileNotFoundError):
        sync_single_image("nonexistent.jpg", db_path=db_path, root_directory=tmp_path)


def test_sync_gallery_index_does_not_wipe_model_tags_or_suppress_them(tmp_path):
    from datetime import UTC, datetime

    from exif_tagger.db import get_connection, get_gallery_images, init_db, sync_gallery_index

    db_path = tmp_path / "test.db"
    init_db(db_path)

    gallery_dir = tmp_path / "gallery"
    gallery_dir.mkdir()
    img_path = gallery_dir / "photo.jpg"
    img = PILImage.new("RGB", (50, 50), color="blue")
    img.save(img_path)
    set_xptags(img_path, ["nature"])

    now_iso = datetime.now(UTC).isoformat()
    conn = get_connection(db_path)
    cursor = conn.execute(
        "INSERT INTO images (file_path, filename, relative_path, last_modified, indexed_at) VALUES (?, ?, ?, ?, ?)",
        (str(img_path.resolve()), img_path.name, "photo.jpg", 0.0, now_iso),
    )
    img_id = cursor.lastrowid
    conn.execute(
        "INSERT INTO image_tags (image_id, tag_name, source, added_at) VALUES (?, ?, 'model', ?)",
        (img_id, "nature", now_iso),
    )
    conn.commit()
    conn.close()

    # Re-sync gallery index
    sync_gallery_index(root_directory=gallery_dir, db_path=db_path)

    # Verify model tag was NOT deleted and NOT inserted into user_suppressions
    conn = get_connection(db_path)
    tags = conn.execute("SELECT tag_name, source FROM image_tags WHERE image_id = ?", (img_id,)).fetchall()
    suppressions = conn.execute("SELECT * FROM user_suppressions WHERE image_id = ?", (img_id,)).fetchall()
    conn.close()

    assert len(tags) == 1
    assert tags[0]["tag_name"] == "nature"
    assert len(suppressions) == 0

    images, total = get_gallery_images(db_path=db_path, root_directory=gallery_dir)
    assert total == 1
    assert "nature" in images[0]["tags"]


def test_sync_gallery_index_with_relative_db_paths(tmp_path):
    from datetime import UTC, datetime

    from exif_tagger.db import get_connection, init_db, sync_gallery_index

    db_path = tmp_path / "test.db"
    init_db(db_path)

    gallery_dir = tmp_path / "gallery"
    gallery_dir.mkdir()
    img_path = gallery_dir / "photo.jpg"
    img = PILImage.new("RGB", (50, 50), color="blue")
    img.save(img_path)

    now_iso = datetime.now(UTC).isoformat()
    conn = get_connection(db_path)
    cursor = conn.execute(
        "INSERT INTO images (file_path, filename, relative_path, last_modified, indexed_at) VALUES (?, ?, ?, ?, ?)",
        ("photo.jpg", img_path.name, "photo.jpg", img_path.stat().st_mtime, now_iso),
    )
    original_id = cursor.lastrowid
    conn.commit()
    conn.close()

    # Sync gallery index
    stats = sync_gallery_index(root_directory=gallery_dir, db_path=db_path)

    # Verify photo record was updated, not deleted and recreated with a new ID
    conn = get_connection(db_path)
    rows = conn.execute("SELECT id, file_path FROM images").fetchall()
    conn.close()

    assert len(rows) == 1
    assert rows[0]["id"] == original_id, f"Expected id {original_id}, got {rows[0]['id']}"
    assert stats["deleted"] == 0


def test_sync_extracts_exif_when_exif_mtime_null(tmp_path):
    """A row inserted by the poller (exif_mtime NULL) still gets EXIF tags."""
    import os

    from exif_tagger.db import get_connection, init_db, reconcile_gallery_index, sync_gallery_index

    db_path = tmp_path / "test.db"
    init_db(db_path)
    gallery_dir = tmp_path / "gallery"
    gallery_dir.mkdir()
    img = gallery_dir / "photo.jpg"
    img_ = PILImage.new("RGB", (50, 50), color="blue")
    img_.save(img)
    set_xptags(img, ["nature"])

    # Discovery-only pass: inserts the row, must NOT read EXIF.
    reconcile_gallery_index(gallery_dir, db_path=db_path)
    conn = get_connection(db_path)
    try:
        row = conn.execute("SELECT id, exif_mtime FROM images").fetchone()
        assert row["exif_mtime"] is None
        img_id = row["id"]
    finally:
        conn.close()

    sync_gallery_index(gallery_dir, db_path=db_path)

    conn = get_connection(db_path)
    try:
        tags = [r["tag_name"] for r in conn.execute(
            "SELECT tag_name FROM image_tags WHERE image_id = ?", (img_id,))]
        mtime = conn.execute("SELECT exif_mtime FROM images WHERE id = ?", (img_id,)).fetchone()["exif_mtime"]
    finally:
        conn.close()

    assert tags == ["nature"]
    assert abs(mtime - os.stat(img).st_mtime) < 0.001


def test_sync_second_run_is_skip_no_re_extract(tmp_path):
    """A second sync with unchanged mtime must not re-read EXIF or rewrite tags."""
    from exif_tagger.db import get_connection, init_db, sync_gallery_index

    db_path = tmp_path / "test.db"
    init_db(db_path)
    gallery_dir = tmp_path / "gallery"
    gallery_dir.mkdir()
    img = gallery_dir / "photo.jpg"
    PILImage.new("RGB", (50, 50), color="blue").save(img)
    set_xptags(img, ["nature"])

    stats1 = sync_gallery_index(gallery_dir, db_path=db_path)
    # Simulate a manual tag the user added in the UI only (not in EXIF).
    conn = get_connection(db_path)
    img_id = conn.execute("SELECT id FROM images").fetchone()["id"]
    conn.execute(
        "INSERT INTO image_tags (image_id, tag_name, source) VALUES (?, 'useronly', 'manual_ui')",
        (img_id,),
    )
    conn.commit()
    conn.close()

    stats2 = sync_gallery_index(gallery_dir, db_path=db_path)
    assert stats2["updated"] == 0

    conn = get_connection(db_path)
    tags = {r["tag_name"] for r in conn.execute(
        "SELECT tag_name FROM image_tags WHERE image_id = ?", (img_id,))}
    conn.close()
    assert tags == {"nature", "useronly"}  # nothing re-read, nothing wiped


def test_sync_re_extracts_after_file_modification(tmp_path):
    """Changing the file mtime triggers EXIF re-extraction."""
    import os

    from exif_tagger.db import get_connection, init_db, sync_gallery_index

    db_path = tmp_path / "test.db"
    init_db(db_path)
    gallery_dir = tmp_path / "gallery"
    gallery_dir.mkdir()
    img = gallery_dir / "photo.jpg"
    PILImage.new("RGB", (50, 50), color="blue").save(img)
    set_xptags(img, ["nature"])

    sync_gallery_index(gallery_dir, db_path=db_path)

    set_xptags(img, ["architecture"])
    new_mtime = img.stat().st_mtime + 5.0
    os.utime(img, (new_mtime, new_mtime))

    stats = sync_gallery_index(gallery_dir, db_path=db_path)
    assert stats["updated"] == 1

    conn = get_connection(db_path)
    tags = {r["tag_name"] for r in conn.execute("SELECT tag_name FROM image_tags").fetchall()}
    conn.close()
    assert tags == {"architecture"}


def test_update_image_in_db_from_file_gates_on_exif_mtime(tmp_path):
    """update_image_in_db_from_file skips EXIF rewrite when exif_mtime matches."""
    from exif_tagger.db import get_connection, init_db, update_image_in_db_from_file

    db_path = tmp_path / "test.db"
    init_db(db_path)
    img = tmp_path / "single.jpg"
    PILImage.new("RGB", (50, 50), color="yellow").save(img)
    set_xptags(img, ["tag1"])

    update_image_in_db_from_file(img, root_directory=tmp_path, db_path=db_path)
    conn = get_connection(db_path)
    img_id = conn.execute("SELECT id FROM images").fetchone()["id"]
    conn.execute(
        "INSERT INTO image_tags (image_id, tag_name, source) VALUES (?, 'useronly', 'manual_ui')",
        (img_id,),
    )
    conn.commit()
    conn.close()

    update_image_in_db_from_file(img, root_directory=tmp_path, db_path=db_path)

    conn = get_connection(db_path)
    tags = {r["tag_name"] for r in conn.execute(
        "SELECT tag_name FROM image_tags WHERE image_id = ?", (img_id,))}
    conn.close()
    assert tags == {"tag1", "useronly"}


def test_update_image_tags_sets_exif_mtime(tmp_path):
    import os

    from exif_tagger.db import get_connection, init_db, sync_gallery_index, update_image_tags_in_db_and_exif

    db_path = tmp_path / "test.db"
    init_db(db_path)
    gallery_dir = tmp_path / "gallery"
    gallery_dir.mkdir()
    img = gallery_dir / "photo.jpg"
    PILImage.new("RGB", (50, 50), color="blue").save(img)
    set_xptags(img, [])

    sync_gallery_index(gallery_dir, db_path=db_path)
    conn = get_connection(db_path)
    img_id = conn.execute("SELECT id FROM images").fetchone()["id"]
    conn.close()

    assert update_image_tags_in_db_and_exif(img_id, ["edited"], db_path=db_path) is True

    conn = get_connection(db_path)
    row = conn.execute("SELECT last_modified, exif_mtime FROM images WHERE id = ?", (img_id,)).fetchone()
    conn.close()
    assert abs(row["exif_mtime"] - row["last_modified"]) < 0.001
    assert abs(row["last_modified"] - os.stat(img).st_mtime) < 0.001


def test_get_gallery_images_is_db_only(monkeypatch, tmp_path):
    """Reads must never touch the filesystem."""
    from exif_tagger.db import get_gallery_images, init_db, reconcile_gallery_index

    db_path = tmp_path / "test.db"
    init_db(db_path)
    root = tmp_path / "gallery"
    root.mkdir()
    (root / "a.jpg").write_bytes(b"x")
    reconcile_gallery_index(root, db_path=db_path)

    def boom(*args, **kwargs):
        raise AssertionError("filesystem must not be scanned during reads")

    monkeypatch.setattr("exif_tagger.db.scan_images", boom)
    images, total = get_gallery_images(db_path=db_path)
    assert total == 1


def test_get_gallery_images_folder_special_chars(tmp_path):
    from exif_tagger.db import get_gallery_images, init_db, reconcile_gallery_index

    db_path = tmp_path / "test.db"
    init_db(db_path)
    root = tmp_path / "gallery"
    root.mkdir()
    special = root / "50%_photos"
    special.mkdir()
    (special / "one.jpg").write_bytes(b"x")
    reconcile_gallery_index(root, db_path=db_path)

    images, total = get_gallery_images(db_path=db_path, folder="50%_photos")
    assert total == 1
    assert images[0]["filename"] == "one.jpg"


def test_get_gallery_images_tag_and_semantics(tmp_path):
    """Selecting multiple tags requires ALL of them (AND), not any."""
    from exif_tagger.db import get_gallery_images, init_db, sync_gallery_index

    db_path = tmp_path / "test.db"
    init_db(db_path)
    root = tmp_path / "gallery"
    root.mkdir()
    for name, tags in [("a.jpg", ["x", "y"]), ("b.jpg", ["x"]), ("c.jpg", ["y"])]:
        p = root / name
        PILImage.new("RGB", (20, 20)).save(p)
        set_xptags(p, tags)
    sync_gallery_index(root, db_path=db_path)

    images, total = get_gallery_images(db_path=db_path, tags=["x", "y"])
    assert total == 1
    assert images[0]["filename"] == "a.jpg"


def test_get_gallery_images_search_unicode_case(tmp_path):
    from exif_tagger.db import get_gallery_images, init_db, reconcile_gallery_index

    db_path = tmp_path / "test.db"
    init_db(db_path)
    root = tmp_path / "gallery"
    root.mkdir()
    (root / "Ångström.jpg").write_bytes(b"x")
    reconcile_gallery_index(root, db_path=db_path)

    images, total = get_gallery_images(db_path=db_path, search="ångström")
    assert total == 1
    images2, total2 = get_gallery_images(db_path=db_path, search="ÅNGSTRÖM")
    assert total2 == 1


def test_get_gallery_images_pagination(tmp_path):
    from exif_tagger.db import get_gallery_images, init_db, reconcile_gallery_index

    db_path = tmp_path / "test.db"
    init_db(db_path)
    root = tmp_path / "gallery"
    root.mkdir()
    for i in range(5):
        (root / f"img{i}.jpg").write_bytes(b"x")
    reconcile_gallery_index(root, db_path=db_path)

    page1, total = get_gallery_images(db_path=db_path, offset=0, limit=2)
    page2, _ = get_gallery_images(db_path=db_path, offset=2, limit=2)
    assert total == 5
    assert len(page1) == 2 and len(page2) == 2
    assert {img["id"] for img in page1}.isdisjoint({img["id"] for img in page2})
