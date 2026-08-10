"""Main script for exif-tagger – CLI entry point and pipeline engine."""

from __future__ import annotations

import argparse
import logging
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from exif_tagger.ai_client import setup_secure_logging

CHECKPOINT_BATCH_SIZE = 100
ERRORS_TO_DISPLAY_MAX = 10


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="exif-tagger",
        description=(
            "AI-powered image tagging tool. Scans images recursively, evaluates them "
            "against configured tags using a vision model, and writes matching tag names "
            "to the XPTags EXIF field (semicolon-separated)."
        ),
    )
    parser.add_argument(
        "-c",
        "--config",
        type=str,
        default="config.yaml",
        help="Path to config.yaml (default: ./config.yaml or $EXIFTAGGER_CONFIG_FILE)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose per-image logging during processing.",
    )
    parser.add_argument(
        "--list-tags",
        action="store_true",
        help="List all configured tags with descriptions and thresholds, then exit.",
    )

    return parser


def _log_tag_list(tags: dict) -> None:
    """Pretty-print the list of configured tags."""
    print("\nConfigured tags:")
    print("-" * 70)
    for name in sorted(tags.keys()):
        tag = tags[name]
        desc = getattr(tag, "description", str(tag)) if hasattr(tag, "description") else "N/A"
        threshold = getattr(tag, "threshold", 0.7)
        print(f"  {name:<25} (threshold: {threshold:.2f})")
        print(f"    → {desc}")
    print("-" * 70)


def _format_summary_text(summary: dict) -> str:
    """Format a summary dictionary into human-readable text."""
    lines = [
        "",
        "=" * 60,
        "RUN SUMMARY",
        "=" * 60,
        f"Root directory: {summary['root_directory']}",
        f"Total images found:   {summary['total_images_found']}",
        f"Processed this run:   {summary['total_processed']}",
        f"Newly tagged:         {summary['successfully_tagged']}",
        f"Already had tags:     {summary['already_tagged']}",
        f"Skipped (checkpoint): {summary['skipped_by_checkpoint']}",
        f"Failed:               {summary['failed']}",
    ]

    if summary.get("errors"):
        lines.append("")
        lines.append("Errors:")
        for err in summary["errors"][:ERRORS_TO_DISPLAY_MAX]:
            lines.append(f"  - {err}")
        if len(summary["errors"]) > ERRORS_TO_DISPLAY_MAX:
            lines.append(f"  ... and {len(summary['errors']) - ERRORS_TO_DISPLAY_MAX} more")

    lines.extend(["", "=" * 60])
    return "\n".join(lines)


def validate_and_resolve_subfolder(user_path: str | None, base_gallery_root: Path) -> tuple[Path, str | None]:
    """
    Validates user_path against base_gallery_root to ensure path traversal breakout is impossible.

    Returns (resolved_base_gallery_root, relative_subfolder_str_or_none).
    Raises ValueError if requested path resolves outside base_gallery_root.
    """
    resolved_root = base_gallery_root.resolve()
    if user_path is None:
        return resolved_root, None

    raw_str = str(user_path).strip()
    clean_rel = raw_str.replace("\\", "/").strip("/")
    if not clean_rel or clean_rel == ".":
        return resolved_root, None

    override_path = Path(raw_str)
    if override_path.is_absolute():
        try:
            rel = override_path.resolve().relative_to(resolved_root)
            if rel.as_posix() == ".":
                return resolved_root, None
            return resolved_root, rel.as_posix()
        except ValueError:
            raise ValueError(f"Requested path '{user_path}' is outside the root image directory.")

    candidate = (resolved_root / clean_rel).resolve()
    try:
        rel = candidate.relative_to(resolved_root)
        if rel.as_posix() == ".":
            return resolved_root, None
        return resolved_root, rel.as_posix()
    except ValueError:
        raise ValueError(f"Requested path '{user_path}' is outside the root image directory.")


class StateLoggingHandler(logging.Handler):
    """Logging handler that routes logs to ProcessingState."""

    def __init__(self, state: ProcessingState):
        super().__init__()
        self.state = state

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            level = record.levelname.lower()
            if level in ("error", "critical"):
                level = "error"
            elif level == "warning":
                level = "warning"
            else:
                level = "info"
            self.state.add_log(msg, level)
        except Exception:
            self.handleError(record)


class ProcessingState:
    """Thread-safe state tracker for a running processing session."""

    def __init__(self):
        self._lock = threading.RLock()
        self._running = False
        self._processed = 0
        self._total = 0
        self._current_image: str | None = None
        self._stop_requested = False
        self._log_entries: list[dict[str, Any]] = []
        self._log_counter = 0
        self._summary: dict | None = None

    @property
    def running(self) -> bool:
        with self._lock:
            return self._running

    @property
    def processed(self) -> int:
        with self._lock:
            return self._processed

    @property
    def total(self) -> int:
        with self._lock:
            return self._total

    @property
    def current_image(self) -> str | None:
        with self._lock:
            return self._current_image

    @property
    def stop_requested(self) -> bool:
        with self._lock:
            return self._stop_requested

    @property
    def summary(self) -> dict | None:
        with self._lock:
            return self._summary

    def add_log(self, text: str, level: str = "info") -> None:
        with self._lock:
            for line in text.splitlines():
                if not line.strip():
                    continue
                self._log_counter += 1
                self._log_entries.append(
                    {
                        "id": self._log_counter,
                        "text": line,
                        "level": level,
                    }
                )
            while len(self._log_entries) > 500:
                self._log_entries.pop(0)

    def get_logs(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._log_entries)

    def start(self, total_images: int) -> None:
        with self._lock:
            self._running = True
            self._processed = 0
            self._total = total_images
            self._current_image = None
            self._stop_requested = False
            self._log_entries = []
            self._log_counter = 0
            self._summary = None

    def update_progress(self, image_name: str) -> None:
        with self._lock:
            self._processed += 1
            self._current_image = image_name
            self.add_log(f"[{self._processed}/{self._total}] Processed: {image_name}", "info")

    def set_stop_requested(self) -> None:
        with self._lock:
            self._stop_requested = True

    def finish(self, summary: dict) -> None:
        with self._lock:
            self._running = False
            self._current_image = None
            self._summary = summary

    @property
    def progress_pct(self) -> float:
        with self._lock:
            if self._total == 0:
                return 0.0
            return round((self._processed / self._total) * 100, 1)


class PipelineEngine:
    def __init__(self, config_path: str, verbose: bool = False):
        self.config_path = config_path
        self.verbose = verbose
        self.state = ProcessingState()
        self._config = None

    def _load_config(self):
        from exif_tagger.config import load_config
        from exif_tagger.models.schema import Config

        self._config: Config = load_config(self.config_path)
        self._config.validate()
        self._config.validate_exclude_patterns()
        return self._config

    def start_session(
        self,
        root_directory: str | None = None,
        max_images: int | None = None,
    ) -> dict:
        from exif_tagger.ai_client import tag_image_with_ai
        from exif_tagger.exif_writer import set_xptags

        state_handler = None
        logger = logging.getLogger("exif_tagger")

        config = self._load_config()
        base_gallery_root = Path(config.root_directory).resolve()
        base_gallery_root, target_subfolder = validate_and_resolve_subfolder(root_directory, base_gallery_root)
        config.root_directory = str(base_gallery_root)

        try:
            config_log_level = getattr(config, "log_level", "INFO")
            config_log_dir = getattr(config, "log_dir", "/app/logs")
            log_level = logging.DEBUG if self.verbose else config_log_level
            setup_secure_logging(level=log_level, log_dir=config_log_dir)

            effective_level = (
                logging.DEBUG if self.verbose else getattr(logging, str(config_log_level).upper(), logging.INFO)
            )
            state_handler = StateLoggingHandler(self.state)
            state_handler.setLevel(effective_level)
            logger.addHandler(state_handler)

            if not config.tags:
                err_msg = "No tags configured"
                self.state.add_log(err_msg, "error")
                summary = {"error": err_msg, "exit_code": 1}
                self.state.finish(summary)
                return summary

            _log_tag_list(config.tags)

            from exif_tagger.config import compute_tag_hash, migrate_legacy_checkpoint
            from exif_tagger.db import (
                evaluate_thresholds_locally,
                get_connection,
                get_unevaluated_candidates,
                record_tag_evaluation,
                sync_gallery_index,
            )

            # 1. Migrate legacy checkpoint if present
            migrate_legacy_checkpoint(config.root_directory)

            # 2. Sync gallery index & self-heal EXIF tag removals
            sync_stats = sync_gallery_index(
                root_directory=config.root_directory,
                exclude_patterns=config.exclude_patterns or [],
            )

            from exif_tagger.image_scanner import scan_images

            if target_subfolder:
                sub_dir = (base_gallery_root / target_subfolder).resolve()
                if sub_dir.exists() and sub_dir.is_dir():
                    scanned_sub = scan_images(sub_dir, exclude_patterns=config.exclude_patterns or [])
                    total_found = len(scanned_sub)
                else:
                    conn = get_connection()
                    try:
                        clean_sub = target_subfolder.replace("\\", "/").strip("/").lower()
                        row = conn.execute(
                            "SELECT COUNT(*) FROM images WHERE LOWER(REPLACE(relative_path, '\\', '/')) LIKE ? OR LOWER(REPLACE(relative_path, '\\', '/')) = ?",
                            (f"{clean_sub}/%", clean_sub),
                        ).fetchone()
                        total_found = row[0] if row else 0
                    finally:
                        conn.close()
            else:
                total_found = sync_stats.get("total", 0)

            # 3. Compute tag description hashes
            tag_hashes = {name: compute_tag_hash(tag_def.description) for name, tag_def in config.tags.items()}

            # 4. Perform zero-cost local threshold re-evaluation
            local_stats = evaluate_thresholds_locally(
                root_directory=config.root_directory,
                active_tags=config.tags,
                tag_hashes=tag_hashes,
            )

            # 5. Query candidate (image, tag) pairs requiring Vision AI evaluation
            candidates = get_unevaluated_candidates(
                root_directory=config.root_directory,
                active_tags=config.tags,
                tag_hashes=tag_hashes,
                subfolder=target_subfolder,
            )

            # Group candidates by image
            images_candidates_map: dict[str, list[dict[str, Any]]] = {}
            for c in candidates:
                images_candidates_map.setdefault(c["file_path"], []).append(c)

            images_to_process = [Path(p) for p in images_candidates_map.keys()]

            # Cap images to process at max_images (don't cap DB query — let loop handle it)
            if max_images and max_images > 0 and len(images_to_process) > max_images:
                images_to_process = images_to_process[:max_images]

            logger.info(
                "%d total images in folder, %d require vision model evaluation.",
                total_found,
                len(images_to_process),
            )

            session_total = total_found

            if not images_to_process:
                summary = {
                    "root_directory": config.root_directory,
                    "total_images_found": total_found,
                    "total_processed": 0,
                    "successfully_tagged": 0,
                    "already_tagged": total_found,
                    "skipped_by_checkpoint": total_found,
                    "failed": 0,
                    "errors": [],
                }
                self.state.start(session_total)
                self.state.finish(summary)
                return summary

            self.state.start(session_total)

            successfully_tagged = 0
            failed_count = 0
            errors: list[str] = []
            counters_lock = threading.Lock()

            concurrency = getattr(config.ai_model, "concurrency", 1)
            logger.info("Processing %d images with concurrency=%d.", len(images_to_process), concurrency)

            def process_image(img_path: Path) -> None:
                nonlocal successfully_tagged, failed_count

                if self.state.stop_requested:
                    return

                if self.verbose:
                    logger.info("Processing: %s", img_path.name)

                img_cand_list = images_candidates_map.get(str(img_path), [])
                if not img_cand_list:
                    self.state.update_progress(img_path.name)
                    return

                img_id = img_cand_list[0]["image_id"]
                img_mtime = img_cand_list[0]["image_mtime"]
                target_tags = {
                    c["tag_name"]: config.tags[c["tag_name"]] for c in img_cand_list if c["tag_name"] in config.tags
                }

                try:
                    response = tag_image_with_ai(
                        config.ai_model,
                        img_path,
                        target_tags,
                        max_dim=config.max_image_dimension,
                    )

                    conn = get_connection()
                    try:
                        t_rows = conn.execute(
                            "SELECT tag_name FROM image_tags WHERE image_id = ?", (img_id,)
                        ).fetchall()
                        current_exif_tags = {tr["tag_name"].lower() for tr in t_rows}
                    finally:
                        conn.close()

                    newly_matched = False
                    for tr in response.results:
                        t_name = tr.tag_name.lower()
                        tag_def = config.tags.get(t_name)
                        desc_hash = tag_hashes.get(t_name, "")
                        is_match = (tag_def is not None) and (tr.score >= tag_def.threshold)

                        status_str = "matched" if is_match else "not_matched"

                        record_tag_evaluation(
                            image_id=img_id,
                            tag_name=t_name,
                            description_hash=desc_hash,
                            status=status_str,
                            score=tr.score,
                            reason=tr.reason,
                            model_name=getattr(config.ai_model, "model_name", "vision_model"),
                            image_mtime=img_mtime,
                        )

                        if is_match:
                            current_exif_tags.add(t_name)
                            newly_matched = True

                    if newly_matched:
                        sorted_tags = sorted(current_exif_tags)
                        modified = set_xptags(img_path, sorted_tags)

                        from datetime import UTC, datetime

                        now_iso = datetime.now(UTC).isoformat()
                        conn = get_connection()
                        try:
                            with conn:
                                conn.execute("DELETE FROM image_tags WHERE image_id = ?", (img_id,))
                                for t in sorted_tags:
                                    conn.execute(
                                        "INSERT OR IGNORE INTO image_tags (image_id, tag_name, source, added_at) VALUES (?, ?, 'model', ?)",
                                        (img_id, t, now_iso),
                                    )
                        finally:
                            conn.close()

                        if modified:
                            with counters_lock:
                                successfully_tagged += 1

                except Exception as exc:
                    with counters_lock:
                        failed_count += 1
                        errors.append(f"{img_path.name}: {exc}")
                    logger.error("Failed to process %s: %s", img_path.name, exc)

                self.state.update_progress(img_path.name)

            with ThreadPoolExecutor(max_workers=concurrency) as executor:
                futures = {executor.submit(process_image, p): p for p in images_to_process}
                for future in as_completed(futures):
                    if self.state.stop_requested:
                        # Cancel pending futures (already-running ones finish naturally)
                        for f in futures:
                            f.cancel()
                        break
                    # Propagate unexpected exceptions from the worker
                    exc = future.exception()
                    if exc:
                        logger.error("Unexpected worker error: %s", exc)

            summary = {
                "root_directory": config.root_directory,
                "total_images_found": total_found,
                "total_processed": len(images_to_process),
                "successfully_tagged": successfully_tagged,
                "already_tagged": total_found - len(images_to_process),
                "skipped_by_checkpoint": total_found - len(images_to_process),
                "failed": failed_count,
                "errors": errors,
            }

            self.state.finish(summary)

            if self.verbose:
                logger.info(_format_summary_text(summary))
            else:
                for line in _format_summary_text(summary).split("\n"):
                    print(line)

            return summary

        except Exception as exc:
            logger.error("Fatal error: %s", exc, exc_info=True)
            err_msg = f"Fatal error: {exc}"
            self.state.add_log(err_msg, "error")
            summary = {
                "root_directory": getattr(self._config, "root_directory", ""),
                "total_images_found": 0,
                "total_processed": 0,
                "successfully_tagged": 0,
                "already_tagged": 0,
                "skipped_by_checkpoint": 0,
                "failed": 1,
                "errors": [err_msg],
            }
            if not self.state.running:
                self.state.start(0)
            self.state.finish(summary)
            return {"error": str(exc), "exit_code": 1}
        finally:
            if state_handler:
                logger.removeHandler(state_handler)

    def stop(self) -> dict:
        """Request graceful stop of current session."""
        self.state.set_stop_requested()
        time.sleep(0.5)  # Give thread a moment to notice
        summary = self.state.summary or {}
        return {
            "status": "stopped",
            "processed": self.state.processed,
        }

    def get_status(self) -> dict:
        """Get current processing state."""
        s = self.state
        return {
            "running": s.running,
            "processed": s.processed,
            "total": s.total,
            "currentImage": s.current_image,
            "progressPct": s.progress_pct,
            "stopRequested": s.stop_requested,
            "logs": s.get_logs(),
        }


def run(
    config_path: str,
    verbose: bool = False,
) -> int:
    """Execute the full tagging pipeline via CLI. Returns exit code (0=success, 1=error)."""
    engine = PipelineEngine(config_path=config_path, verbose=verbose)
    summary = engine.start_session()
    return summary.get("exit_code", 0 if not summary.get("errors") else 1)


def main() -> None:
    """CLI entry point."""
    parser = _build_parser()
    args = parser.parse_args()

    if args.list_tags:
        from exif_tagger.config import load_config

        config = load_config(args.config)
        _log_tag_list(config.tags)
        sys.exit(0)

    exit_code = run(
        config_path=args.config,
        verbose=args.verbose,
    )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
