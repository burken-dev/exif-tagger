"""Auth gate tests for /api/* routes."""
from __future__ import annotations

from fastapi.testclient import TestClient

import exif_tagger.server as server_module

TOKEN = "test-token-xyz"


def _client():
    return TestClient(server_module.app, raise_server_exceptions=False)


def test_api_requires_token(monkeypatch):
    monkeypatch.setenv("EXIFTAGGER_API_TOKEN", TOKEN)
    resp = _client().get("/api/status")
    assert resp.status_code == 401


def test_api_wrong_token(monkeypatch):
    monkeypatch.setenv("EXIFTAGGER_API_TOKEN", TOKEN)
    resp = _client().get("/api/status", headers={"Authorization": "Bearer wrong"})
    assert resp.status_code == 401


def test_api_valid_token(monkeypatch):
    monkeypatch.setenv("EXIFTAGGER_API_TOKEN", TOKEN)
    resp = _client().get("/api/status", headers={"Authorization": f"Bearer {TOKEN}"})
    assert resp.status_code == 200


def test_api_misconfigured_server(monkeypatch):
    monkeypatch.delenv("EXIFTAGGER_API_TOKEN", raising=False)
    resp = _client().get("/api/status", headers={"Authorization": "Bearer anything"})
    assert resp.status_code == 503


def test_ui_route_stays_public(monkeypatch):
    monkeypatch.setenv("EXIFTAGGER_API_TOKEN", TOKEN)
    resp = _client().get("/")
    assert resp.status_code == 200


def test_config_masks_api_key(monkeypatch, tmp_path):
    monkeypatch.setenv("EXIFTAGGER_API_TOKEN", TOKEN)
    cfg = tmp_path / "config.yaml"
    cfg.write_text("root_directory: /tmp\nmodel:\n  base_url: http://x/v1\n  model_name: m\n  api_key: super-secret\n")
    monkeypatch.setattr(server_module, "CONFIG_PATH", str(cfg))
    resp = _client().get("/api/config", headers={"Authorization": f"Bearer {TOKEN}"})
    assert resp.status_code == 200
    body = resp.json()
    assert "api_key" not in body["model"]
    assert body["model"]["api_key_set"] is True
