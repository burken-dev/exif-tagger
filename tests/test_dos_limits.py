"""Resource-consumption limits on user-controlled inputs."""
from __future__ import annotations

import exif_tagger.server as server_module
from fastapi.testclient import TestClient

HEADERS = {"Authorization": "Bearer test-token-xyz"}


def _client():
    return TestClient(server_module.app, raise_server_exceptions=False)


def test_gallery_images_limit_capped():
    resp = _client().get("/api/gallery/images", params={"limit": 1000000}, headers=HEADERS)
    assert resp.status_code == 422


def test_gallery_images_negative_offset_rejected():
    resp = _client().get("/api/gallery/images", params={"offset": -5}, headers=HEADERS)
    assert resp.status_code == 422


def test_batch_tags_size_capped():
    resp = _client().post(
        "/api/gallery/batch-tags",
        json={"image_ids": list(range(501)), "add_tags": ["x"]},
        headers=HEADERS,
    )
    assert resp.status_code == 422


def test_max_image_pixels_capped():
    from PIL import Image
    assert Image.MAX_IMAGE_PIXELS is not None and Image.MAX_IMAGE_PIXELS <= 50_000_000


def test_oversize_file_rejected(monkeypatch, tmp_path):
    from PIL import Image as PILImage
    gallery = tmp_path / "gallery"
    gallery.mkdir()
    big = gallery / "big.jpg"
    PILImage.new("RGB", (64, 64)).save(big, format="JPEG")
    with open(big, "ab") as f:
        f.truncate(server_module.MAX_INLINE_IMAGE_BYTES + 1)
    cfg = tmp_path / "config.yaml"
    cfg.write_text(f"root_directory: {gallery}\nmodel:\n  base_url: http://x/v1\n  model_name: m\n")
    monkeypatch.setattr(server_module, "CONFIG_PATH", str(cfg))
    resp = _client().get("/api/gallery/image/file", params={"path": "big.jpg"}, headers=HEADERS)
    assert resp.status_code == 413
