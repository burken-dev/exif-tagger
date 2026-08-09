import pytest

from exif_tagger.config import load_config
from exif_tagger.models.schema import Config, ModelConfig

DUMMY_MODEL = ModelConfig(base_url="http://localhost:11434/v1", model_name="gpt-4o")


def test_config_default_log_settings():
    cfg = Config(root_directory=".", model=DUMMY_MODEL)
    assert cfg.log_level == "INFO"
    assert cfg.log_dir == "/app/logs"


def test_config_custom_log_level_uppercase():
    cfg = Config(root_directory=".", model=DUMMY_MODEL, log_level="debug")
    assert cfg.log_level == "DEBUG"


def test_config_invalid_log_level():
    with pytest.raises(ValueError, match="Invalid log level"):
        Config(root_directory=".", model=DUMMY_MODEL, log_level="INVALID_LEVEL")


def test_config_env_log_settings(monkeypatch, tmp_path):
    monkeypatch.setenv("EXIFTAGGER_LOG_LEVEL", "warning")
    monkeypatch.setenv("EXIFTAGGER_LOG_DIR", "/custom/logs")

    config_file = tmp_path / "config.yaml"
    config_file.write_text("root_directory: '.'\nmodel:\n  base_url: http://localhost:11434/v1\n  model_name: gpt-4o\n")

    cfg = load_config(config_file)
    assert cfg.log_level == "WARNING"
    assert cfg.log_dir == "/custom/logs"
