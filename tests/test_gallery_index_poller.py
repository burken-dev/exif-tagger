"""Tests for reconcile_gallery_index — the discovery-layer walker."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from exif_tagger.db import get_connection, init_db, reconcile_gallery_index  # noqa: F401


def make_img(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (20, 20), color="red").save(path, format="JPEG")
    return path


def db_rows(db_path: Path) -> dict[str, dict]:
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            "SELECT id, file_path, filename, relative_path, last_modified, exif_mtime FROM images"
        ).fetchall()
        return {r["relative_path"]: dict(r) for r in rows}
    finally:
        conn.close()


def test_reconcile_adds_new_files(tmp_path):
    db = tmp_path / "g.db"
    root = tmp_path / "gallery"
    root.mkdir()
    make_img(root / "a.jpg")
    make_img(root / "sub" / "b.png")

    stats = reconcile_gallery_index(root, db_path=db)
    rows = db_rows(db)

    assert stats["total"] == 2
    assert stats["added"] == 2
    assert set(rows) == {"a.jpg", "sub/b.png"}
    assert rows["a.jpg"]["exif_mtime"] is None  # discovery never sets it


def test_reconcile_second_run_is_noop(tmp_path):
    db = tmp_path / "g.db"
    root = tmp_path / "gallery"
    root.mkdir()
    make_img(root / "a.jpg")

    reconcile_gallery_index(root, db_path=db)
    mtime_before = db_rows(db)["a.jpg"]["last_modified"]
    stats = reconcile_gallery_index(root, db_path=db)

    assert stats == {"total": 1, "added": 0, "removed": 0, "updated": 0}
    assert db_rows(db)["a.jpg"]["last_modified"] == mtime_before


def test_reconcile_detects_deletion(tmp_path):
    db = tmp_path / "g.db"
    root = tmp_path / "gallery"
    root.mkdir()
    make_img(root / "a.jpg")
    make_img(root / "b.jpg")
    reconcile_gallery_index(root, db_path=db)

    (root / "b.jpg").unlink()
    stats = reconcile_gallery_index(root, db_path=db)

    assert stats["removed"] == 1
    assert set(db_rows(db)) == {"a.jpg"}


def test_reconcile_rename_preserves_id_and_tags(tmp_path):
    from exif_tagger.db import get_connection

    db = tmp_path / "g.db"
    root = tmp_path / "gallery"
    root.mkdir()
    img = make_img(root / "old.jpg")
    reconcile_gallery_index(root, db_path=db)
    old_row = db_rows(db)["old.jpg"]

    conn = get_connection(db)
    conn.execute(
        "INSERT INTO image_tags (image_id, tag_name, source) VALUES (?, 'manual', 'manual_exif')", (old_row["id"],)
    )
    conn.commit()
    conn.close()

    img.rename(root / "new.jpg")
    stats = reconcile_gallery_index(root, db_path=db)
    rows = db_rows(db)

    assert stats["added"] == 0 and stats["removed"] == 0
    assert "new.jpg" in rows and "old.jpg" not in rows
    assert rows["new.jpg"]["id"] == old_row["id"]  # id preserved -> tags kept

    conn = get_connection(db)
    tags = conn.execute("SELECT tag_name FROM image_tags WHERE image_id = ?", (old_row["id"],)).fetchall()
    conn.close()
    assert [t["tag_name"] for t in tags] == ["manual"]


def test_reconcile_new_nested_dir_discovered_after_parent_prune(tmp_path):
    db = tmp_path / "g.db"
    root = tmp_path / "gallery"
    root.mkdir()
    make_img(root / "sub" / "a.jpg")
    reconcile_gallery_index(root, db_path=db)

    # Add a file inside a NEW deeper dir under the (already-indexed) sub dir.
    make_img(root / "sub" / "deeper" / "b.jpg")
    stats = reconcile_gallery_index(root, db_path=db)

    assert stats["added"] == 1
    assert "sub/deeper/b.jpg" in db_rows(db)


def test_reconcile_removed_folder_purges_subtree(tmp_path):
    db = tmp_path / "g.db"
    root = tmp_path / "gallery"
    root.mkdir()
    make_img(root / "sub" / "a.jpg")
    make_img(root / "sub" / "x" / "b.png")
    reconcile_gallery_index(root, db_path=db)

    import shutil

    shutil.rmtree(root / "sub")
    stats = reconcile_gallery_index(root, db_path=db)

    assert stats["removed"] == 2
    assert db_rows(db) == {}
    conn = get_connection(db)
    left = conn.execute("SELECT COUNT(*) AS c FROM dir_mtimes").fetchone()["c"]
    conn.close()
    assert left == 1  # only root's baseline remains; sub + sub/x baselines purged


def test_reconcile_exclude_patterns(tmp_path):
    db = tmp_path / "g.db"
    root = tmp_path / "gallery"
    root.mkdir()
    make_img(root / "keep.jpg")
    make_img(root / "skip.jpg")

    reconcile_gallery_index(root, db_path=db, exclude_patterns=["skip"])
    assert set(db_rows(db)) == {"keep.jpg"}


def test_reconcile_full_rebuild_matches_incremental(tmp_path):
    db = tmp_path / "g.db"
    root = tmp_path / "gallery"
    root.mkdir()
    make_img(root / "a.jpg")
    make_img(root / "sub" / "b.png")
    reconcile_gallery_index(root, db_path=db)
    stats_full = reconcile_gallery_index(root, db_path=db, full=True)

    assert stats_full["total"] == 2
    assert stats_full["added"] == 0 and stats_full["removed"] == 0
    assert set(db_rows(db)) == {"a.jpg", "sub/b.png"}


def test_reconcile_symlink_dir_alias_no_duplicate(tmp_path):
    import os

    from exif_tagger.db import get_connection, reconcile_gallery_index

    db = tmp_path / "g.db"
    root = tmp_path / "gallery"
    real = root / "real"
    real.mkdir(parents=True)
    make_img(real / "a.jpg")
    os.symlink(real, root / "alias", target_is_directory=True)

    for _ in range(2):
        stats = reconcile_gallery_index(root, db_path=db)
        assert stats["total"] == 1

    conn = get_connection(db)
    rows = conn.execute("SELECT file_path FROM images").fetchall()
    conn.close()
    assert len({r["file_path"] for r in rows}) == 1  # alias and real do not double-index


def test_reconcile_file_replaced_by_dir_removes_ghost(tmp_path):
    from exif_tagger.db import get_connection, reconcile_gallery_index

    db = tmp_path / "g.db"
    root = tmp_path / "gallery"
    root.mkdir()
    make_img(root / "item.jpg")
    reconcile_gallery_index(root, db_path=db)
    assert reconcile_gallery_index(root, db_path=db)["total"] == 1

    (root / "item.jpg").unlink()
    (root / "item.jpg").mkdir()  # same name is now a directory
    make_img(root / "item.jpg" / "a.jpg")
    reconcile_gallery_index(root, db_path=db)

    conn = get_connection(db)
    paths = {r["relative_path"] for r in conn.execute("SELECT relative_path FROM images").fetchall()}
    conn.close()
    assert paths == {"item.jpg/a.jpg"}
