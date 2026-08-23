"""Tests for the image scanner module."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from exif_tagger.image_scanner import build_exclude_compilers, scan_images


class TestScanImages:
    """Test recursive image scanning with various scenarios."""

    def test_finds_jpg_and_png(self, sample_image_directory):
        """scan_images should find all .jpg and .png files recursively."""
        images = scan_images(sample_image_directory)
        paths_str = {str(p) for p in images}
        assert len(images) >= 2  # real_image.png + another.jpg at minimum

    def test_excludes_hidden_files(self, tmp_path):
        """Files matching exclude patterns (e.g., .hidden) should be excluded."""
        Image.new("RGB", (50, 50)).save(tmp_path / "photo.jpg")
        # Create a hidden file that won't match our regex but is still there
        (tmp_path / ".hidden.jpg").write_bytes(b"fake image data")

        images = scan_images(
            tmp_path,
            exclude_patterns=["^\\."],  # Match files starting with dot
        )
        paths_str = {str(p) for p in images}
        assert not any(".hidden" in str(p) for p in images), (
            ".hidden.jpg was included but should be excluded by '^\\.' pattern"
        )

    def test_excludes_by_pattern(self, tmp_path):
        """Files matching exclude regex patterns are skipped."""
        Image.new("RGB", (50, 50)).save(tmp_path / "photo.jpg")
        (tmp_path / "thumbs_db").mkdir()
        Image.new("RGB", (50, 50)).save(tmp_path / "thumbs_db" / "thumb_01.jpg")

        images = scan_images(tmp_path, exclude_patterns=["thumbs?_?(db|cache)?/i?"])
        paths_str = {str(p) for p in images}
        assert not any("thumbs_db" in str(p) for p in images), "Image inside thumbs_db should be excluded by pattern"

    def test_deterministic_order(self, sample_image_directory):
        """scanned list should be sorted alphabetically for deterministic processing."""
        images = scan_images(sample_image_directory)
        paths_str = [str(p) for p in images]
        assert paths_str == sorted(paths_str), "Image paths must be sorted"

    def test_nonexistent_directory_raises(self):
        """Scanning a nonexistent directory should raise FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            scan_images("/nonexistent/directory/path/xyz")

    def test_scan_cancelled_stops_early(self, tmp_path):
        """scan_images should stop when is_cancelled returns True."""
        # Create 10 images sorted alphabetically (a.jpg through j.jpg)
        for letter in "abcdefghij":
            Image.new("RGB", (50, 50)).save(tmp_path / f"{letter}.jpg")

        call_count = 0

        def is_cancelled():
            nonlocal call_count
            call_count += 1
            return call_count >= 3  # Cancel on the 3rd check

        images = scan_images(tmp_path, is_cancelled=is_cancelled)
        assert len(images) < 10, "scan_images should have stopped early"

    def test_scan_images_logs_at_debug_level(self, tmp_path, caplog):
        """scan_images should log found count at DEBUG level, not INFO."""
        import logging

        Image.new("RGB", (50, 50)).save(tmp_path / "img1.jpg")
        with caplog.at_level(logging.DEBUG):
            scan_images(tmp_path)

        info_records = [r for r in caplog.records if r.levelno == logging.INFO and "Found" in r.message]
        debug_records = [r for r in caplog.records if r.levelno == logging.DEBUG and "Found" in r.message]
        assert len(info_records) == 0, "scan_images should not emit 'Found ... images' at INFO level"
        assert len(debug_records) >= 1, "scan_images should emit 'Found ... images' at DEBUG level"


class TestExcludeCompilers:
    """Test regex compiler builder for exclude patterns."""

    def test_empty_patterns(self):
        compilers = build_exclude_compilers([])
        assert compilers == []

    def test_valid_patterns_compile(self):
        compilers = build_exclude_compilers(["^thumbs", "/\\.DS_Store"])
        assert len(compilers) == 2

    def test_invalid_pattern_skipped(self, caplog):
        """Invalid regex pattern should be skipped with a warning."""

        compilers = build_exclude_compilers(["[invalid"])
        # The invalid pattern is silently skipped (warning logged), not raised
        assert len(compilers) == 0  # None were compiled successfully


class TestFilterByCheckpoint:
    """Test filtering images against existing checkpoint data."""

    def test_filter_skips_done_images(self):
        from exif_tagger.image_scanner import filter_by_checkpoint
        from exif_tagger.models.schema import ImageCheckpoint

        all_images = [Path("/a/b/1.jpg"), Path("/a/b/2.jpg"), Path("/a/b/3.jpg")]
        checkpoint = {
            str(Path("/a/b/1.jpg").resolve()): ImageCheckpoint(
                path=str(Path("/a/b/1.jpg")), status="done", matched_tags=["tag1"]
            ),
            str(Path("/a/b/2.jpg").resolve()): ImageCheckpoint(
                path=str(Path("/a/b/2.jpg")), status="failed", error="timeout"
            ),
        }

        to_process, done_count = filter_by_checkpoint(all_images, checkpoint)
        # 1 is "done" → skipped. 2 is "failed" (not done) and 3 not in checkpoint
        assert len(to_process) == 2
        assert done_count == 1

    def test_filter_no_checkpoint(self):
        from exif_tagger.image_scanner import filter_by_checkpoint

        all_images = [Path("/a/b/1.jpg"), Path("/a/b/2.jpg")]
        to_process, done_count = filter_by_checkpoint(all_images, {})
        assert len(to_process) == 2
        assert done_count == 0
