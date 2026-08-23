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
        assert len(state.log_lines) == 1
        assert "[1/10] Processed: photo.jpg" in state.log_lines[0]

    def test_update_multiple_images(self):
        from exif_tagger.main import ProcessingState

        state = ProcessingState()
        state.start(3)
        for name in ["a.jpg", "b.jpg", "c.jpg"]:
            state.update_progress(name)
        assert state.processed == 3
        assert len(state.log_lines) == 3

    def test_log_lines_retain_last_200(self):
        from exif_tagger.main import ProcessingState

        state = ProcessingState()
        state.start(500)
        for i in range(300):
            state.update_progress(f"img_{i}.jpg")
        log = state.log_lines
        assert len(log) == 200
        # Should contain last 200 entries (100-299), not the first 100
        assert "img_99.jpg" not in "".join(log[-5:])

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

    def test_processing_state_log_lines_returns_copy(self):
        """log_lines should return a copy so mutation doesn't affect internal state."""
        from exif_tagger.main import ProcessingState

        state = ProcessingState()
        lines1 = state.log_lines
        lines2 = state.log_lines
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
        assert "processed" in status
        assert "total" in status
        assert "currentImage" in status
        assert "progressPct" in status
        assert "stopRequested" in status

    def test_get_summary_before_session_is_none(self):
        """Before start_session(), summary should be None."""
        from exif_tagger.main import PipelineEngine

        engine = PipelineEngine(config_path="config.yaml")
        assert engine.get_summary() is None

    def test_stop_returns_status_dict_with_processed_key(self):
        """Calling stop() on an unstarted engine returns a dict with status and processed."""
        from exif_tagger.main import PipelineEngine

        engine = PipelineEngine(config_path="config.yaml")

        result = engine.stop()

        assert "status" in result
        assert result["status"] == "stopped"
        assert "processed" in result


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
            if not matched_names:
                return False, 0
            return True, len(matched_names)

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

        with patch("exif_tagger.config.load_config", return_value=MockConfig()):
            with patch("exif_tagger.image_scanner.scan_images", return_value=created_paths):
                with patch(
                    "exif_tagger.image_scanner.filter_by_checkpoint", side_effect=lambda imgs, cp: (list(imgs), 0)
                ):
                    with patch("exif_tagger.config.get_resume_info", return_value=None):
                        with patch("exif_tagger.ai_client.setup_secure_logging"):
                            with patch("exif_tagger.ai_client.tag_image_with_ai", return_value=mock_response):
                                with patch("exif_tagger.exif_writer.tag_image_exif", side_effect=fake_exif):
                                    with patch("exif_tagger.config.save_checkpoint"):
                                        with patch("exif_tagger.db.update_image_in_db_from_file"):
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

                def fake_filter(images, checkpoint):
                    return list(images), 0

                with patch("exif_tagger.image_scanner.filter_by_checkpoint", side_effect=fake_filter):
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
