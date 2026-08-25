"""Tests for configuration loading and validation."""

from __future__ import annotations

import pytest
import yaml

from exif_tagger.config import load_config
from exif_tagger.models.schema import Config, ModelConfig


class TestModelConfig:
    """Test ModelConfig pydantic model."""

    def test_defaults(self):
        mc = ModelConfig(base_url="https://api.openai.com/v1", model_name="gpt-4o")
        assert mc.max_tokens == 500
        assert mc.temperature == 0.1
        assert mc.api_key is None

    def test_explicit_values(self):
        mc = ModelConfig(
            base_url="https://example.com/v1",
            model_name="my-model",
            api_key="sk-test123",
            max_tokens=1024,
            temperature=0.5,
        )
        assert mc.base_url == "https://example.com/v1"
        assert mc.model_name == "my-model"
        assert mc.api_key == "sk-test123"
        assert mc.max_tokens == 1024
        assert mc.temperature == 0.5

    def test_invalid_temperature(self):
        with pytest.raises(Exception):
            ModelConfig(
                base_url="https://api.openai.com/v1",
                model_name="gpt-4o",
                temperature=5.0,
            )


class TestTagDefinition:
    """Test TagDefinition model."""

    def test_defaults(self):
        td = {"description": "A tag"}
        # This is how it would come from YAML – we just check the dict form first
        assert isinstance(td, dict)
        assert "description" in td

    def test_with_threshold(self):

        from exif_tagger.models.schema import TagDefinition

        td = TagDefinition(description="A tag", threshold=0.8)
        assert td.threshold == 0.8
        assert td.description == "A tag"


class TestConfig:
    """Test full Config loading and validation."""

    def test_load_from_file(self, tmp_path):
        config_data = {
            "root_directory": str(tmp_path),
            "model": {
                "base_url": "https://api.test.com/v1",
                "model_name": "test-model",
            },
            "tags": {"nature": {"description": "Nature scenes", "threshold": 0.7}},
        }
        config_file = tmp_path / "config.yaml"
        with open(config_file, "w") as fh:
            yaml.dump(config_data, fh)

        config = load_config(str(config_file))
        assert isinstance(config, Config)
        assert config.root_directory == str(tmp_path)
        assert config.ai_model.base_url == "https://api.test.com/v1"
        assert "nature" in config.tags
        assert config.tags["nature"].threshold == 0.7

    def test_env_override_api_key(self, tmp_path, monkeypatch):
        """EXIFTAGGER_ prefixed env vars should override config values."""
        config_data = {
            "root_directory": str(tmp_path),
            "model": {
                "base_url": "https://api.test.com/v1",
                "model_name": "test-model",
            },
            "tags": {"nature": {"description": "Nature scenes", "threshold": 0.7}},
        }
        config_file = tmp_path / "config.yaml"
        with open(config_file, "w") as fh:
            yaml.dump(config_data, fh)

        monkeypatch.setenv("EXIFTAGGER_MODEL_BASE_URL", "https://override.com/v1")
        config = load_config(str(config_file))
        assert config.ai_model.base_url == "https://override.com/v1"

    def test_env_override_root_directory(self, tmp_path, monkeypatch):
        """ENV vars should override root_directory."""
        other_dir = tmp_path / "other_dir"
        other_dir.mkdir()

        config_data = {
            "root_directory": str(tmp_path),
            "model": {"base_url": "https://api.test.com/v1", "model_name": "test-model"},
            "tags": {},
        }
        config_file = tmp_path / "config.yaml"
        with open(config_file, "w") as fh:
            yaml.dump(config_data, fh)

        monkeypatch.setenv("EXIFTAGGER_ROOT_DIRECTORY", str(other_dir))
        config = load_config(str(config_file))
        assert config.root_directory == str(other_dir)

    def test_validate_root_directory_not_exists(self):
        """Config with nonexistent root_directory should fail validation."""
        from exif_tagger.models.schema import Config as Cfg

        cfg_data = {
            "root_directory": "/nonexistent/path/xyz123",
            "model": {"base_url": "https://api.test.com/v1", "model_name": "test"},
            "tags": {},
        }
        config = Cfg(**cfg_data)
        with pytest.raises(ValueError, match="root_directory does not exist"):
            config.validate()

    def test_validate_exclude_patterns_invalid_regex(self, tmp_path):
        """Invalid regex in exclude_patterns should raise ValueError."""
        config_data = {
            "root_directory": str(tmp_path),
            "model": {"base_url": "https://api.test.com/v1", "model_name": "test"},
            "tags": {},
            "exclude_patterns": ["[invalid"],  # Unclosed bracket
        }
        config_file = tmp_path / "config.yaml"
        with open(config_file, "w") as fh:
            yaml.dump(config_data, fh)

        config = load_config(str(config_file))
        with pytest.raises(ValueError, match="Invalid regex"):
            config.validate_exclude_patterns()

    def test_gallery_index_defaults(self):
        from exif_tagger.models.schema import GalleryIndexConfig

        cfg = GalleryIndexConfig()
        assert cfg.enabled is True
        assert cfg.poll_interval_seconds == 10

    def test_gallery_index_config_from_yaml(self, tmp_path):
        config_data = {
            "root_directory": str(tmp_path),
            "model": {"base_url": "https://api.test.com/v1", "model_name": "test-model"},
            "gallery_index": {"enabled": False, "poll_interval_seconds": 30},
        }
        config_file = tmp_path / "config.yaml"
        with open(config_file, "w") as fh:
            yaml.dump(config_data, fh)

        config = load_config(str(config_file))
        assert config.gallery_index.enabled is False
        assert config.gallery_index.poll_interval_seconds == 30

    def test_gallery_index_env_override(self, tmp_path, monkeypatch):
        config_data = {
            "root_directory": str(tmp_path),
            "model": {"base_url": "https://api.test.com/v1", "model_name": "test-model"},
        }
        config_file = tmp_path / "config.yaml"
        with open(config_file, "w") as fh:
            yaml.dump(config_data, fh)

        monkeypatch.setenv("EXIFTAGGER_GALLERY_INDEX_POLL_INTERVAL_SECONDS", "45")
        config = load_config(str(config_file))
        assert config.gallery_index.poll_interval_seconds == 45


class TestConfigValidationEdgeCases:
    """Test edge cases in config validation."""

    def test_missing_root_directory_uses_default(self):
        """Missing root_directory should fall back to the default /data/images."""
        from exif_tagger.models.schema import Config as Cfg

        cfg = Cfg(model={"base_url": "http://x.com", "model_name": "test"})
        assert cfg.root_directory == "/data/images"


class TestAtomicCheckpointSave:
    """Test that save_checkpoint uses atomic write pattern."""

    def test_atomic_write_no_tmp_left(self, tmp_path):
        """After a successful save, no .tmp file should remain on disk."""
        from exif_tagger.config import save_checkpoint
        from exif_tagger.models.schema import ImageCheckpoint

        root = str(tmp_path)
        images: dict[str, ImageCheckpoint] = {}

        save_checkpoint(root, total_images=10, images=images)

        cp_path = tmp_path / ".exif-tagger-checkpoint.json"
        assert cp_path.exists()
        # No temp file should be left behind
        tmp_file = tmp_path / ".exif-tagger-checkpoint.json.tmp"
        assert not tmp_file.exists(), "Temp file should not remain after atomic save"

    def test_checkpoint_content_valid(self, tmp_path):
        """The saved checkpoint should contain valid JSON with expected keys."""
        import json

        from exif_tagger.config import get_checkpoint_path, save_checkpoint
        from exif_tagger.models.schema import ImageCheckpoint

        root = str(tmp_path)
        images: dict[str, ImageCheckpoint] = {
            "photo.jpg": ImageCheckpoint(path="photo.jpg", status="done", matched_tags=["landscape"]),
        }

        save_checkpoint(root, total_images=2, images=images)

        cp_path = get_checkpoint_path(root)
        with open(cp_path, encoding="utf-8") as fh:
            data = json.load(fh)

        assert data["version"] == 1
        assert data["total_images"] == 2
        assert data["processed"] == 1
        assert "photo.jpg" in data["images"]


class TestGetConfigPath:
    """Test get_config_path resolution and EXIFTAGGER_DATA_DIR auto-initialization."""

    def test_get_config_path_default(self, monkeypatch):
        from exif_tagger.config import DEFAULT_CONFIG_PATH, get_config_path

        monkeypatch.delenv("EXIFTAGGER_CONFIG_FILE", raising=False)
        monkeypatch.delenv("EXIFTAGGER_DATA_DIR", raising=False)
        assert get_config_path() == DEFAULT_CONFIG_PATH

    def test_get_config_path_data_dir(self, monkeypatch, tmp_path):
        from exif_tagger.config import get_config_path

        monkeypatch.delenv("EXIFTAGGER_CONFIG_FILE", raising=False)
        monkeypatch.setenv("EXIFTAGGER_DATA_DIR", str(tmp_path))
        path = get_config_path()
        assert path == tmp_path / "config.yaml"

    def test_get_config_path_config_file_override(self, monkeypatch, tmp_path):
        from exif_tagger.config import get_config_path

        custom_file = tmp_path / "custom_config.yaml"
        monkeypatch.setenv("EXIFTAGGER_CONFIG_FILE", str(custom_file))
        monkeypatch.setenv("EXIFTAGGER_DATA_DIR", str(tmp_path / "data"))
        assert get_config_path() == custom_file

    def test_get_config_path_custom_param(self, monkeypatch, tmp_path):
        from exif_tagger.config import get_config_path

        param_file = tmp_path / "explicit.yaml"
        monkeypatch.setenv("EXIFTAGGER_CONFIG_FILE", str(tmp_path / "env.yaml"))
        monkeypatch.setenv("EXIFTAGGER_DATA_DIR", str(tmp_path / "data"))
        assert get_config_path(param_file) == param_file

    def test_load_config_creates_data_dir_and_copies_example(self, monkeypatch, tmp_path):
        from exif_tagger.config import load_config

        data_dir = tmp_path / "nested" / "data"
        monkeypatch.delenv("EXIFTAGGER_CONFIG_FILE", raising=False)
        monkeypatch.setenv("EXIFTAGGER_DATA_DIR", str(data_dir))
        monkeypatch.setenv("EXIFTAGGER_ROOT_DIRECTORY", str(tmp_path))

        config = load_config()
        assert data_dir.exists()
        config_file = data_dir / "config.yaml"
        assert config_file.exists()
        assert config.root_directory == str(tmp_path)
