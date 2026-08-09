"""Test processing subfolders to ensure DB is not cleared or corrupted."""

from pathlib import Path
from unittest.mock import patch

from PIL import Image

from exif_tagger.db import get_connection, get_gallery_folders, sync_gallery_index
from exif_tagger.main import PipelineEngine
from exif_tagger.models.schema import TaggingResponse, TagResult


def create_test_image(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (100, 100), color="blue")
    img.save(path, format="JPEG")


def test_subfolder_processing_does_not_clear_db(tmp_path: Path, monkeypatch):
    gallery_dir = tmp_path / "gallery"
    sub1 = gallery_dir / "folder1"
    sub2 = gallery_dir / "folder2"

    img1_path = sub1 / "image1.jpg"
    img2_path = sub2 / "image2.jpg"

    create_test_image(img1_path)
    create_test_image(img2_path)

    db_path = tmp_path / "test.db"
    monkeypatch.setenv("EXIFTAGGER_DB_FILE", str(db_path))

    # Step 1: Initial sync of gallery
    sync_stats = sync_gallery_index(root_directory=gallery_dir, db_path=db_path)
    assert sync_stats["total"] == 2

    # Verify initial gallery folder counts
    folders_info = get_gallery_folders(db_path=db_path, root_directory=gallery_dir)
    folder_counts = {f["name"]: f["image_count"] for f in folders_info["folders"]}
    assert folder_counts.get("folder1") == 1
    assert folder_counts.get("folder2") == 1

    # Step 2: Run processing on subfolder1
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        f"""
root_directory: "{gallery_dir}"
model:
  base_url: "https://api.openai.com/v1"
  model_name: "test-model"
  api_key: "test-key"
tags:
  nature:
    description: "nature scene"
    threshold: 0.5
"""
    )

    engine = PipelineEngine(config_path=str(config_file))

    mock_res = TaggingResponse(results=[TagResult(tag_name="nature", score=0.9, reason="good")])
    with patch("exif_tagger.ai_client.tag_image_with_ai") as mock_ai:
        mock_ai.return_value = mock_res
        # Process ONLY subfolder1
        summary = engine.start_session(root_directory="folder1")

    # Step 3: Check DB integrity after subfolder processing
    conn = get_connection(db_path)
    rows = conn.execute("SELECT id, file_path, relative_path FROM images").fetchall()
    conn.close()

    rel_paths = [r["relative_path"] for r in rows]

    # Verify folder2 image was NOT deleted from DB!
    assert len(rows) == 2, f"Expected 2 images in DB, found {len(rows)}: {rel_paths}"
    assert "folder1/image1.jpg" in rel_paths
    assert "folder2/image2.jpg" in rel_paths

    # Verify folder browser counts remain 1 for each folder
    folders_info_after = get_gallery_folders(db_path=db_path, root_directory=gallery_dir)
    folder_counts_after = {f["name"]: f["image_count"] for f in folders_info_after["folders"]}
    assert folder_counts_after.get("folder1") == 1, f"folder1 count is {folder_counts_after.get('folder1')}"
    assert folder_counts_after.get("folder2") == 1, f"folder2 count is {folder_counts_after.get('folder2')}"


def test_subfolder_processing_with_slash_prefix(tmp_path: Path, monkeypatch):
    gallery_dir = tmp_path / "gallery"
    sub1 = gallery_dir / "folder1"
    sub2 = gallery_dir / "folder2"

    img1_path = sub1 / "image1.jpg"
    img2_path = sub2 / "image2.jpg"

    create_test_image(img1_path)
    create_test_image(img2_path)

    db_path = tmp_path / "test.db"
    monkeypatch.setenv("EXIFTAGGER_DB_FILE", str(db_path))

    sync_gallery_index(root_directory=gallery_dir, db_path=db_path)

    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        f"""
root_directory: "{gallery_dir}"
model:
  base_url: "https://api.openai.com/v1"
  model_name: "test-model"
  api_key: "test-key"
tags:
  nature:
    description: "nature scene"
    threshold: 0.5
"""
    )

    engine = PipelineEngine(config_path=str(config_file))
    mock_res = TaggingResponse(results=[TagResult(tag_name="nature", score=0.9, reason="good")])

    with patch("exif_tagger.ai_client.tag_image_with_ai") as mock_ai:
        mock_ai.return_value = mock_res
        # Pass root_directory with a leading slash e.g. "/folder1"
        summary = engine.start_session(root_directory="/folder1")

    assert summary.get("total_processed") == 1

