"""Unit tests for recursive unprocessed image counts in gallery folders."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import yaml

from exif_tagger.config import compute_tag_hash
from exif_tagger.db import (
    get_gallery_folders,
    init_db,
    record_tag_evaluation,
    record_user_suppression,
)


def test_get_gallery_folders_unprocessed_counts(tmp_path: Path):
    db_file = tmp_path / "gallery.db"
    root_dir = tmp_path / "images"
    root_dir.mkdir()

    # Create subdirectories
    sub1 = root_dir / "vacation"
    sub1.mkdir()
    sub2 = root_dir / "work"
    sub2.mkdir()
    sub1_nested = sub1 / "beach"
    sub1_nested.mkdir()

    # Create files
    f1 = sub1 / "img1.jpg"
    f1.write_text("dummy")
    f2 = sub1_nested / "img2.jpg"
    f2.write_text("dummy")
    f3 = sub2 / "img3.jpg"
    f3.write_text("dummy")

    # Create config file with active tags
    cfg_file = tmp_path / "config.yaml"
    cfg_data = {
        "root_directory": str(root_dir),
        "tags": {
            "nature": {"description": "Nature and scenery", "threshold": 0.7},
            "portrait": {"description": "People and faces", "threshold": 0.7},
        },
    }
    with open(cfg_file, "w") as f:
        yaml.safe_dump(cfg_data, f)

    init_db(db_file)
    conn = sqlite3.connect(str(db_file))
    conn.row_factory = sqlite3.Row
    with conn:
        conn.execute(
            "INSERT INTO images (id, file_path, filename, relative_path, last_modified, indexed_at) VALUES (?, ?, ?, ?, ?, ?)",
            (1, str(f1), "img1.jpg", "vacation/img1.jpg", 1000.0, "2026-08-25T00:00:00Z"),
        )
        conn.execute(
            "INSERT INTO images (id, file_path, filename, relative_path, last_modified, indexed_at) VALUES (?, ?, ?, ?, ?, ?)",
            (2, str(f2), "img2.jpg", "vacation/beach/img2.jpg", 1000.0, "2026-08-25T00:00:00Z"),
        )
        conn.execute(
            "INSERT INTO images (id, file_path, filename, relative_path, last_modified, indexed_at) VALUES (?, ?, ?, ?, ?, ?)",
            (3, str(f3), "img3.jpg", "work/img3.jpg", 1000.0, "2026-08-25T00:00:00Z"),
        )
    conn.close()

    # Initial state: all images have 0 evaluations -> all 3 images unprocessed
    res = get_gallery_folders(relative_path="", db_path=db_file, root_directory=root_dir, config_path=cfg_file)
    assert res["total_images"] == 3
    assert res["unprocessed_images"] == 3

    folder_map = {f["name"]: f for f in res["folders"]}
    assert folder_map["vacation"]["total_images"] == 2
    assert folder_map["vacation"]["unprocessed_images"] == 2
    assert folder_map["work"]["total_images"] == 1
    assert folder_map["work"]["unprocessed_images"] == 1

    # Breadcrumbs check at root
    assert len(res["breadcrumbs"]) == 1
    assert res["breadcrumbs"][0]["name"] == "Root"
    assert res["breadcrumbs"][0]["path"] == ""
    assert res["breadcrumbs"][0]["unprocessed_images"] == 3

    # Evaluate img3 for both tags
    nature_hash = compute_tag_hash("Nature and scenery")
    portrait_hash = compute_tag_hash("People and faces")

    record_tag_evaluation(3, "nature", nature_hash, "matched", 0.9, "nature ok", "test", 1000.0, db_path=db_file)
    record_tag_evaluation(3, "portrait", portrait_hash, "unmatched", 0.1, "not portrait", "test", 1000.0, db_path=db_file)

    res2 = get_gallery_folders(relative_path="", db_path=db_file, root_directory=root_dir, config_path=cfg_file)
    folder_map2 = {f["name"]: f for f in res2["folders"]}
    assert folder_map2["work"]["total_images"] == 1
    assert folder_map2["work"]["unprocessed_images"] == 0
    assert res2["unprocessed_images"] == 2

    # User suppresses 'portrait' on img1 and evaluates 'nature' on img1 -> img1 is fully processed
    record_tag_evaluation(1, "nature", nature_hash, "matched", 0.9, "nature ok", "test", 1000.0, db_path=db_file)
    record_user_suppression(1, "portrait", reason="manual", db_path=db_file)

    # Navigate inside vacation
    res_vac = get_gallery_folders(relative_path="vacation", db_path=db_file, root_directory=root_dir, config_path=cfg_file)
    assert res_vac["total_images"] == 2
    assert res_vac["unprocessed_images"] == 1
    beach_folder = res_vac["folders"][0]
    assert beach_folder["name"] == "beach"
    assert beach_folder["total_images"] == 1
    assert beach_folder["unprocessed_images"] == 1

    # Breadcrumbs check when navigated inside vacation
    assert len(res_vac["breadcrumbs"]) == 2
    assert res_vac["breadcrumbs"][0]["name"] == "Root"
    assert res_vac["breadcrumbs"][0]["unprocessed_images"] == 1
    assert res_vac["breadcrumbs"][1]["name"] == "vacation"
    assert res_vac["breadcrumbs"][1]["path"] == "vacation"
    assert res_vac["breadcrumbs"][1]["unprocessed_images"] == 1


def test_get_gallery_folders_hash_and_mtime_invalidation(tmp_path: Path):
    db_file = tmp_path / "gallery.db"
    root_dir = tmp_path / "images"
    root_dir.mkdir()

    f1 = root_dir / "img1.jpg"
    f1.write_text("dummy")

    cfg_file = tmp_path / "config.yaml"
    cfg_data = {
        "root_directory": str(root_dir),
        "tags": {
            "nature": {"description": "Nature and scenery", "threshold": 0.7},
        },
    }
    with open(cfg_file, "w") as f:
        yaml.safe_dump(cfg_data, f)

    init_db(db_file)
    conn = sqlite3.connect(str(db_file))
    with conn:
        conn.execute(
            "INSERT INTO images (id, file_path, filename, relative_path, last_modified, indexed_at) VALUES (?, ?, ?, ?, ?, ?)",
            (1, str(f1), "img1.jpg", "img1.jpg", 1000.0, "2026-08-25T00:00:00Z"),
        )
    conn.close()

    nature_hash = compute_tag_hash("Nature and scenery")
    record_tag_evaluation(1, "nature", nature_hash, "matched", 0.9, "nature ok", "test", 1000.0, db_path=db_file)

    # 1. Fully evaluated
    res = get_gallery_folders(relative_path="", db_path=db_file, root_directory=root_dir, config_path=cfg_file)
    assert res["unprocessed_images"] == 0

    # 2. Image mtime changes in DB
    conn = sqlite3.connect(str(db_file))
    with conn:
        conn.execute("UPDATE images SET last_modified = 1005.0 WHERE id = 1")
    conn.close()

    res = get_gallery_folders(relative_path="", db_path=db_file, root_directory=root_dir, config_path=cfg_file)
    assert res["unprocessed_images"] == 1

    # 3. Re-evaluate with new mtime
    record_tag_evaluation(1, "nature", nature_hash, "matched", 0.9, "nature ok", "test", 1005.0, db_path=db_file)
    res = get_gallery_folders(relative_path="", db_path=db_file, root_directory=root_dir, config_path=cfg_file)
    assert res["unprocessed_images"] == 0

    # 4. Tag description changes in config -> tag hash mismatch
    cfg_data["tags"]["nature"]["description"] = "Updated Nature description"
    with open(cfg_file, "w") as f:
        yaml.safe_dump(cfg_data, f)

    res = get_gallery_folders(relative_path="", db_path=db_file, root_directory=root_dir, config_path=cfg_file)
    assert res["unprocessed_images"] == 1


def test_get_gallery_folders_no_active_tags(tmp_path: Path):
    db_file = tmp_path / "gallery.db"
    root_dir = tmp_path / "images"
    root_dir.mkdir()

    f1 = root_dir / "img1.jpg"
    f1.write_text("dummy")

    cfg_file = tmp_path / "config.yaml"
    cfg_data = {
        "root_directory": str(root_dir),
        "tags": {},
    }
    with open(cfg_file, "w") as f:
        yaml.safe_dump(cfg_data, f)

    init_db(db_file)
    conn = sqlite3.connect(str(db_file))
    with conn:
        conn.execute(
            "INSERT INTO images (id, file_path, filename, relative_path, last_modified, indexed_at) VALUES (?, ?, ?, ?, ?, ?)",
            (1, str(f1), "img1.jpg", "img1.jpg", 1000.0, "2026-08-25T00:00:00Z"),
        )
    conn.close()

    res = get_gallery_folders(relative_path="", db_path=db_file, root_directory=root_dir, config_path=cfg_file)
    assert res["total_images"] == 1
    assert res["unprocessed_images"] == 0
