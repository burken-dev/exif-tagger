"""Unit tests for robust database state engine, evaluation tracking, suppressions, and self-healing sync."""

from __future__ import annotations

from pathlib import Path

from exif_tagger.db import (
    evaluate_thresholds_locally,
    get_connection,
    get_unevaluated_candidates,
    init_db,
    record_tag_evaluation,
    record_user_suppression,
    sync_gallery_index,
)
from exif_tagger.models.schema import TagDefinition


def test_init_db_creates_new_tables(tmp_path: Path):
    db_file = tmp_path / "test_gallery.db"
    init_db(db_file)

    conn = get_connection(db_file)
    try:
        tables = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        assert "images" in tables
        assert "image_tags" in tables
        assert "tag_definitions" in tables
        assert "tag_evaluations" in tables
        assert "user_suppressions" in tables

        # Verify image_tags has source column
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(image_tags)").fetchall()}
        assert "source" in columns
        assert "added_at" in columns
    finally:
        conn.close()


def test_record_tag_evaluation_and_suppression(tmp_path: Path):
    db_file = tmp_path / "test_gallery.db"
    init_db(db_file)

    conn = get_connection(db_file)
    try:
        with conn:
            cursor = conn.execute(
                "INSERT INTO images (file_path, filename, relative_path, last_modified, indexed_at) "
                "VALUES ('/data/img1.jpg', 'img1.jpg', 'img1.jpg', 100.0, '2026-08-07T12:00:00Z')"
            )
            image_id = cursor.lastrowid
    finally:
        conn.close()

    # Record evaluation
    record_tag_evaluation(
        image_id=image_id,
        tag_name="landscape",
        description_hash="hash123",
        status="matched",
        score=0.85,
        reason="mountain seen",
        model_name="gpt-4o",
        image_mtime=100.0,
        db_path=db_file,
    )

    conn = get_connection(db_file)
    try:
        row = conn.execute(
            "SELECT * FROM tag_evaluations WHERE image_id = ? AND tag_name = ?",
            (image_id, "landscape"),
        ).fetchone()
        assert row is not None
        assert row["status"] == "matched"
        assert row["score"] == 0.85
        assert row["description_hash"] == "hash123"
    finally:
        conn.close()

    # Record suppression
    record_user_suppression(
        image_id=image_id,
        tag_name="landscape",
        reason="manual_removal",
        db_path=db_file,
    )

    conn = get_connection(db_file)
    try:
        sup_row = conn.execute(
            "SELECT * FROM user_suppressions WHERE image_id = ? AND tag_name = ?",
            (image_id, "landscape"),
        ).fetchone()
        assert sup_row is not None
        assert sup_row["reason"] == "manual_removal"
    finally:
        conn.close()


def test_get_unevaluated_candidates(tmp_path: Path):
    db_file = tmp_path / "test_gallery.db"
    init_db(db_file)

    root = tmp_path / "gallery"
    root.mkdir()
    sub_dir = root / "vacation"
    sub_dir.mkdir()

    img1 = root / "root_img.jpg"
    img1.write_bytes(b"dummy1")
    img2 = sub_dir / "vac_img.jpg"
    img2.write_bytes(b"dummy2")

    sync_gallery_index(root_directory=root, db_path=db_file)

    active_tags = {
        "landscape": TagDefinition(description="Nature landscape", threshold=0.7),
        "portrait": TagDefinition(description="Face closeup", threshold=0.8),
    }
    tag_hashes = {
        "landscape": "hash_land",
        "portrait": "hash_port",
    }

    # Query all candidates
    candidates = get_unevaluated_candidates(
        root_directory=root,
        active_tags=active_tags,
        tag_hashes=tag_hashes,
        db_path=db_file,
    )
    # 2 images * 2 tags = 4 candidate pairs
    assert len(candidates) == 4

    # Query subfolder candidates only
    sub_candidates = get_unevaluated_candidates(
        root_directory=root,
        subfolder="vacation",
        active_tags=active_tags,
        tag_hashes=tag_hashes,
        db_path=db_file,
    )
    assert len(sub_candidates) == 2
    assert all("vac_img.jpg" in c["file_path"] for c in sub_candidates)

    # Evaluate 1 tag on vac_img.jpg
    vac_id = sub_candidates[0]["image_id"]
    record_tag_evaluation(
        image_id=vac_id,
        tag_name="landscape",
        description_hash="hash_land",
        status="matched",
        score=0.9,
        reason="nature",
        model_name="test_model",
        image_mtime=img2.stat().st_mtime,
        db_path=db_file,
    )

    # Re-query subfolder candidates - landscape should now be excluded for vac_img
    sub_candidates_after = get_unevaluated_candidates(
        root_directory=root,
        subfolder="vacation",
        active_tags=active_tags,
        tag_hashes=tag_hashes,
        db_path=db_file,
    )
    assert len(sub_candidates_after) == 1
    assert sub_candidates_after[0]["tag_name"] == "portrait"


def test_suppression_prevents_unevaluated_candidate(tmp_path: Path):
    db_file = tmp_path / "test_gallery.db"
    init_db(db_file)

    root = tmp_path / "gallery"
    root.mkdir()
    img1 = root / "img.jpg"
    img1.write_bytes(b"dummy")

    sync_gallery_index(root_directory=root, db_path=db_file)

    conn = get_connection(db_file)
    try:
        row = conn.execute("SELECT id FROM images WHERE filename='img.jpg'").fetchone()
        image_id = row["id"]
    finally:
        conn.close()

    # Suppress tag "landscape"
    record_user_suppression(image_id=image_id, tag_name="landscape", db_path=db_file)

    active_tags = {
        "landscape": TagDefinition(description="Nature landscape", threshold=0.7),
    }
    tag_hashes = {"landscape": "hash_land"}

    candidates = get_unevaluated_candidates(
        root_directory=root,
        active_tags=active_tags,
        tag_hashes=tag_hashes,
        db_path=db_file,
    )
    assert len(candidates) == 0


def test_evaluate_thresholds_locally(tmp_path: Path):
    from PIL import Image

    db_file = tmp_path / "test_gallery.db"
    init_db(db_file)

    root = tmp_path / "gallery"
    root.mkdir()
    img_pil = Image.new("RGB", (50, 50), color=(255, 0, 0))
    img1 = root / "img.jpg"
    img_pil.save(img1, format="JPEG")

    sync_gallery_index(root_directory=root, db_path=db_file)

    conn = get_connection(db_file)
    try:
        row = conn.execute("SELECT id FROM images WHERE filename='img.jpg'").fetchone()
        image_id = row["id"]
    finally:
        conn.close()

    # Record evaluation score=0.75 for description_hash="hash1"
    record_tag_evaluation(
        image_id=image_id,
        tag_name="sunset",
        description_hash="hash1",
        status="matched",
        score=0.75,
        reason="sky color",
        model_name="test_model",
        image_mtime=img1.stat().st_mtime,
        db_path=db_file,
    )

    # Initial threshold 0.8 -> score 0.75 is below 0.8 so not tagged
    active_tags = {
        "sunset": TagDefinition(description="Sunset sky", threshold=0.8),
    }
    tag_hashes = {"sunset": "hash1"}

    stats = evaluate_thresholds_locally(
        root_directory=root,
        active_tags=active_tags,
        tag_hashes=tag_hashes,
        db_path=db_file,
    )
    assert stats["added"] == 0

    # Lower threshold to 0.7 -> score 0.75 is now above 0.7 -> locally added!
    active_tags["sunset"].threshold = 0.7
    stats = evaluate_thresholds_locally(
        root_directory=root,
        active_tags=active_tags,
        tag_hashes=tag_hashes,
        db_path=db_file,
    )
    assert stats["added"] == 1

    conn = get_connection(db_file)
    try:
        t_row = conn.execute(
            "SELECT * FROM image_tags WHERE image_id=? AND tag_name='sunset'",
            (image_id,),
        ).fetchone()
        assert t_row is not None
    finally:
        conn.close()


def test_sync_gallery_index_detects_manual_exif_removal(tmp_path: Path):
    from PIL import Image

    from exif_tagger.exif_writer import set_xptags

    db_file = tmp_path / "test_gallery.db"
    init_db(db_file)

    root = tmp_path / "gallery"
    root.mkdir()
    img1 = root / "img.jpg"
    Image.new("RGB", (50, 50), color=(0, 255, 0)).save(img1, format="JPEG")

    # Set EXIF tag "nature" on image
    set_xptags(img1, ["nature"])

    # First sync
    sync_gallery_index(root_directory=root, db_path=db_file)

    conn = get_connection(db_file)
    try:
        row = conn.execute("SELECT id FROM images WHERE filename='img.jpg'").fetchone()
        image_id = row["id"]
        # Set source to 'model'
        conn.execute("UPDATE image_tags SET source='model' WHERE image_id=? AND tag_name='nature'", (image_id,))
        conn.commit()
    finally:
        conn.close()

    # Now simulate user manually removing "nature" tag from EXIF
    set_xptags(img1, [])

    # Update mtime slightly to force re-sync
    mtime = img1.stat().st_mtime + 5.0
    import os

    os.utime(img1, (mtime, mtime))

    # Second sync
    sync_gallery_index(root_directory=root, db_path=db_file)

    # Verify user suppression was recorded for "nature"
    conn = get_connection(db_file)
    try:
        sup_row = conn.execute(
            "SELECT * FROM user_suppressions WHERE image_id=? AND tag_name='nature'",
            (image_id,),
        ).fetchone()
        assert sup_row is not None
    finally:
        conn.close()
