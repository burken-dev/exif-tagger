"""Containment tests: no indexing/serving/listing outside the gallery root."""
from __future__ import annotations

import exif_tagger.server as server_module
from fastapi.testclient import TestClient
from PIL import Image

HEADERS = {"Authorization": "Bearer test-token-xyz"}


def _client():
    return TestClient(server_module.app, raise_server_exceptions=False)


def _make_jpeg(path):
    img = Image.new("RGB", (60, 40), color=(1, 2, 3))
    img.save(path, format="JPEG")
    return path


def test_sync_absolute_path_outside_root_rejected(monkeypatch, tmp_path):
    gallery = tmp_path / "gallery"
    gallery.mkdir()
    outside = _make_jpeg(tmp_path / "evil.jpg")
    cfg = tmp_path / "config.yaml"
    cfg.write_text(f"root_directory: {gallery}\nmodel:\n  base_url: http://x/v1\n  model_name: m\n")
    monkeypatch.setattr(server_module, "CONFIG_PATH", str(cfg))
    resp = _client().post("/api/gallery/image/sync", json={"file_path": str(outside)}, headers=HEADERS)
    assert resp.status_code == 403


def test_folders_dotdot_rejected(monkeypatch, tmp_path):
    gallery = tmp_path / "gallery"
    gallery.mkdir()
    cfg = tmp_path / "config.yaml"
    cfg.write_text(f"root_directory: {gallery}\nmodel:\n  base_url: http://x/v1\n  model_name: m\n")
    monkeypatch.setattr(server_module, "CONFIG_PATH", str(cfg))
    resp = _client().get("/api/gallery/folders", params={"path": "../../.."}, headers=HEADERS)
    assert resp.status_code == 403


def test_by_id_file_outside_root_rejected(monkeypatch, tmp_path):
    from exif_tagger.db import get_connection, init_db
    gallery = tmp_path / "gallery"
    gallery.mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_text("topsecret")
    init_db()
    conn = get_connection()
    with conn:
        cur = conn.execute(
            "INSERT INTO images (file_path, filename, relative_path, last_modified, indexed_at) VALUES (?, ?, ?, ?, ?)",
            (str(secret.resolve()), "secret.txt", "secret.txt", 1.0, "2026-01-01T00:00:00"),
        )
        image_id = cur.lastrowid
    conn.close()
    cfg = tmp_path / "config.yaml"
    cfg.write_text(f"root_directory: {gallery}\nmodel:\n  base_url: http://x/v1\n  model_name: m\n")
    monkeypatch.setattr(server_module, "CONFIG_PATH", str(cfg))
    resp = _client().get(f"/api/gallery/image/{image_id}/file", headers=HEADERS)
    assert resp.status_code in (400, 403)
    assert b"topsecret" not in resp.content
