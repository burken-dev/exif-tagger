import logging
from pathlib import Path
from unittest.mock import patch

from exif_tagger.ai_client import setup_secure_logging
from exif_tagger.main import PipelineEngine
from exif_tagger.models.schema import Config, ModelConfig

DUMMY_MODEL = ModelConfig(base_url="http://localhost:11434/v1", model_name="gpt-4o")


def test_setup_logging_from_config(tmp_path):
    logger = logging.getLogger("exif_tagger")
    logger.handlers.clear()
    log_dir = str(tmp_path / "cli_logs")
    cfg = Config(root_directory=".", model=DUMMY_MODEL, log_level="DEBUG", log_dir=log_dir)
    setup_secure_logging(level=cfg.log_level, log_dir=cfg.log_dir, logger_name="exif_tagger")

    assert logger.level == logging.DEBUG
    log_file = Path(log_dir) / "exif-tagger.log"
    assert log_file.exists()


def test_pipeline_engine_uses_config_logging(tmp_path):
    log_dir = str(tmp_path / "engine_logs")
    dummy_config = Config(
        root_directory=str(tmp_path),
        model=DUMMY_MODEL,
        log_level="DEBUG",
        log_dir=log_dir,
        tags={"cat": {"description": "a feline", "threshold": 0.5}},
    )

    engine = PipelineEngine(config_path="config.yaml", verbose=False)

    with patch.object(engine, "_load_config", return_value=dummy_config):
        with patch("exif_tagger.main.setup_secure_logging") as mock_setup_logging:
            with patch("exif_tagger.db.sync_gallery_index", return_value={"total": 0}):
                summary = engine.start_session()
                mock_setup_logging.assert_called_with(level="DEBUG", log_dir=log_dir)


def test_server_startup_configures_logging(tmp_path):
    log_dir = str(tmp_path / "server_logs")
    dummy_config = Config(
        root_directory=".",
        model=DUMMY_MODEL,
        log_level="WARNING",
        log_dir=log_dir,
    )

    with patch("exif_tagger.server.load_config", return_value=dummy_config):
        with patch("exif_tagger.server.setup_secure_logging") as mock_setup_logging:
            import asyncio

            from exif_tagger.server import app, lifespan

            async def run_lifespan():
                async with lifespan(app):
                    pass

            asyncio.run(run_lifespan())
            mock_setup_logging.assert_called_with(level="WARNING", log_dir=log_dir)
