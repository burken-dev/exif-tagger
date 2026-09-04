"""Tests for gallery API endpoints in server.py."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from PIL import Image as PILImage

from exif_tagger.db import sync_gallery_index
from exif_tagger.exif_writer import set_xptags
from exif_tagger.server import app
from tests.conftest import TEST_API_TOKEN


@pytest.fixture
def gallery_setup(tmp_path, monkeypatch):
    """Setup gallery test directory and override DB_PATH in db module."""
    db_path = tmp_path / "test_api_gallery.db"
    gallery_dir = tmp_path / "images"
    gallery_dir.mkdir()

    img1 = gallery_dir / "cat.jpg"
    PILImage.new("RGB", (50, 50), color="yellow").save(img1)
    set_xptags(img1, ["feline", "cute"])

    img2 = gallery_dir / "dog.jpg"
    PILImage.new("RGB", (50, 50), color="blue").save(img2)
    set_xptags(img2, ["canine", "cute"])

    monkeypatch.setenv("EXIFTAGGER_DB_FILE", str(db_path))

    # Perform initial sync
    sync_gallery_index(gallery_dir, db_path=db_path)

    class MockConfig:
        root_directory = str(gallery_dir)
        exclude_patterns = []

    monkeypatch.setattr("exif_tagger.server.CONFIG_PATH", str(tmp_path / "config.yaml"))
    with patch("exif_tagger.server.load_config", return_value=MockConfig()):
        yield TestClient(app, headers={"Authorization": f"Bearer {TEST_API_TOKEN}"}), db_path, gallery_dir


class TestGalleryAPI:
    def test_get_gallery_images(self, gallery_setup):
        client, _, _ = gallery_setup
        resp = client.get("/api/gallery/images")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert len(data["images"]) == 2

    def test_get_gallery_tags(self, gallery_setup):
        client, _, _ = gallery_setup
        resp = client.get("/api/gallery/tags")
        assert resp.status_code == 200
        data = resp.json()
        assert set(data["tags"]) == {"canine", "cute", "feline"}

    def test_get_gallery_image_by_id(self, gallery_setup):
        client, _, _ = gallery_setup
        images = client.get("/api/gallery/images").json()["images"]
        img_id = images[0]["id"]

        resp = client.get(f"/api/gallery/image/{img_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == img_id

    def test_get_gallery_image_file(self, gallery_setup):
        client, _, _ = gallery_setup
        images = client.get("/api/gallery/images").json()["images"]
        img_id = images[0]["id"]

        resp = client.get(f"/api/gallery/image/{img_id}/file")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("image/")

    def test_put_image_tags(self, gallery_setup):
        client, _, _ = gallery_setup
        images = client.get("/api/gallery/images").json()["images"]
        img_id = images[0]["id"]

        resp = client.put(
            f"/api/gallery/image/{img_id}/tags",
            json={"tags": ["customtag", "updated"]},
        )
        assert resp.status_code == 200

        img_resp = client.get(f"/api/gallery/image/{img_id}")
        assert set(img_resp.json()["tags"]) == {"customtag", "updated"}

    def test_post_batch_tags(self, gallery_setup):
        client, _, _ = gallery_setup
        images = client.get("/api/gallery/images").json()["images"]
        img_ids = [img["id"] for img in images]

        resp = client.post(
            "/api/gallery/batch-tags",
            json={
                "image_ids": img_ids,
                "add_tags": ["batchadded"],
                "remove_tags": ["cute"],
            },
        )
        assert resp.status_code == 200
        assert resp.json()["modified"] == 2

        tags_resp = client.get("/api/gallery/tags")
        tags = tags_resp.json()["tags"]
        assert "batchadded" in tags
        assert "cute" not in tags

    def test_post_remove_tag_global(self, gallery_setup):
        client, _, _ = gallery_setup
        resp = client.post(
            "/api/gallery/remove-tag-global",
            json={"tag_name": "cute"},
        )
        assert resp.status_code == 200
        assert resp.json()["modified"] == 2

        tags_resp = client.get("/api/gallery/tags")
        assert "cute" not in tags_resp.json()["tags"]
