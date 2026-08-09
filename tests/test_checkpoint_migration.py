"""Unit tests for tag hash calculation and legacy JSON checkpoint migration."""

from __future__ import annotations

import json
from pathlib import Path

from exif_tagger.config import compute_tag_hash, migrate_legacy_checkpoint
from exif_tagger.db import get_connection, init_db
from exif_tagger.models.schema import CheckpointData, ImageCheckpoint


def test_compute_tag_hash():
    desc = "A majestic mountain landscape with snow"
    h1 = compute_tag_hash(desc)
    h2 = compute_tag_hash("  A majestic mountain landscape with snow  ")
    assert isinstance(h1, str)
    assert len(h1) > 0
    # Whitespace stripping / normalization
    assert h1 == h2


def test_migrate_legacy_checkpoint(tmp_path: Path):
    root = tmp_path / "gallery"
    root.mkdir()
    db_file = tmp_path / "test_gallery.db"
    init_db(db_file)

    img_file = root / "photo1.jpg"
    img_file.write_bytes(b"dummy")

    # Insert image into db
    conn = get_connection(db_file)
    try:
        with conn:
            cursor = conn.execute(
                "INSERT INTO images (file_path, filename, relative_path, last_modified, indexed_at) "
                "VALUES (?, 'photo1.jpg', 'photo1.jpg', 100.0, '2026-08-07T12:00:00Z')",
                (str(img_file.resolve()),),
            )
            image_id = cursor.lastrowid
    finally:
        conn.close()

    # Create legacy checkpoint file
    cp_data = CheckpointData(
        version=1,
        created_at="2026-08-07T12:00:00Z",
        root_directory=str(root.resolve()),
        total_images=1,
        processed=1,
        images={
            str(img_file.resolve()): ImageCheckpoint(
                path=str(img_file.resolve()),
                status="done",
                matched_tags=["landscape"],
            )
        },
    )

    cp_file = root / ".exif-tagger-checkpoint.json"
    with open(cp_file, "w", encoding="utf-8") as fh:
        json.dump(cp_data.model_dump(), fh)

    # Run migration
    migrated_count = migrate_legacy_checkpoint(root_directory=root, db_path=db_file)
    assert migrated_count == 1

    # Check database tag_evaluations and image_tags
    conn = get_connection(db_file)
    try:
        eval_row = conn.execute(
            "SELECT * FROM tag_evaluations WHERE image_id=? AND tag_name='landscape'",
            (image_id,),
        ).fetchone()
        assert eval_row is not None
        assert eval_row["status"] == "matched"

        tag_row = conn.execute(
            "SELECT * FROM image_tags WHERE image_id=? AND tag_name='landscape'",
            (image_id,),
        ).fetchone()
        assert tag_row is not None
    finally:
        conn.close()

    # Checkpoint file should be removed or renamed after migration
    assert not cp_file.exists()
