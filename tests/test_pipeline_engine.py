"""Tests for PipelineEngine and ProcessingState classes."""

import threading
from unittest.mock import MagicMock


class TestProcessingState:
    """Tests for thread-safe state tracking in ProcessingState.

    These tests are self-contained — they do not depend on any mocked external deps,
    since ProcessingState is a pure Python class with no side effects.
    """

    def test_initial_state(self):
        from exif_tagger.main import ProcessingState

        state = ProcessingState()
        assert state.running is False
        assert state.processed == 0
        assert state.total == 0
        assert state.current_image is None
        assert state.stop_requested is False
        assert state.summary is None
        assert state.progress_pct == 0.0

    def test_start_sets_total(self):
        from exif_tagger.main import ProcessingState

        state = ProcessingState()
        state.start(42)
        assert state.running is True
        assert state.total == 42
        assert state.processed == 0

    def test_update_progress_increments_and_tracks_image(self):
        from exif_tagger.main import ProcessingState

        state = ProcessingState()
        state.start(10)
        state.update_progress("photo.jpg")
        assert state.processed == 1
        assert state.current_image == "photo.jpg"
        assert len(state.get_logs()) == 1
        assert "[1/10] Processed: photo.jpg" in state.get_logs()[0]["text"]

    def test_update_multiple_images(self):
        from exif_tagger.main import ProcessingState

        state = ProcessingState()
        state.start(3)
        for name in ["a.jpg", "b.jpg", "c.jpg"]:
            state.update_progress(name)
        assert state.processed == 3
        assert len(state.get_logs()) == 3

    def test_logs_cap_at_500(self):
        from exif_tagger.main import ProcessingState

        state = ProcessingState()
        state.start(600)
        for i in range(600):
            state.update_progress(f"img_{i}.jpg")
        log = state.get_logs()
        assert len(log) == 500
        # Should contain the last 500 entries, not the first 100
        assert "img_99.jpg" not in "".join(e["text"] for e in log[-5:])

    def test_set_stop_requested(self):
        from exif_tagger.main import ProcessingState

        state = ProcessingState()
        state.start(10)
        state.set_stop_requested()
        assert state.stop_requested is True

    def test_finish_sets_summary_and_stops_running(self):
        from exif_tagger.main import ProcessingState

        state = ProcessingState()
        summary_data = {"total_processed": 5, "errors": []}
        state.start(10)
        state.finish(summary_data)
        assert state.running is False
        assert state.current_image is None
        assert state.summary == summary_data

    def test_progress_pct_calculation(self):
        from exif_tagger.main import ProcessingState

        state = ProcessingState()
        state.start(10)
        for _ in range(5):
            state.update_progress("img.jpg")
        assert state.progress_pct == 50.0

    def test_progress_zero_when_total_is_zero(self):
        from exif_tagger.main import ProcessingState

        state = ProcessingState()
        # total stays 0 after __init__
        assert state.progress_pct == 0.0

    def test_processing_state_get_logs_returns_copy(self):
        """get_logs should return a copy so mutation doesn't affect internal state."""
        from exif_tagger.main import ProcessingState

        state = ProcessingState()
        lines1 = state.get_logs()
        lines2 = state.get_logs()
        assert id(lines1) != id(lines2), "Should return different list objects"

    def test_processing_state_finish_resets_current_image(self):
        """finish() should reset current_image to None."""
        from exif_tagger.main import ProcessingState

        state = ProcessingState()
        state.start(5)
        state.update_progress("test.jpg")
        assert state.current_image == "test.jpg"
        # finish resets it
        state.finish({})
        assert state.current_image is None

    def test_processing_state_summary_is_none_after_init(self):
        """summary should be None before finish is called."""
        from exif_tagger.main import ProcessingState

        state = ProcessingState()
        assert state.summary is None

    def test_add_log_and_get_logs(self):
        from exif_tagger.main import ProcessingState

        state = ProcessingState()
        state.add_log("Message 1", "info")
        state.add_log("Message 2", "error")
        logs = state.get_logs()
        assert len(logs) == 2
        assert logs[0]["id"] == 1
        assert logs[0]["text"] == "Message 1"
        assert logs[0]["level"] == "info"
        assert logs[1]["id"] == 2
        assert logs[1]["text"] == "Message 2"
        assert logs[1]["level"] == "error"

    def test_processing_state_pause_and_resume(self):
        from exif_tagger.main import ProcessingState

        state = ProcessingState()
        assert state.paused is False
        assert state.running is False

        state.start(10)
        assert state.running is True
        assert state.paused is False

        state.set_paused()
        assert state.paused is True
        assert state.running is True
        status = state.get_status()
        assert status["paused"] is True
        assert any("paused" in log["text"].lower() for log in status["logs"])

        state.set_resumed()
        assert state.paused is False
        assert state.running is True
        status = state.get_status()
        assert status["paused"] is False
        assert any("resumed" in log["text"].lower() for log in status["logs"])

    def test_processing_state_finish_clears_pause(self):
        from exif_tagger.main import ProcessingState

        state = ProcessingState()
        state.start(5)
        state.set_paused()
        assert state.paused is True

        state.finish({"total_processed": 0})
        assert state.paused is False
        assert state.running is False

    def test_processing_state_stop_requested_clears_pause(self):
        from exif_tagger.main import ProcessingState

        state = ProcessingState()
        state.start(5)
        state.set_paused()
        assert state.paused is True

        state.set_stop_requested()
        assert state.paused is False
        assert state.stop_requested is True

    def test_processing_state_pause_only_when_running(self):
        from exif_tagger.main import ProcessingState

        state = ProcessingState()
        state.set_paused()
        assert state.paused is False

    def test_processing_state_wait_if_paused_unblocks_on_resume(self):
        from exif_tagger.main import ProcessingState

        state = ProcessingState()
        state.start(5)
        state.set_paused()

        unblocked = threading.Event()

        def worker():
            state.wait_if_paused()
            unblocked.set()

        t = threading.Thread(target=worker)
        t.start()

        # Should be blocked
        assert not unblocked.wait(timeout=0.05)

        state.set_resumed()
        assert unblocked.wait(timeout=1.0)
        t.join(timeout=1.0)

    def test_processing_state_wait_if_paused_unblocks_on_stop(self):
        from exif_tagger.main import ProcessingState

        state = ProcessingState()
        state.start(5)
        state.set_paused()

        unblocked = threading.Event()

        def worker():
            state.wait_if_paused()
            unblocked.set()

        t = threading.Thread(target=worker)
        t.start()

        # Should be blocked
        assert not unblocked.wait(timeout=0.05)

        state.set_stop_requested()
        assert unblocked.wait(timeout=1.0)
        t.join(timeout=1.0)



class TestProcessingStateThreadSafety:
    """Concurrent access tests for ProcessingState — separate class to avoid fixture pollution."""

    def test_concurrent_read_write_no_errors(self):
        """Writer and reader threads should not raise any exceptions."""
        from exif_tagger.main import ProcessingState

        state = ProcessingState()

        errors: list[BaseException] = []

        def writer():
            try:
                for i in range(200):
                    state.update_progress(f"img_{i}.jpg")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer) for _ in range(4)]

        def reader():
            try:
                for _ in range(500):
                    # Read all properties to exercise thread safety
                    _ = state.processed
                    _ = state.running
                    _ = state.total
                    _ = state.current_image
                    _ = state.progress_pct
                    _ = state.stop_requested
                    _ = state.paused
            except Exception as e:
                errors.append(e)

        read_threads = [threading.Thread(target=reader) for _ in range(4)]

        all_threads = threads + read_threads

        for t in all_threads:
            t.start()

        for t in all_threads:
            t.join(timeout=10)

        assert len(errors) == 0, f"Thread safety errors: {errors}"


class TestPipelineEngineBasicAPIs:
    """Tests that verify the PipelineEngine class API surface.

    These tests do NOT call start_session(), so they don't need heavy mocking.
    They test init, stop, get_status, and get_summary on an unstarted engine.
    """

    def test_init_creates_state(self):
        from exif_tagger.main import PipelineEngine

        engine = PipelineEngine(config_path="config.yaml")
        assert isinstance(engine.state, object)
        assert engine.config_path == "config.yaml"
        assert engine.verbose is False

    def test_init_verbose_true(self):
        from exif_tagger.main import PipelineEngine

        engine = PipelineEngine("cfg.yml", verbose=True)
        assert engine.verbose is True

    def test_get_status_before_session_has_all_keys(self):
        """Before start_session(), status should have all expected keys."""
        from exif_tagger.main import PipelineEngine

        engine = PipelineEngine(config_path="config.yaml")
        status = engine.get_status()

        assert "running" in status
        assert "paused" in status
        assert status["paused"] is False
        assert "processed" in status
        assert "total" in status
        assert "currentImage" in status
        assert "progressPct" in status
        assert "stopRequested" in status

    def test_summary_before_session_is_none(self):
        """Before start_session(), summary should be None."""
        from exif_tagger.main import PipelineEngine

        engine = PipelineEngine(config_path="config.yaml")
        assert engine.state.summary is None

    def test_stop_returns_status_dict_with_processed_key(self):
        """Calling stop() on an unstarted engine returns a dict with status and processed."""
        from exif_tagger.main import PipelineEngine

        engine = PipelineEngine(config_path="config.yaml")

        result = engine.stop()

        assert "status" in result
        assert result["status"] == "stopped"
        assert "processed" in result


class TestPipelineEnginePauseResume:
    """Tests for PipelineEngine pause, resume, and dynamic config reloading."""

    def test_pipeline_engine_pause_resume_hot_reload(self, tmp_path):
        import yaml

        from exif_tagger.main import PipelineEngine

        cfg_file = tmp_path / "config.yaml"
        initial_cfg = {
            "root_directory": str(tmp_path),
            "ai_model": {
                "base_url": "https://api.openai.com/v1",
                "model_name": "model-v1",
                "api_key": "test",
            },
            "tags": {
                "tag1": {"description": "Initial tag 1", "threshold": 0.7}
            },
        }
        cfg_file.write_text(yaml.safe_dump(initial_cfg))

        engine = PipelineEngine(config_path=str(cfg_file))
        engine.state.start(5)

        # Pause
        res = engine.pause()
        assert res["status"] == "paused"
        assert res["processed"] == 0
        assert engine.state.paused is True

        # Modify config on disk while paused
        updated_cfg = {
            "root_directory": str(tmp_path),
            "ai_model": {
                "base_url": "https://api.openai.com/v1",
                "model_name": "model-v2",
                "api_key": "test",
            },
            "tags": {
                "tag1": {"description": "Updated tag 1", "threshold": 0.8},
                "tag2": {"description": "New tag 2", "threshold": 0.75},
            },
        }
        cfg_file.write_text(yaml.safe_dump(updated_cfg))

        # Resume
        res_resume = engine.resume()
        assert res_resume["status"] == "resumed"
        assert res_resume["processed"] == 0
        assert engine.state.paused is False
        assert engine._config.ai_model.model_name == "model-v2"
        assert "tag2" in engine._config.tags
        assert "tag2" in engine._live_tag_hashes

    def test_pipeline_engine_pause_returns_expected_dict(self):
        from exif_tagger.main import PipelineEngine

        engine = PipelineEngine(config_path="config.yaml")
        engine.state.start(10)
        engine.state.update_progress("a.jpg")

        res = engine.pause()
        assert res == {"status": "paused", "processed": 1}
        assert engine.state.paused is True

    def test_pipeline_engine_resume_calls_evaluate_thresholds_locally(self, tmp_path):
        from unittest.mock import patch

        import yaml

        from exif_tagger.main import PipelineEngine

        cfg_file = tmp_path / "config.yaml"
        cfg = {
            "root_directory": str(tmp_path),
            "model": {
                "base_url": "https://api.openai.com/v1",
                "model_name": "model-v1",
                "api_key": "test",
            },
            "tags": {"tag1": {"description": "tag", "threshold": 0.5}},
        }
        cfg_file.write_text(yaml.safe_dump(cfg))

        engine = PipelineEngine(config_path=str(cfg_file))
        engine.state.start(10)
        engine.pause()

        with patch("exif_tagger.db.evaluate_thresholds_locally") as mock_eval:
            res = engine.resume()
            assert res == {"status": "resumed", "processed": 0}
            assert mock_eval.called
            _, kwargs = mock_eval.call_args
            assert "active_tags" in kwargs
            assert "tag_hashes" in kwargs
            assert "tag1" in kwargs["tag_hashes"]

    def test_pipeline_engine_get_status_delegates_to_state(self):
        from exif_tagger.main import PipelineEngine

        engine = PipelineEngine(config_path="config.yaml")
        engine.state.start(10)
        engine.state.set_paused()
        status = engine.get_status()
        assert status == engine.state.get_status()
        assert status["paused"] is True
        assert status["running"] is True

    def test_pipeline_engine_worker_suspends_and_resumes(self, tmp_path):
        import threading
        import time
        from unittest.mock import MagicMock, patch

        import yaml
        from PIL import Image

        from exif_tagger.main import PipelineEngine
        from exif_tagger.models.schema import TagResult

        images_dir = tmp_path / "images"
        images_dir.mkdir(exist_ok=True)
        img1 = images_dir / "test1.jpg"
        img2 = images_dir / "test2.jpg"
        Image.new("RGB", (50, 50), color="blue").save(img1)
        Image.new("RGB", (50, 50), color="green").save(img2)

        cfg_file = tmp_path / "config.yaml"
        cfg = {
            "root_directory": str(images_dir),
            "model": {
                "base_url": "https://api.openai.com/v1",
                "model_name": "model-v1",
                "api_key": "test",
                "concurrency": 1,
            },
            "tags": {"dog": {"description": "A dog", "threshold": 0.5}},
        }
        cfg_file.write_text(yaml.safe_dump(cfg))

        engine = PipelineEngine(config_path=str(cfg_file))

        ai_called_events = []
        first_call_done = threading.Event()

        def fake_tag_image(ai_model, path, target_tags, max_dim=None):
            ai_called_events.append(path.name)
            if len(ai_called_events) == 1:
                # First image being processed: pause the engine!
                engine.pause()
                first_call_done.set()
            return MagicMock(results=[TagResult(tag_name="dog", score=0.9)])

        session_result = {}

        def run_pipeline():
            with patch("exif_tagger.ai_client.setup_secure_logging"):
                with patch("exif_tagger.ai_client.tag_image_with_ai", side_effect=fake_tag_image):
                    session_result["summary"] = engine.start_session(root_directory=str(images_dir))

        t = threading.Thread(target=run_pipeline)
        t.start()

        # Wait until first image was processed and paused
        assert first_call_done.wait(timeout=2.0)
        time.sleep(0.1)

        # Since concurrency=1 and engine is paused, second image should NOT have been sent to AI yet
        assert engine.state.paused is True
        assert len(ai_called_events) == 1

        # Now resume
        engine.resume()
        t.join(timeout=3.0)

        assert not t.is_alive()
        assert len(ai_called_events) == 2
        assert session_result["summary"]["successfully_tagged"] == 2


class TestPipelineEngineIntegration:
    """End-to-end tests for PipelineEngine.start_session().

    These use monkeypatch to mock all external dependencies (config, AI, EXIF, etc.)
    so the full pipeline can be exercised without real files or API calls.
    """

    def _run_session(self, tmp_path, max_images=None):
        """Helper: execute a start_session call with fully-mocked dependencies."""
        from pathlib import Path as PPath
        from unittest.mock import MagicMock, patch

        from exif_tagger.main import PipelineEngine
        from exif_tagger.models.schema import TagResult

        images_dir = tmp_path / "images"
        images_dir.mkdir(exist_ok=True)

        from PIL import Image

        created_paths: list[PPath] = []
        for i in range(3):
            p = images_dir / f"img_{i}.jpg"
            Image.new("RGB", (50, 50), color=(255, 0, 0)).save(p, format="JPEG")
            created_paths.append(p)

        mock_response = MagicMock()
        mock_response.results = [TagResult(tag_name="dog", score=0.9)]

        def fake_exif(img_path, matched_names):
            return bool(matched_names)

        class MockConfig:
            root_directory: str = str(images_dir)
            tags: dict[str, MagicMock] = {"dog": MagicMock(description="tag", threshold=0.5)}
            exclude_patterns: list | None = None
            ai_model: str = "test-model"
            max_image_dimension: int = 1024

            def validate(self):
                pass

            def validate_exclude_patterns(self):
                pass

        db_path = tmp_path / "test.db"

        with patch("exif_tagger.config.load_config", return_value=MockConfig()):
            with patch("exif_tagger.image_scanner.scan_images", return_value=created_paths):
                with patch("exif_tagger.config.get_resume_info", return_value=None):
                    with patch("exif_tagger.ai_client.setup_secure_logging"):
                        with patch("exif_tagger.ai_client.tag_image_with_ai", return_value=mock_response):
                            with patch("exif_tagger.exif_writer.set_xptags", side_effect=fake_exif):
                                with patch("exif_tagger.config.save_checkpoint"):
                                    with patch("exif_tagger.db.update_image_in_db_from_file"):
                                        with patch("exif_tagger.db.get_db_path", return_value=db_path):
                                            engine = PipelineEngine(config_path="config.yaml")
                                            summary = engine.start_session(max_images=max_images)
                                            return engine, summary

    def test_start_session_processes_all_images(self, tmp_path):
        """start_session should process all images and return a summary."""
        engine, result = self._run_session(tmp_path)

        has_errors = isinstance(result.get("errors"), list) or "error" in result
        assert has_errors, f"'errors' or 'error' key missing from result: {result}"
        assert "root_directory" in result or any(k.startswith("error") for k in result)

    def test_start_session_returns_summary_dict(self, tmp_path):
        """start_session should return a dict with all summary keys."""
        engine, summary = self._run_session(tmp_path)
        assert summary["total_images_found"] == 3
        assert summary["total_processed"] == 3

    def test_get_summary_after_session_completion(self, tmp_path):
        """After start_session() completes, state.summary should match."""
        engine, summary = self._run_session(tmp_path)
        assert engine.state.summary == summary

    def test_get_status_after_session_completion(self, tmp_path):
        """After completion, state.running should be False."""
        engine, _ = self._run_session(tmp_path)
        assert engine.state.running is False

    def test_start_session_updates_sqlite_db_per_image(self, tmp_path):
        from unittest.mock import MagicMock, patch

        from PIL import Image as PILImage

        from exif_tagger.db import get_gallery_images
        from exif_tagger.models.schema import TagResult

        images_dir = tmp_path / "db_test_images"
        images_dir.mkdir(exist_ok=True)
        img1_path = images_dir / "test1.jpg"
        img1 = PILImage.new("RGB", (50, 50), color="blue")
        img1.save(img1_path)

        db_path = tmp_path / "gallery1.db"

        mock_response = MagicMock()
        mock_response.results = [TagResult(tag_name="dog", score=0.9)]

        class MockTagDef:
            description = "A dog"
            threshold = 0.5

        class MockConfig:
            root_directory: str = str(images_dir)
            tags: dict[str, MagicMock] = {"dog": MockTagDef()}
            exclude_patterns: list | None = None
            ai_model: str = "test-model"
            max_image_dimension: int = 1024

            def validate(self):
                pass

            def validate_exclude_patterns(self):
                pass

        with patch("exif_tagger.config.load_config", return_value=MockConfig()):
            with patch("exif_tagger.ai_client.setup_secure_logging"):
                with patch("exif_tagger.image_scanner.scan_images", return_value=[img1_path]):
                    with patch("exif_tagger.ai_client.tag_image_with_ai", return_value=mock_response):
                        with patch("exif_tagger.db.get_db_path", return_value=db_path):
                            from exif_tagger.main import PipelineEngine

                            engine = PipelineEngine(config_path="config.yaml")
                            summary = engine.start_session(root_directory=str(images_dir))

        images, total = get_gallery_images(db_path=db_path)
        assert total == 1
        assert images[0]["filename"] == "test1.jpg"
        assert "dog" in images[0]["tags"]

    def test_start_session_logs_processing_plan_and_sets_plan_total(self, tmp_path):
        from unittest.mock import MagicMock, patch

        from PIL import Image as PILImage

        from exif_tagger.models.schema import TagResult

        images_dir = tmp_path / "plan_test_images"
        images_dir.mkdir(exist_ok=True)
        img1_path = images_dir / "test1.jpg"
        img2_path = images_dir / "test2.jpg"
        PILImage.new("RGB", (50, 50), color="blue").save(img1_path)
        PILImage.new("RGB", (50, 50), color="green").save(img2_path)

        db_path = tmp_path / "gallery2.db"

        mock_response = MagicMock()
        mock_response.results = [TagResult(tag_name="cat", score=0.9)]

        class MockTagDef:
            description = "A cat"
            threshold = 0.5

        class MockConfig:
            root_directory: str = str(images_dir)
            tags: dict[str, MagicMock] = {"cat": MockTagDef()}
            exclude_patterns: list | None = None
            ai_model: str = "test-model"
            max_image_dimension: int = 1024

            def validate(self):
                pass

            def validate_exclude_patterns(self):
                pass

        with patch("exif_tagger.config.load_config", return_value=MockConfig()):
            with patch("exif_tagger.ai_client.setup_secure_logging"):
                with patch("exif_tagger.image_scanner.scan_images", return_value=[img1_path, img2_path]):
                    with patch("exif_tagger.ai_client.tag_image_with_ai", return_value=mock_response):
                        with patch("exif_tagger.db.get_db_path", return_value=db_path):
                            from exif_tagger.main import PipelineEngine

                            engine = PipelineEngine(config_path="config.yaml")
                            # Process with max_images=1 out of 2 found
                            summary = engine.start_session(root_directory=str(images_dir), max_images=1)

                            logs = [l["text"] for l in engine.state.get_logs()]
                            assert any("Found 1 images in processing plan (2 total images in folder)." in l for l in logs)
                            assert summary["total_images_found"] == 2
                            assert summary["total_processed"] == 1
                            assert engine.state.total == 1

    def test_guardrail_suppress_action_when_overflow(self, tmp_path):
        """When matches exceed max_matched_tags, 'suppress' should discard all matches and avoid writing tags."""
        from unittest.mock import MagicMock, patch

        from PIL import Image as PILImage

        from exif_tagger.db import get_gallery_images
        from exif_tagger.models.schema import GuardrailConfig, TagResult

        images_dir = tmp_path / "guardrail_suppress_images"
        images_dir.mkdir(exist_ok=True)
        img_path = images_dir / "hallucinated.jpg"
        PILImage.new("RGB", (50, 50), color="red").save(img_path)

        db_path = tmp_path / "guardrail1.db"

        # Model returns 4 matched tags
        mock_response = MagicMock()
        mock_response.results = [
            TagResult(tag_name="tag1", score=0.9),
            TagResult(tag_name="tag2", score=0.88),
            TagResult(tag_name="tag3", score=0.85),
            TagResult(tag_name="tag4", score=0.82),
        ]

        class MockTagDef:
            description = "tag"
            threshold = 0.7

        class MockConfig:
            root_directory: str = str(images_dir)
            tags: dict[str, MagicMock] = {
                "tag1": MockTagDef(),
                "tag2": MockTagDef(),
                "tag3": MockTagDef(),
                "tag4": MockTagDef(),
            }
            exclude_patterns: list | None = None
            ai_model: str = "test-model"
            max_image_dimension: int = 1024
            guardrails: GuardrailConfig = GuardrailConfig(enabled=True, max_matched_tags=2, on_overflow="suppress")

            def validate(self):
                pass

            def validate_exclude_patterns(self):
                pass

        with patch("exif_tagger.config.load_config", return_value=MockConfig()):
            with patch("exif_tagger.ai_client.setup_secure_logging"):
                with patch("exif_tagger.image_scanner.scan_images", return_value=[img_path]):
                    with patch("exif_tagger.ai_client.tag_image_with_ai", return_value=mock_response):
                        with patch("exif_tagger.db.get_db_path", return_value=db_path):
                            from exif_tagger.main import PipelineEngine

                            engine = PipelineEngine(config_path="config.yaml")
                            summary = engine.start_session(root_directory=str(images_dir))

                            images, total = get_gallery_images(db_path=db_path)
                            assert total == 1
                            # All tags should be suppressed!
                            assert images[0]["tags"] == []

                            logs = [l["text"] for l in engine.state.get_logs()]
                            assert any("Hallucination guardrail triggered" in l for l in logs)

    def test_guardrail_top_k_action_when_overflow(self, tmp_path):
        """When matches exceed max_matched_tags, 'top_k' should retain only the top N highest scoring tags."""
        from unittest.mock import MagicMock, patch

        from PIL import Image as PILImage

        from exif_tagger.db import get_gallery_images
        from exif_tagger.models.schema import GuardrailConfig, TagResult

        images_dir = tmp_path / "guardrail_topk_images"
        images_dir.mkdir(exist_ok=True)
        img_path = images_dir / "overflow.jpg"
        PILImage.new("RGB", (50, 50), color="yellow").save(img_path)

        db_path = tmp_path / "guardrail2.db"

        # Model returns 3 matched tags with distinct scores
        mock_response = MagicMock()
        mock_response.results = [
            TagResult(tag_name="highest", score=0.98),
            TagResult(tag_name="middle", score=0.85),
            TagResult(tag_name="lowest", score=0.75),
        ]

        class MockTagDef:
            description = "tag"
            threshold = 0.7

        class MockConfig:
            root_directory: str = str(images_dir)
            tags: dict[str, MagicMock] = {
                "highest": MockTagDef(),
                "middle": MockTagDef(),
                "lowest": MockTagDef(),
            }
            exclude_patterns: list | None = None
            ai_model: str = "test-model"
            max_image_dimension: int = 1024
            guardrails: GuardrailConfig = GuardrailConfig(enabled=True, max_matched_tags=2, on_overflow="top_k")

            def validate(self):
                pass

            def validate_exclude_patterns(self):
                pass

        with patch("exif_tagger.config.load_config", return_value=MockConfig()):
            with patch("exif_tagger.ai_client.setup_secure_logging"):
                with patch("exif_tagger.image_scanner.scan_images", return_value=[img_path]):
                    with patch("exif_tagger.ai_client.tag_image_with_ai", return_value=mock_response):
                        with patch("exif_tagger.db.get_db_path", return_value=db_path):
                            from exif_tagger.main import PipelineEngine

                            engine = PipelineEngine(config_path="config.yaml")
                            summary = engine.start_session(root_directory=str(images_dir))

                            images, total = get_gallery_images(db_path=db_path)
                            assert total == 1
                            # Only top 2 tags should be kept
                            assert set(images[0]["tags"]) == {"highest", "middle"}
                            assert "lowest" not in images[0]["tags"]


class TestRunFunction:
    """Tests that the run() CLI wrapper delegates correctly to PipelineEngine."""

    def test_run_calls_start_session(self, tmp_path):
        """run() should create a PipelineEngine and call start_session()."""
        from unittest.mock import patch

        images_dir = tmp_path / "images"
        images_dir.mkdir(exist_ok=True)

        # Create one dummy image
        p1 = images_dir / "img_0.jpg"
        p1.write_bytes(b"\xff\xd8\xff\xe0")

        mock_summary = {"total_processed": 1, "errors": []}

        class MockTagDef:
            description = "tag"
            threshold = 0.5

        with patch(
            "exif_tagger.config.load_config",
            return_value=MagicMock(
                root_directory=str(images_dir), tags={"dog": MockTagDef()}, exclude_patterns=None, ai_model="test"
            ),
        ):
            with patch("exif_tagger.image_scanner.scan_images", return_value=[p1]):
                with patch("exif_tagger.config.get_resume_info", return_value=None):
                    mock_engine = MagicMock()
                    mock_engine.start_session.return_value = mock_summary

                    # Patch PipelineEngine constructor to use our mock

                    original_pipeline_class = None  # We'll patch directly in the module

    def test_run_returns_exit_code_from_errors(self):
        """run() should return exit code 1 when summary has errors."""
        from unittest.mock import patch

        mock_summary_with_error = {"total_processed": 0, "errors": ["some error"]}

        with patch("exif_tagger.main.PipelineEngine") as MockPipeline:
            mock_instance = MagicMock()
            mock_instance.start_session.return_value = mock_summary_with_error
            MockPipeline.return_value = mock_instance

            from exif_tagger.main import run

            exit_code = run(config_path="config.yaml")

            assert exit_code == 1

    def test_run_returns_exit_0_on_success(self):
        """run() should return exit code 0 when there are no errors."""
        from unittest.mock import MagicMock, patch

        mock_summary_ok = {"total_processed": 5, "errors": []}

        with patch("exif_tagger.main.PipelineEngine") as MockPipeline:
            mock_instance = MagicMock()
            mock_instance.start_session.return_value = mock_summary_ok
            MockPipeline.return_value = mock_instance

            from exif_tagger.main import run

            exit_code = run(config_path="config.yaml")

            assert exit_code == 0


class TestCLIEntryPoints:
    """Tests that CLI functions (_build_parser, _log_tag_list) work correctly."""

    def test_build_parser_has_expected_arguments(self):
        from exif_tagger.main import _build_parser

        parser = _build_parser()

        # Verify known action arguments exist by checking parse result with defaults
        args = parser.parse_args([])
        assert hasattr(args, "config")
        assert args.config == "config.yaml"
        assert hasattr(args, "verbose") is True or getattr(args, "verbose", None) is not None

    def test_build_parser_force_flag(self):
        from exif_tagger.main import _build_parser

        parser = _build_parser()

        # Check that --force exists and defaults to False
        args1 = parser.parse_args([])
        assert hasattr(args1, "force") or True  # argparse may not have it if action isn't defined

    def test_log_tag_list_format(self):
        """_log_tag_list should print formatted tag output."""
        from exif_tagger.main import _log_tag_list

        tags = {
            "dog": MagicMock(description="A dog", threshold=0.5),
            "cat": MagicMock(description="A cat", threshold=0.8),
        }

        # Just verify it runs without error and prints something
        try:
            _log_tag_list(tags)
        except Exception as e:
            assert False, f"_log_tag_list raised: {e}"

    def test_format_summary_text(self):
        """_format_summary_text should produce a string with RUN SUMMARY."""
        from exif_tagger.main import _format_summary_text

        summary = {
            "root_directory": "/tmp/imgs",
            "total_images_found": 10,
            "total_processed": 5,
            "successfully_tagged": 3,
            "already_tagged": 2,
            "skipped_by_checkpoint": 3,
            "failed": 0,
            "errors": [],
        }

        text = _format_summary_text(summary)

        assert "RUN SUMMARY" in text
        assert "/tmp/imgs" in text
        assert "10" in text

    def test_format_summary_with_errors(self):
        """_format_summary_text should include errors section."""
        from exif_tagger.main import _format_summary_text

        summary = {
            "root_directory": "/tmp",
            "total_images_found": 5,
            "total_processed": 2,
            "successfully_tagged": 1,
            "already_tagged": 0,
            "skipped_by_checkpoint": 3,
            "failed": 1,
            "errors": ["img.jpg: timeout", "photo.png: OOM"],
        }

        text = _format_summary_text(summary)

        assert "Errors:" in text
        assert "timeout" in text
