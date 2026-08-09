"""Unit tests for gallery folder tree navigation, glob search filtering, and folder API."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from exif_tagger.db import (
    get_gallery_folders,
    get_gallery_images,
    init_db,
    sync_gallery_index,
)


def test_get_gallery_folders(tmp_path: Path):
    db_file = tmp_path / "test_gallery.db"
    init_db(db_file)

    root = tmp_path / "gallery"
    root.mkdir()

    vacation_dir = root / "vacation"
    vacation_dir.mkdir()
    sub2024 = vacation_dir / "2024"
    sub2024.mkdir()
    work_dir = root / "work"
    work_dir.mkdir()

    # Create test images
    img_root = root / "root_img.jpg"
    Image.new("RGB", (50, 50), color="red").save(img_root, format="JPEG")

    img_vac1 = vacation_dir / "vac1.jpg"
    Image.new("RGB", (50, 50), color="blue").save(img_vac1, format="JPEG")

    img_2024 = sub2024 / "beach.png"
    Image.new("RGB", (50, 50), color="green").save(img_2024, format="PNG")

    img_work = work_dir / "report.jpg"
    Image.new("RGB", (50, 50), color="yellow").save(img_work, format="JPEG")

    sync_gallery_index(root_directory=root, db_path=db_file)

    # 1. Test root folder listing
    res_root = get_gallery_folders(relative_path="", db_path=db_file)
    assert res_root["current_path"] == ""
    folder_names = [f["name"] for f in res_root["folders"]]
    assert "vacation" in folder_names
    assert "work" in folder_names

    # Check vacation image count (vac1.jpg + 2024/beach.png = 2)
    vac_folder = next(f for f in res_root["folders"] if f["name"] == "vacation")
    assert vac_folder["image_count"] == 2

    # 2. Test subfolder listing under "vacation"
    res_vac = get_gallery_folders(relative_path="vacation", db_path=db_file)
    assert res_vac["current_path"] == "vacation"
    assert len(res_vac["folders"]) == 1
    assert res_vac["folders"][0]["name"] == "2024"
    assert res_vac["folders"][0]["image_count"] == 1


def test_get_gallery_images_folder_scoping(tmp_path: Path):
    db_file = tmp_path / "test_gallery.db"
    init_db(db_file)

    root = tmp_path / "gallery"
    root.mkdir()
    vacation_dir = root / "vacation"
    vacation_dir.mkdir()

    img_root = root / "root_img.jpg"
    Image.new("RGB", (50, 50)).save(img_root, format="JPEG")

    img_vac = vacation_dir / "vac1.jpg"
    Image.new("RGB", (50, 50)).save(img_vac, format="JPEG")

    sync_gallery_index(root_directory=root, db_path=db_file)

    # Query folder="vacation"
    images, total = get_gallery_images(folder="vacation", db_path=db_file)
    assert total == 1
    assert images[0]["filename"] == "vac1.jpg"


def test_get_gallery_images_glob_search(tmp_path: Path):
    db_file = tmp_path / "test_gallery.db"
    init_db(db_file)

    root = tmp_path / "gallery"
    root.mkdir()

    img1 = root / "DSC_001.jpg"
    Image.new("RGB", (50, 50)).save(img1, format="JPEG")
    img2 = root / "DSC_002.png"
    Image.new("RGB", (50, 50)).save(img2, format="PNG")
    img3 = root / "PHOTO_999.jpg"
    Image.new("RGB", (50, 50)).save(img3, format="JPEG")

    sync_gallery_index(root_directory=root, db_path=db_file)

    # Search with glob pattern *.png
    images_png, total_png = get_gallery_images(search="*.png", db_path=db_file)
    assert total_png == 1
    assert images_png[0]["filename"] == "DSC_002.png"

    # Search with glob pattern DSC_*
    images_dsc, total_dsc = get_gallery_images(search="DSC_*", db_path=db_file)
    assert total_dsc == 2


def test_get_gallery_folders_unindexed_folders(tmp_path: Path):
    db_file = tmp_path / "test_gallery.db"
    init_db(db_file)

    root = tmp_path / "gallery"
    root.mkdir()

    # Create folders on disk
    (root / "indexed_folder").mkdir()
    (root / "empty_unindexed_folder").mkdir()

    img1 = root / "indexed_folder" / "photo.jpg"
    Image.new("RGB", (50, 50), color="blue").save(img1, format="JPEG")

    sync_gallery_index(root_directory=root, db_path=db_file)

    # Now create an extra unindexed subfolder after sync
    (root / "new_unindexed_dir").mkdir()

    res = get_gallery_folders(relative_path="", db_path=db_file, root_directory=root)
    folder_names = [f["name"] for f in res["folders"]]

    assert "indexed_folder" in folder_names
    assert "empty_unindexed_folder" in folder_names
    assert "new_unindexed_dir" in folder_names

    unindexed_item = next(f for f in res["folders"] if f["name"] == "new_unindexed_dir")
    assert unindexed_item["image_count"] == 0
