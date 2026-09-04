"""5xx responses must not leak exception text or paths."""
from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

import exif_tagger.server as server_module

HEADERS = {"Authorization": "Bearer test-token-xyz"}


def _client():
    return TestClient(server_module.app, raise_server_exceptions=False)


def test_global_handler_hides_details():
    with patch.object(server_module, "_get_engine", side_effect=RuntimeError("/secret/path boom")):
        resp = _client().get("/api/status", headers=HEADERS)
    assert resp.status_code == 500
    assert resp.json() == {"detail": "Internal server error"}
    assert "/secret/path" not in resp.text


def test_gallery_images_hides_details(monkeypatch, tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("root_directory: /tmp\nmodel:\n  base_url: http://x/v1\n  model_name: m\n")
    monkeypatch.setattr(server_module, "CONFIG_PATH", str(cfg))
    with patch("exif_tagger.server.get_gallery_images", side_effect=OSError("/etc/passwd unreadable")):
        resp = _client().get("/api/gallery/images", headers=HEADERS)
    assert resp.status_code == 500
    assert "/etc/passwd" not in resp.text


def test_config_rejects_bad_base_url(monkeypatch, tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("root_directory: /tmp\nmodel:\n  base_url: http://x/v1\n  model_name: m\n")
    monkeypatch.setattr(server_module, "CONFIG_PATH", str(cfg))
    resp = _client().put("/api/config", json={"model": {"base_url": "ftp://evil/x"}}, headers=HEADERS)
    assert resp.status_code == 400


def test_config_rejects_url_with_credentials(monkeypatch, tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("root_directory: /tmp\nmodel:\n  base_url: http://x/v1\n  model_name: m\n")
    monkeypatch.setattr(server_module, "CONFIG_PATH", str(cfg))
    resp = _client().put(
        "/api/config", json={"model": {"base_url": "http://user:pass@evil/v1"}}, headers=HEADERS
    )
    assert resp.status_code == 400


def test_config_rejects_relative_log_dir(monkeypatch, tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("root_directory: /tmp\nmodel:\n  base_url: http://x/v1\n  model_name: m\n")
    monkeypatch.setattr(server_module, "CONFIG_PATH", str(cfg))
    resp = _client().put("/api/config", json={"log_dir": "relative/path"}, headers=HEADERS)
    assert resp.status_code == 400
