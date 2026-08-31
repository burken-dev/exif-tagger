"""Shared pytest fixtures and configuration."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from PIL import Image

# ---------------------------------------------------------------------------
# Fixture to isolate SQLite database per test
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def isolate_test_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Ensure every test operates on an isolated SQLite database file."""
    db_file = tmp_path / "isolated_test_gallery.db"
    monkeypatch.setenv("EXIFTAGGER_DB_FILE", str(db_file))
    return db_file


@pytest.fixture(autouse=True)
def reset_ai_client_cache():
    """Ensure every test starts and ends with a clean OpenAI client cache."""
    from exif_tagger.ai_client import clear_client_cache

    clear_client_cache()
    yield
    clear_client_cache()


# ---------------------------------------------------------------------------
# Fixtures for creating temporary images
# ---------------------------------------------------------------------------


@pytest.fixture()
def sample_jpeg(tmp_path: Path) -> Path:
    """Create a small test JPEG image."""
    img = Image.new("RGB", (100, 80), color=(255, 0, 0))
    path = tmp_path / "test.jpg"
    img.save(path, format="JPEG")
    return path


@pytest.fixture()
def sample_png(tmp_path: Path) -> Path:
    """Create a small test PNG image."""
    img = Image.new("RGB", (120, 90), color=(0, 255, 0))
    path = tmp_path / "test.png"
    img.save(path, format="PNG")
    return path


@pytest.fixture()
def sample_image_directory(tmp_path: Path) -> Path:
    """Create a small directory structure with various image files."""
    (tmp_path / "photo1.jpg").write_bytes(b"")  # placeholder

    img = Image.new("RGB", (50, 50), color=(0, 0, 255))
    img.save(tmp_path / "real_image.png", format="PNG")
    img.save(tmp_path / "another.jpg", format="JPEG")

    sub = tmp_path / "subdir" / "nested"
    sub.mkdir(parents=True, exist_ok=True)
    img.save(sub / "deep.jpg", format="JPEG")

    return tmp_path


@pytest.fixture()
def sample_config(tmp_path: Path):
    """Create a minimal valid config.yaml for testing."""
    content = {
        "root_directory": str(tmp_path),
        "model": {  # alias "model" → ai_model field
            "base_url": "https://api.example.com/v1",
            "model_name": "test-model",
        },
        "tags": {
            "test_tag": {
                "description": "A test tag for unit tests",
                "threshold": 0.5,
            }
        },
        "exclude_patterns": [],
    }
    config_path = tmp_path / "config.yaml"
    import yaml

    with open(config_path, "w") as fh:
        yaml.dump(content, fh)
    return config_path


# ---------------------------------------------------------------------------
# Mock for OpenAI client (avoids real API calls in tests)
# ---------------------------------------------------------------------------


class _MockOpenAIClient:
    """Minimal mock of the OpenAI client that returns JSON responses.

    Returns a properly structured response where choices[0].message.content
    is a real string (not a MagicMock).
    """

    def __init__(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        pass

    class chat:
        class completions:
            @staticmethod
            def create(*args, **kwargs):  # type: ignore[no-untyped-def]
                payload = {
                    "results": [
                        {"tag_name": "test_tag", "score": 0.9, "reason": "Mock match"},
                    ]
                }

                # Build a proper response structure – ai_client expects
                # response.choices[0].message.content (string)
                class _Msg:
                    content = json.dumps(payload)

                class _Choice:
                    message = _Msg()

                result = MagicMock()
                result.choices = [_Choice()]  # type: ignore[list-item]
                return result


@pytest.fixture()
def mock_openai(monkeypatch):
    """Patch the OpenAI import so no real API calls are made."""
    monkeypatch.setattr("exif_tagger.ai_client.OpenAI", _MockOpenAIClient)
    return _MockOpenAIClient
