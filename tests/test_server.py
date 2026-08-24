"""Tests for the FastAPI server endpoints and schedule management."""

from __future__ import annotations

import os
import tempfile
from datetime import UTC
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# Import the app — we'll patch dependencies at module level
import exif_tagger.server as server_module
from exif_tagger.models.schema import ScheduleModel


@pytest.fixture(autouse=True)
def _reset_server_state():
    """Reset global state before each test."""
    server_module._engine = None
    server_module._schedules.clear()
    server_module._scheduler = None
    # Reset schedules file
    schedules_file = Path("/app/schedules.json")
    if schedules_file.exists():
        schedules_file.unlink()


@pytest.fixture
def client(_reset_server_state):
    """Create a test client."""
    return TestClient(server_module.app)


class TestApiStatus:
    def test_status_no_session(self, client):
        resp = client.get("/api/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["running"] is False
        assert data["processed"] == 0
        assert data["total"] == 0

    def test_status_running(self, client):
        with patch.object(server_module, "_get_engine") as mock_get:
            mock_engine = MagicMock()
            mock_engine.get_status.return_value = {
                "running": True,
                "processed": 5,
                "total": 10,
                "currentImage": "photo.jpg",
                "progressPct": 50.0,
                "stopRequested": False,
            }
            mock_engine.state.summary = None
            mock_get.return_value = mock_engine

            resp = client.get("/api/status")
            assert resp.status_code == 200
            data = resp.json()
            assert data["running"] is True


class TestApiStart:
    def test_start_no_running_session(self, client):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("root_directory: /tmp\nmodel:\n  base_url: http://test/v1\n  model_name: test\n")
            config_path = f.name

        original_config = server_module.CONFIG_PATH
        original_engine = server_module._engine
        server_module.CONFIG_PATH = config_path
        server_module._engine = None

        try:
            with patch("exif_tagger.server.PipelineEngine") as mock_engine_cls:
                mock_instance = MagicMock()
                mock_instance.state.running = False
                mock_instance._load_config.return_value.root_directory = "/tmp"
                mock_engine_cls.return_value = mock_instance

                resp = client.post("/api/start", json={"rootDirectory": "/tmp/images", "maxImages": 50})
                assert resp.status_code == 200
                data = resp.json()
                assert data["status"] == "started"
        finally:
            server_module.CONFIG_PATH = original_config
            server_module._engine = original_engine
            os.unlink(config_path)

    def test_start_already_running(self, client):
        # Set _engine to a state where running=True (the endpoint checks the global directly)
        mock_engine = MagicMock()
        mock_engine.state.running = True
        server_module._engine = mock_engine

        resp = client.post("/api/start", json={})
        assert resp.status_code == 409


class TestApiStop:
    def test_stop_no_session(self, client):
        with patch.object(server_module, "_get_engine") as mock_get:
            mock_engine = MagicMock()
            mock_engine.state.running = False
            mock_get.return_value = mock_engine

            resp = client.post("/api/stop")
            assert resp.status_code == 400

    def test_stop_with_session(self, client):
        with patch.object(server_module, "_get_engine") as mock_get:
            mock_engine = MagicMock()
            mock_engine.state.running = True
            mock_engine.stop.return_value = {"status": "stopped", "processed": 10}
            mock_get.return_value = mock_engine

            resp = client.post("/api/stop")
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "stopped"


class TestApiPauseResume:
    def test_pause_no_running_session(self, client):
        resp = client.post("/api/pause")
        assert resp.status_code == 400
        assert "No active processing session" in resp.json()["detail"]

    def test_resume_no_running_session(self, client):
        resp = client.post("/api/resume")
        assert resp.status_code == 400
        assert "No active processing session" in resp.json()["detail"]

    def test_pause_and_resume_flow(self, client, monkeypatch):
        from exif_tagger import server

        engine = server._get_engine()
        engine.state.start(10)

        # First pause succeeds
        resp = client.post("/api/pause")
        assert resp.status_code == 200
        assert resp.json()["status"] == "paused"

        # Status shows paused
        s_resp = client.get("/api/status")
        assert s_resp.status_code == 200
        assert s_resp.json()["paused"] is True
        assert s_resp.json()["running"] is True

        # Second pause fails
        resp2 = client.post("/api/pause")
        assert resp2.status_code == 400

        # Resume succeeds
        resp_resume = client.post("/api/resume")
        assert resp_resume.status_code == 200
        assert resp_resume.json()["status"] == "resumed"

        # Status shows not paused
        s_resp2 = client.get("/api/status")
        assert s_resp2.json()["paused"] is False

        # Stop while running or paused works
        resp_stop = client.post("/api/stop")
        assert resp_stop.status_code == 200
        assert resp_stop.json()["status"] == "stopped"

    def test_resume_when_not_paused(self, client):
        from exif_tagger import server

        engine = server._get_engine()
        engine.state.start(10)

        resp = client.post("/api/resume")
        assert resp.status_code == 400
        assert "Processing session is not paused" in resp.json()["detail"]

    def test_stop_when_paused(self, client):
        from exif_tagger import server

        engine = server._get_engine()
        engine.state.start(10)
        client.post("/api/pause")

        resp = client.post("/api/stop")
        assert resp.status_code == 200
        assert resp.json()["status"] == "stopped"


class TestApiConfig:
    def test_get_config(self, client):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("""root_directory: /tmp/images
model:
  base_url: http://test/v1
  model_name: gpt-4o
tags:
  landscape:
    description: Pictures of landscapes
    threshold: 0.7
exclude_patterns: []
""")
            config_path = f.name

        original_config = server_module.CONFIG_PATH
        server_module.CONFIG_PATH = config_path

        try:
            resp = client.get("/api/config")
            assert resp.status_code == 200
            data = resp.json()
            assert data["root_directory"] == "/tmp/images"
            assert "landscape" in data["tags"]
            assert data["tags"]["landscape"]["threshold"] == 0.7
            assert "image_format" in data["model"]
            assert "image_quality" in data["model"]
            assert "concurrency" in data["model"]
            assert "log_level" in data
            assert "log_dir" in data
        finally:
            server_module.CONFIG_PATH = original_config
            os.unlink(config_path)

    def test_get_and_put_config_reasoning_effort_and_fields(self, client, tmp_path):
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".yaml") as f:
            f.write(f"""root_directory: {tmp_path}
model:
  base_url: http://localhost:8000/v1
  model_name: test-model
  image_format: webp
  image_quality: 90
  concurrency: 4
  params:
    reasoning_effort: none
log_level: DEBUG
log_dir: /tmp/logs
tags: {{}}
exclude_patterns: []
""")
            config_path = f.name

        original_config = server_module.CONFIG_PATH
        server_module.CONFIG_PATH = config_path

        try:
            # Test GET /api/config returns all parameters including custom reasoning_effort
            resp = client.get("/api/config")
            assert resp.status_code == 200
            data = resp.json()
            assert data["model"]["image_format"] == "webp"
            assert data["model"]["image_quality"] == 90
            assert data["model"]["concurrency"] == 4
            assert data["model"]["params"]["reasoning_effort"] == "none"
            assert data["log_level"] == "DEBUG"
            assert data["log_dir"] == "/tmp/logs"

            # Test PUT /api/config updates parameters properly
            updates = {
                "model": {
                    "base_url": "http://localhost:8000/v1",
                    "model_name": "test-model",
                    "image_format": "jpeg",
                    "image_quality": 75,
                    "concurrency": 2,
                    "params": {
                        "reasoning_effort": "minimal_custom",
                    },
                },
                "log_level": "WARNING",
            }
            put_resp = client.put("/api/config", json=updates)
            assert put_resp.status_code == 200
            assert put_resp.json() == {"status": "updated"}

            # Verify GET after update
            resp_after = client.get("/api/config")
            assert resp_after.status_code == 200
            data_after = resp_after.json()
            assert data_after["model"]["image_format"] == "jpeg"
            assert data_after["model"]["image_quality"] == 75
            assert data_after["model"]["concurrency"] == 2
            assert data_after["model"]["params"]["reasoning_effort"] == "minimal_custom"
            assert data_after["log_level"] == "WARNING"
        finally:
            server_module.CONFIG_PATH = original_config
            os.unlink(config_path)


class TestApiSchedules:
    def test_list_empty_schedules(self, client):
        resp = client.get("/api/schedule")
        assert resp.status_code == 200
        data = resp.json()
        assert data == []

    def test_create_schedule(self, client):
        with patch.object(server_module, "_setup_scheduler"):
            with patch.object(server_module, "_save_schedules"):
                resp = client.post(
                    "/api/schedule",
                    json={
                        "name": "Daily scan",
                        "folder": "/data/images",
                        "interval_hours": 6,
                        "enabled": True,
                    },
                )
            assert resp.status_code == 200
            data = resp.json()
            assert "id" in data

    def test_delete_schedule(self, client):
        with patch.object(server_module, "_setup_scheduler"):
            with patch.object(server_module, "_save_schedules"):
                # First create a schedule
                resp = client.post(
                    "/api/schedule",
                    json={
                        "name": "Test",
                        "folder": "/data/images",
                        "interval_hours": 1,
                    },
                )
                sid = resp.json()["id"]

                # Then delete it
                resp = client.delete(f"/api/schedule/{sid}")
                assert resp.status_code == 200
                assert resp.json()["status"] == "deleted"

    def test_delete_nonexistent_schedule(self, client):
        resp = client.delete("/api/schedule/nonexistent_id")
        assert resp.status_code == 404


class TestScheduleModel:
    def test_schedule_model_defaults(self):
        s = ScheduleModel(name="test", folder="/data/images")
        assert s.enabled is True
        assert s.last_run_at is None
        assert s.interval_hours is None

    def test_schedule_cron_validation(self):
        with pytest.raises(Exception):
            ScheduleModel(
                name="bad cron",
                folder="/data/images",
                cron_expression="invalid",  # Not 5 fields
            )


class TestComputeNextRun:
    def test_interval_hours(self):
        from datetime import datetime

        schedule = ScheduleModel(name="test", folder="/data", interval_hours=6)
        next_run = server_module._compute_next_run(schedule)
        assert next_run is not None

        # Parse and verify it's roughly 6 hours ahead
        run_time = datetime.fromisoformat(next_run)
        now = datetime.now(UTC).replace(microsecond=0, second=0)
        diff = (run_time - now).total_seconds() / 3600
        assert 5.9 <= diff <= 7.0

    def test_cron_expression(self):
        schedule = ScheduleModel(name="daily", folder="/data", cron_expression="0 2 * * *")
        next_run = server_module._compute_next_run(schedule)
        assert next_run is not None


class TestApiSuppressions:
    def test_get_and_delete_suppressions(self, client, tmp_path):
        from exif_tagger.db import get_connection, init_db, record_user_suppression

        db_file = tmp_path / "test_server_suppression.db"
        init_db(db_file)

        img_path = str((tmp_path / "test_suppression.jpg").resolve())
        conn = get_connection(db_file)
        try:
            with conn:
                cursor = conn.execute(
                    "INSERT INTO images (file_path, filename, relative_path, last_modified, indexed_at) "
                    "VALUES (?, 'test.jpg', 'test.jpg', 100.0, '2026-08-07T12:00:00Z')",
                    (img_path,),
                )
                image_id = cursor.lastrowid
        finally:
            conn.close()

        record_user_suppression(image_id=image_id, tag_name="false_tag", reason="manual_test", db_path=db_file)

        with patch("exif_tagger.db.get_db_path", return_value=db_file):
            resp = client.get(f"/api/gallery/image/{image_id}/suppressions")
            assert resp.status_code == 200
            data = resp.json()
            assert "suppressions" in data
            assert len(data["suppressions"]) == 1
            assert data["suppressions"][0]["tag_name"] == "false_tag"

            del_resp = client.delete(f"/api/gallery/image/{image_id}/suppressions/false_tag")
            assert del_resp.status_code == 200

            resp_after = client.get(f"/api/gallery/image/{image_id}/suppressions")
            assert len(resp_after.json()["suppressions"]) == 0


def test_get_schedules_file_path_data_dir(monkeypatch, tmp_path):
    from exif_tagger.server import get_schedules_file_path

    monkeypatch.delenv("EXIFTAGGER_SCHEDULES_FILE", raising=False)
    monkeypatch.setenv("EXIFTAGGER_DATA_DIR", str(tmp_path))
    assert get_schedules_file_path() == tmp_path / "schedules.json"


def test_get_schedules_file_path_override(monkeypatch, tmp_path):
    from exif_tagger.server import get_schedules_file_path

    schedules_custom = tmp_path / "custom_schedules.json"
    monkeypatch.setenv("EXIFTAGGER_SCHEDULES_FILE", str(schedules_custom))
    monkeypatch.setenv("EXIFTAGGER_DATA_DIR", str(tmp_path / "ignored"))
    assert get_schedules_file_path() == schedules_custom


class TestGalleryTask2Endpoints:
    def test_gallery_image_file_by_path(self, client, tmp_path):
        from exif_tagger.models.schema import Config as SchemaConfig
        from exif_tagger.models.schema import ModelConfig

        # Create dummy image file
        img_file = tmp_path / "test_photo.jpg"
        img_file.write_bytes(b"\xff\xd8\xff\xe0\x00\x10JFIF\x00")

        # Mock load_config to return tmp_path as root_directory
        dummy_config = SchemaConfig(
            root_directory=str(tmp_path),
            model=ModelConfig(base_url="http://test/v1", model_name="test"),
        )

        with patch("exif_tagger.server.load_config", return_value=dummy_config):
            # Test valid relative path
            resp = client.get("/api/gallery/image/file?path=test_photo.jpg")
            assert resp.status_code == 200
            assert resp.content == b"\xff\xd8\xff\xe0\x00\x10JFIF\x00"

            # Test path outside root_directory (security boundary)
            resp_sec = client.get("/api/gallery/image/file?path=../outside.jpg")
            assert resp_sec.status_code == 403

            # Test file not found
            resp_404 = client.get("/api/gallery/image/file?path=nonexistent.jpg")
            assert resp_404.status_code == 404

            # Test invalid extension
            bad_file = tmp_path / "script.py"
            bad_file.write_text("print('hello')")
            resp_ext = client.get("/api/gallery/image/file?path=script.py")
            assert resp_ext.status_code == 400

    def test_gallery_sync_single_image_endpoint(self, client, tmp_path):
        from exif_tagger.db import init_db
        from exif_tagger.models.schema import Config as SchemaConfig
        from exif_tagger.models.schema import ModelConfig

        db_file = tmp_path / "test_single_sync.db"
        init_db(db_file)

        img_file = tmp_path / "single_test.jpg"
        img_file.write_bytes(b"\xff\xd8\xff\xe0\x00\x10JFIF\x00")

        dummy_config = SchemaConfig(
            root_directory=str(tmp_path),
            model=ModelConfig(base_url="http://test/v1", model_name="test"),
        )

        with (
            patch("exif_tagger.server.load_config", return_value=dummy_config),
            patch("exif_tagger.db.get_db_path", return_value=db_file),
        ):
            resp = client.post("/api/gallery/image/sync", json={"relative_path": "single_test.jpg"})
            assert resp.status_code == 200
            data = resp.json()
            assert data["indexed"] is True
            assert data["relative_path"] == "single_test.jpg"
            assert data["id"] is not None

            # Test missing file
            resp_missing = client.post("/api/gallery/image/sync", json={"relative_path": "missing.jpg"})
            assert resp_missing.status_code == 404

    def test_gallery_sync_filtered_mode(self, client, tmp_path):
        import time

        from exif_tagger.db import init_db, reconcile_gallery_index
        from exif_tagger.models.schema import Config as SchemaConfig
        from exif_tagger.models.schema import ModelConfig

        db_file = tmp_path / "test_filtered_sync.db"
        init_db(db_file)

        # Create image files
        sub_dir = tmp_path / "sub"
        sub_dir.mkdir()
        (tmp_path / "root_img.jpg").write_bytes(b"\xff\xd8\xff\xe0\x00\x10JFIF\x00")
        (sub_dir / "sub_img.jpg").write_bytes(b"\xff\xd8\xff\xe0\x00\x10JFIF\x00")

        reconcile_gallery_index(tmp_path, db_path=db_file)

        dummy_config = SchemaConfig(
            root_directory=str(tmp_path),
            model=ModelConfig(base_url="http://test/v1", model_name="test"),
        )

        with (
            patch("exif_tagger.server.load_config", return_value=dummy_config),
            patch("exif_tagger.db.get_db_path", return_value=db_file),
        ):
            resp = client.post("/api/gallery/sync", json={"mode": "filtered", "folder": "sub"})
            assert resp.status_code == 200
            assert resp.json()["status"] == "started"

            # Wait for background thread
            for _ in range(20):
                status_resp = client.get("/api/gallery/sync/status")
                sdata = status_resp.json()
                if sdata["status"] == "complete":
                    break
                time.sleep(0.1)

            assert sdata["status"] == "complete"
            assert sdata["stats"]["total"] == 1
            assert sdata["stats"]["indexed"] == 1


def test_gallery_index_poller_registered(monkeypatch, tmp_path):
    """With the default config, the poller job is registered on startup."""
    import exif_tagger.server as server_module
    from exif_tagger.server import _setup_scheduler

    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        f"root_directory: {tmp_path}\n"
        "model:\n"
        "  base_url: http://test/v1\n"
        "  model_name: test\n"
        "gallery_index:\n"
        "  enabled: true\n"
        "  poll_interval_seconds: 10\n"
    )

    monkeypatch.setattr("exif_tagger.server.CONFIG_PATH", str(cfg))
    _setup_scheduler()
    try:
        job = server_module._scheduler.get_job("gallery_index_poll")
        assert job is not None
    finally:
        server_module._scheduler.shutdown(wait=False)


def test_poll_refreshes_index_and_reads(tmp_path):
    """A reconcile round makes a newly added file visible to the gallery API."""
    from exif_tagger.db import reconcile_gallery_index
    from exif_tagger.models.schema import Config as SchemaConfig
    from exif_tagger.models.schema import ModelConfig

    gallery = tmp_path / "gallery"
    gallery.mkdir()
    (gallery / "a.jpg").write_bytes(b"\xff\xd8\xff\xe0\x00\x10JFIF\x00")

    dummy_config = SchemaConfig(
        root_directory=str(gallery),
        model=ModelConfig(base_url="http://t/v1", model_name="t"),
    )

    with (
        patch("exif_tagger.server.load_config", return_value=dummy_config),
        patch("exif_tagger.server.CONFIG_PATH", str(tmp_path / "config.yaml")),
        TestClient(server_module.app) as client,
    ):
        # Startup reconcile seeded the index.
        assert client.get("/api/gallery/images").json()["total"] == 1

        # A file added on disk after startup shows up after one reconcile round.
        (gallery / "b.jpg").write_bytes(b"\xff\xd8\xff\xe0\x00\x10JFIF\x00")
        reconcile_gallery_index(gallery, db_path=None)
        assert client.get("/api/gallery/images").json()["total"] == 2
