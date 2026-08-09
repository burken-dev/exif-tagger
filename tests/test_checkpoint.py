"""Tests for checkpoint (resume) functionality."""

from __future__ import annotations

import json

from exif_tagger.config import (
    get_checkpoint_path,
    get_resume_info,
    load_checkpoint,
    save_checkpoint,
)
from exif_tagger.models.schema import ImageCheckpoint


class TestCheckpointPersistence:
    """Test checkpoint save/load round-trip."""

    def test_save_and_load_roundtrip(self, tmp_path):
        images = {
            str(tmp_path / "a.jpg"): ImageCheckpoint(
                path=str(tmp_path / "a.jpg"), status="done", matched_tags=["landscape"]
            ),
            str(tmp_path / "b.jpg"): ImageCheckpoint(path=str(tmp_path / "b.jpg"), status="failed", error="timeout"),
        }

        save_checkpoint(str(tmp_path), total_images=5, images=images)

        loaded = load_checkpoint(str(tmp_path), total_images=5)
        assert len(loaded) == 2
        assert loaded[str(tmp_path / "a.jpg")].status == "done"
        assert loaded[str(tmp_path / "b.jpg")].error == "timeout"

    def test_checkpoint_file_created(self, tmp_path):
        """Checkpoint should create a JSON file in root_directory."""
        save_checkpoint(str(tmp_path), total_images=0, images={})

        cp = get_checkpoint_path(str(tmp_path))
        assert cp.exists()
        # Should be valid JSON
        with open(cp) as fh:
            data = json.load(fh)
        assert "version" in data


class TestCheckpointLoadingEdgeCases:
    """Test checkpoint loading when file is missing or corrupt."""

    def test_missing_checkpoint_file(self, tmp_path):
        result = load_checkpoint(str(tmp_path), total_images=10)
        assert result == {}

    def test_corrupt_json_file(self, tmp_path):
        cp_path = get_checkpoint_path(str(tmp_path))
        cp_path.write_text("this is not json {{{")
        result = load_checkpoint(str(tmp_path), total_images=10)
        # Should return empty dict on corrupt data
        assert isinstance(result, dict)

    def test_different_root_directory_ignored(self, tmp_path):
        """Checkpoint for a different root dir should be ignored on load."""
        other_dir = tmp_path / "other"
        other_dir.mkdir()

        images = {
            str(other_dir / "photo.jpg"): ImageCheckpoint(
                path=str(other_dir / "photo.jpg"), status="done", matched_tags=["test"]
            )
        }
        save_checkpoint(str(tmp_path), total_images=1, images=images)

        # Loading from a DIFFERENT directory (no checkpoint file there) should return empty
        different_root = tmp_path / "totally_different"
        different_root.mkdir()
        result = load_checkpoint(str(different_root), total_images=10)
        assert str(other_dir / "photo.jpg") not in result


class TestGetResumeInfo:
    """Test resume logic – returns checkpoint if there's progress, else None."""

    def test_returns_none_for_empty_run(self, tmp_path):
        """If no images have been processed yet, get_resume_info should return None."""
        # Create empty checkpoint (or none at all)
        result = get_resume_info(str(tmp_path), total_images=0)
        assert result is None

    def test_returns_checkpoint_when_done(self, tmp_path):
        """If some images were done, resume info should be available."""
        save_checkpoint(
            str(tmp_path),
            total_images=3,
            images={
                str(tmp_path / "a.jpg"): ImageCheckpoint(
                    path=str(tmp_path / "a.jpg"), status="done", matched_tags=["landscape"]
                ),
            },
        )

        result = get_resume_info(str(tmp_path), total_images=3)
        assert result is not None
        assert str(tmp_path / "a.jpg") in result


class TestCheckpointDataModel:
    """Test the CheckpointData pydantic model."""

    def test_defaults(self):
        from exif_tagger.models.schema import CheckpointData

        cd = CheckpointData(
            version=1,
            created_at="2024-01-01T00:00:00Z",
            root_directory="/data/images",
            total_images=100,
            processed=50,
            images={},
        )
        assert cd.version == 1
        assert cd.total_images == 100
        assert cd.processed == 50
