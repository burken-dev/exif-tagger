"""Test processing subfolders to ensure DB is not cleared or corrupted."""

from pathlib import Path
from unittest.mock import patch

from PIL import Image

import pytest
from fastapi.testclient import TestClient

from exif_tagger.db import get_connection, get_gallery_folders, sync_gallery_index
from exif_tagger.main import PipelineEngine
from exif_tagger.models.schema import TaggingResponse, TagResult
from exif_tagger.server import app


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


def test_validate_and_resolve_subfolder_root_inputs(tmp_path: Path):
    from exif_tagger.main import validate_and_resolve_subfolder

    root = tmp_path / "gallery"
    root.mkdir()

    # None, empty, slash, dot should all resolve to root with relative_subfolder = None
    resolved_root, subfolder = validate_and_resolve_subfolder(None, root)
    assert resolved_root == root.resolve()
    assert subfolder is None

    resolved_root, subfolder = validate_and_resolve_subfolder("", root)
    assert subfolder is None

    resolved_root, subfolder = validate_and_resolve_subfolder("/", root)
    assert subfolder is None

    resolved_root, subfolder = validate_and_resolve_subfolder(".", root)
    assert subfolder is None


def test_validate_and_resolve_subfolder_valid_relative(tmp_path: Path):
    from exif_tagger.main import validate_and_resolve_subfolder

    root = tmp_path / "gallery"
    sub = root / "vacation" / "2026"
    sub.mkdir(parents=True)

    # Leading slash should be stripped and treated relative to root
    resolved_root, subfolder = validate_and_resolve_subfolder("/vacation/2026", root)
    assert resolved_root == root.resolve()
    assert subfolder == "vacation/2026"

    # Without leading slash
    resolved_root, subfolder = validate_and_resolve_subfolder("vacation/2026", root)
    assert resolved_root == root.resolve()
    assert subfolder == "vacation/2026"


def test_validate_and_resolve_subfolder_breakout_attempts(tmp_path: Path):
    from exif_tagger.main import validate_and_resolve_subfolder

    root = tmp_path / "gallery"
    root.mkdir()

    bad_paths = ["../../etc/passwd", "/../outside", "../", "/../etc/passwd"]
    for bad_path in bad_paths:
        with pytest.raises(ValueError) as exc_info:
            validate_and_resolve_subfolder(bad_path, root)
        assert f"Requested path '{bad_path}' is outside the root image directory." in str(exc_info.value)


def test_api_start_rejects_path_traversal(tmp_path: Path, monkeypatch):
    client = TestClient(app)

    # Attempt path traversal breakout via API
    resp = client.post("/api/start", json={"rootDirectory": "../../etc/passwd"})
    assert resp.status_code == 400
    assert "is outside the root image directory" in resp.json()["detail"]


def test_pipeline_engine_start_session_scoping(tmp_path: Path, monkeypatch):
    root = tmp_path / "gallery"
    root.mkdir()
    (root / "img.jpg").touch()
    sub = root / "subfolder"
    sub.mkdir()
    (sub / "sub_img.jpg").touch()

    # Engine start_session with path traversal should fail validation
    engine = PipelineEngine(config_path="config.yaml")
    monkeypatch.setattr(
        engine,
        "_load_config",
        lambda: type(
            "Config",
            (),
            {
                "root_directory": str(root),
                "validate": lambda self: None,
                "validate_exclude_patterns": lambda self: None,
                "log_level": "INFO",
                "log_dir": str(tmp_path / "logs"),
            },
        )(),
    )

    with pytest.raises(ValueError) as exc_info:
        engine.start_session(root_directory="../../etc/passwd")
    assert "outside the root image directory" in str(exc_info.value)




