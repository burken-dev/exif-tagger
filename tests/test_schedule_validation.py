"""Schedule creation validates folder; job failures are recorded."""
from __future__ import annotations

import exif_tagger.server as server_module
from fastapi.testclient import TestClient

HEADERS = {"Authorization": "Bearer test-token-xyz"}


def _client():
    return TestClient(server_module.app, raise_server_exceptions=False)


def test_create_schedule_outside_root_rejected(monkeypatch, tmp_path):
    gallery = tmp_path / "gallery"
    gallery.mkdir()
    cfg = tmp_path / "config.yaml"
    cfg.write_text(f"root_directory: {gallery}\nmodel:\n  base_url: http://x/v1\n  model_name: m\n")
    monkeypatch.setattr(server_module, "CONFIG_PATH", str(cfg))
    monkeypatch.setenv("EXIFTAGGER_SCHEDULES_FILE", str(tmp_path / "schedules.json"))
    server_module._schedules.clear()
    resp = _client().post("/api/schedule", json={"name": "evil", "folder": "/etc"}, headers=HEADERS)
    assert resp.status_code == 400


def test_run_schedule_job_failure_recorded(monkeypatch, tmp_path):
    from unittest.mock import patch
    from exif_tagger.models.schema import ScheduleModel

    gallery = tmp_path / "gallery"
    gallery.mkdir()
    cfg = tmp_path / "config.yaml"
    cfg.write_text(f"root_directory: {gallery}\nmodel:\n  base_url: http://x/v1\n  model_name: m\n")
    monkeypatch.setattr(server_module, "CONFIG_PATH", str(cfg))
    sched_file = tmp_path / "schedules.json"
    monkeypatch.setattr(server_module, "SCHEDULES_FILE", sched_file)
    monkeypatch.setenv("EXIFTAGGER_SCHEDULES_FILE", str(sched_file))
    server_module._schedules.clear()
    server_module._schedules["s1"] = ScheduleModel(id="s1", name="t", folder=str(gallery), enabled=True)
    with patch.object(server_module, "PipelineEngine", side_effect=RuntimeError("boom")):
        server_module._run_schedule_job("s1")
    assert server_module._schedules["s1"].last_status == "failed"
