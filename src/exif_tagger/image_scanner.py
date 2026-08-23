"""Söker rekursivt efter bilder i root-directory med regex-exkludering."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from pathlib import Path

from exif_tagger.models.schema import IMAGE_EXTENSIONS

logger = logging.getLogger(__name__)


def build_exclude_compilers(patterns: list[str]) -> list[re.Pattern]:
    """Compile exclude patterns into regex objects. Empty list if no patterns."""
    compilers: list[re.Pattern] = []
    for pattern in patterns:
        try:
            # Compile against the full path of each image we encounter
            compilers.append(re.compile(pattern))
        except re.error as exc:
            logger.warning("Skipping invalid exclude pattern '%s': %s", pattern, exc)
    return compilers


def _is_image_path(path: Path) -> bool:
    """Check if a file path has an image extension."""
    return path.suffix.lower() in IMAGE_EXTENSIONS


def scan_images(
    root_directory: str | Path,
    exclude_patterns: list[str] | None = None,
    is_cancelled: Callable[[], bool] | None = None,
) -> list[Path]:
    """Recursively find all images in the given directory.

    Args:
        root_directory: The base directory to search recursively.
        exclude_patterns: Optional list of regex patterns for paths to skip.
        is_cancelled: Optional callback returning True when scanning should stop early.

    Returns:
        Sorted list of absolute Path objects pointing to image files.
        Sorting ensures deterministic processing order.
    """
    root = Path(root_directory).resolve()
    if not root.exists():
        raise FileNotFoundError(f"Directory does not exist: {root}")
    if not root.is_dir():
        raise NotADirectoryError(f"Not a directory: {root}")

    # Compile exclude patterns once
    compilers = build_exclude_compilers(exclude_patterns or [])

    image_paths: list[Path] = []

    for dirpath, _dirnames, filenames in sorted(root.walk()):
        if is_cancelled and is_cancelled():
            logger.debug("Scan cancelled after finding %d images", len(image_paths))
            break

        current_dir = Path(dirpath)

        # Check if the *directory* itself should be excluded (match on relative path from root)
        try:
            rel_path = current_dir.relative_to(root).as_posix()
        except ValueError:
            # File is in root or above – use absolute
            rel_path = ""

        for filename in sorted(filenames):
            if is_cancelled and is_cancelled():
                logger.debug("Scan cancelled after finding %d images", len(image_paths))
                break

            file_path = current_dir / filename
            if not _is_image_path(file_path):
                continue

            # Check exclude patterns against relative path (as posix-style string).
            # Path.walk() only lists files here, so no extra stat needed.
            full_rel = file_path.relative_to(root).as_posix()

            excluded = False
            for compiler in compilers:
                if compiler.search(full_rel):
                    logger.debug("Excluded %s (matched pattern '%s')", file_path, compiler.pattern)
                    excluded = True
                    break

            if not excluded:
                image_paths.append(file_path)

    # Sort for deterministic order
    image_paths.sort()

    logger.debug("Found %d images in %s", len(image_paths), root)
    return image_paths
