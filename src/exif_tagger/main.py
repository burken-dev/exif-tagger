"""Main script for exif-tagger – CLI entry point and pipeline engine."""

from __future__ import annotations

import argparse
import contextlib
import logging
import queue
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from exif_tagger.ai_client import setup_secure_logging

CHECKPOINT_BATCH_SIZE = 100
ERRORS_TO_DISPLAY_MAX = 10


@dataclass
class PreparedPayload:
    img_path: Path
    img_cand_list: list[dict[str, Any]]
    img_id: int
    img_mtime: float
    target_tags: dict[str, Any]
    prompt: str
    image_b64: str | None = None
    mime_type: str = "image/jpeg"
    error: Exception | None = None


@dataclass
class WriteTask:
    img_path: Path
    img_cand_list: list[dict[str, Any]]
    img_id: int
    img_mtime: float
    cleaned_results: dict[str, Any]
    tags_to_apply: set[str]
    current_exif_tags: set[str] | None = None
    is_match: bool = False
    error: Exception | None = None


_PREFETCH_SENTINEL = object()
_WRITE_SENTINEL = object()


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
        self._paused = False
        self._pause_event = threading.Event()
        self._pause_event.set()
        self._processed = 0
        self._total = 0
        self._current_image: str | None = None
        self._stop_requested = False
        self._log_entries: list[dict[str, Any]] = []
        self._log_counter = 0
        self._summary: dict | None = None
        self._active_elapsed_seconds: float = 0.0
        self._period_start_time: float | None = None

    @property
    def running(self) -> bool:
        with self._lock:
            return self._running

    @property
    def paused(self) -> bool:
        with self._lock:
            return self._paused

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

    def set_paused(self) -> None:
        with self._lock:
            if self._running and not self._paused:
                if self._period_start_time is not None:
                    self._active_elapsed_seconds += time.monotonic() - self._period_start_time
                    self._period_start_time = None
                self._paused = True
                self._pause_event.clear()
                self.add_log("Processing session paused.", "info")

    def set_resumed(self) -> None:
        with self._lock:
            if self._paused:
                self._paused = False
                self._period_start_time = time.monotonic()
                self._pause_event.set()
                self.add_log("Processing session resumed.", "info")

    def wait_if_paused(self) -> None:
        while True:
            with self._lock:
                if not self._paused or self._stop_requested:
                    return
            self._pause_event.wait(timeout=0.2)

    def start(self, total_images: int) -> None:
        with self._lock:
            self._running = True
            self._paused = False
            self._pause_event.set()
            self._processed = 0
            self._total = total_images
            self._current_image = None
            self._stop_requested = False
            self._log_entries = []
            self._log_counter = 0
            self._summary = None
            self._active_elapsed_seconds = 0.0
            self._period_start_time = time.monotonic()

    def update_progress(self, image_name: str) -> None:
        with self._lock:
            self._processed += 1
            self._current_image = image_name
            self.add_log(f"[{self._processed}/{self._total}] Processed: {image_name}", "info")

    def set_stop_requested(self) -> None:
        with self._lock:
            if self._period_start_time is not None:
                self._active_elapsed_seconds += time.monotonic() - self._period_start_time
                self._period_start_time = None
            self._stop_requested = True
            self._paused = False
            self._pause_event.set()

    def finish(self, summary: dict) -> None:
        with self._lock:
            if self._period_start_time is not None:
                self._active_elapsed_seconds += time.monotonic() - self._period_start_time
                self._period_start_time = None
            self._running = False
            self._paused = False
            self._pause_event.set()
            self._current_image = None
            self._stop_requested = False
            if summary is not None:
                summary["elapsed_seconds"] = round(self.elapsed_seconds, 2)
                summary["avg_seconds_per_image"] = round(self.avg_seconds_per_image, 2)
            self._summary = summary

    @property
    def progress_pct(self) -> float:
        with self._lock:
            if self._total == 0:
                return 0.0
            return round((self._processed / self._total) * 100, 1)

    @property
    def elapsed_seconds(self) -> float:
        with self._lock:
            if self._running and not self._paused and self._period_start_time is not None:
                return self._active_elapsed_seconds + (time.monotonic() - self._period_start_time)
            return self._active_elapsed_seconds

    @property
    def avg_seconds_per_image(self) -> float:
        with self._lock:
            if self._processed > 0:
                return self.elapsed_seconds / self._processed
            return 0.0

    def get_status(self) -> dict:
        """Get current processing state."""
        with self._lock:
            return {
                "running": self._running,
                "paused": self._paused,
                "processed": self._processed,
                "total": self._total,
                "currentImage": self._current_image,
                "progressPct": self.progress_pct,
                "elapsedSeconds": round(self.elapsed_seconds, 2),
                "avgSecondsPerImage": round(self.avg_seconds_per_image, 2),
                "stopRequested": self._stop_requested,
                "logs": list(self._log_entries),
            }


class PipelineEngine:
    def __init__(self, config_path: str, verbose: bool = False):
        self.config_path = config_path
        self.verbose = verbose
        self.state = ProcessingState()
        self._config = None
        self._live_tag_hashes = None

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
        self._config = config

        try:
            config_log_level = getattr(config, "log_level", "INFO")
            config_log_dir = getattr(config, "log_dir", "/app/logs")
            log_level = logging.DEBUG if self.verbose else config_log_level
            setup_secure_logging(level=log_level, log_dir=config_log_dir)

            effective_level = (
                logging.DEBUG if self.verbose else getattr(logging, str(config_log_level).upper(), logging.INFO)
            )
            logger.setLevel(effective_level)
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

            from exif_tagger import image_scanner

            if target_subfolder:
                sub_dir = (base_gallery_root / target_subfolder).resolve()
                if sub_dir.exists() and sub_dir.is_dir():
                    scanned_sub = image_scanner.scan_images(sub_dir, exclude_patterns=config.exclude_patterns or [])
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
            self._live_tag_hashes = tag_hashes

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

            session_total = len(images_to_process)

            if not images_to_process:
                self.state.start(0)
                logger.info(
                    "Found 0 images in processing plan (all %d images in folder are already up to date).",
                    total_found,
                )
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
                self.state.finish(summary)
                return summary

            self.state.start(session_total)

            logger.info(
                "Found %d images in processing plan (%d total images in folder).",
                len(images_to_process),
                total_found,
            )

            successfully_tagged = 0
            failed_count = 0
            errors: list[str] = []
            counters_lock = threading.Lock()

            concurrency = getattr(config.ai_model, "concurrency", 1)
            logger.info("Processing %d images with concurrency=%d.", len(images_to_process), concurrency)

            prefetch_queue_size = max(8, concurrency * 2)
            prefetch_queue: queue.Queue = queue.Queue(maxsize=prefetch_queue_size)
            write_queue: queue.Queue = queue.Queue()

            def prefetch_worker() -> None:
                from exif_tagger.ai_client import _build_prompt, _image_to_base64

                for img_path in images_to_process:
                    self.state.wait_if_paused()
                    if self.state.stop_requested:
                        break

                    try:
                        img_cand_list = images_candidates_map.get(str(img_path), [])
                        if not img_cand_list:
                            payload = PreparedPayload(
                                img_path=img_path,
                                img_cand_list=[],
                                img_id=0,
                                img_mtime=0.0,
                                target_tags={},
                                prompt="",
                            )
                        else:
                            img_id = img_cand_list[0]["image_id"]
                            img_mtime = img_cand_list[0]["image_mtime"]
                            current_config = self._config or config

                            target_tags = {
                                c["tag_name"]: current_config.tags[c["tag_name"]]
                                for c in img_cand_list
                                if c["tag_name"] in current_config.tags
                            }

                            if not target_tags:
                                payload = PreparedPayload(
                                    img_path=img_path,
                                    img_cand_list=img_cand_list,
                                    img_id=img_id,
                                    img_mtime=img_mtime,
                                    target_tags={},
                                    prompt="",
                                )
                            else:
                                fmt = getattr(current_config.ai_model, "image_format", "jpeg")
                                quality = getattr(current_config.ai_model, "image_quality", 80)
                                max_dim = current_config.max_image_dimension
                                image_b64 = _image_to_base64(img_path, max_dim=max_dim, fmt=fmt, quality=quality)
                                mime_type = "image/webp" if fmt.lower() == "webp" else "image/jpeg"
                                use_so = getattr(current_config.ai_model, "use_structured_outputs", False)
                                prompt = _build_prompt(target_tags, use_structured_outputs=use_so)

                                payload = PreparedPayload(
                                    img_path=img_path,
                                    img_cand_list=img_cand_list,
                                    img_id=img_id,
                                    img_mtime=img_mtime,
                                    target_tags=target_tags,
                                    prompt=prompt,
                                    image_b64=image_b64,
                                    mime_type=mime_type,
                                )
                    except Exception as exc:
                        payload = PreparedPayload(
                            img_path=img_path,
                            img_cand_list=images_candidates_map.get(str(img_path), []),
                            img_id=0,
                            img_mtime=0.0,
                            target_tags={},
                            prompt="",
                            error=exc,
                        )

                    while not self.state.stop_requested:
                        self.state.wait_if_paused()
                        if self.state.stop_requested:
                            break
                        try:
                            prefetch_queue.put(payload, timeout=0.1)
                            break
                        except queue.Full:
                            continue

            def ai_inference_worker() -> None:
                from exif_tagger.models.schema import TagResult

                while not self.state.stop_requested:
                    self.state.wait_if_paused()
                    if self.state.stop_requested:
                        break

                    try:
                        payload = prefetch_queue.get(timeout=0.1)
                    except queue.Empty:
                        continue

                    if payload is _PREFETCH_SENTINEL:
                        prefetch_queue.put(_PREFETCH_SENTINEL)
                        break

                    if not isinstance(payload, PreparedPayload):
                        continue

                    if self.verbose:
                        logger.info("Processing: %s", payload.img_path.name)

                    if payload.error is not None:
                        write_task = WriteTask(
                            img_path=payload.img_path,
                            img_cand_list=payload.img_cand_list,
                            img_id=payload.img_id,
                            img_mtime=payload.img_mtime,
                            cleaned_results={},
                            tags_to_apply=set(),
                            current_exif_tags=set(),
                            is_match=False,
                            error=payload.error,
                        )
                        write_queue.put(write_task)
                        continue

                    if not payload.target_tags:
                        write_task = WriteTask(
                            img_path=payload.img_path,
                            img_cand_list=payload.img_cand_list,
                            img_id=payload.img_id,
                            img_mtime=payload.img_mtime,
                            cleaned_results={},
                            tags_to_apply=set(),
                            current_exif_tags=set(),
                            is_match=False,
                        )
                        write_queue.put(write_task)
                        continue

                    try:
                        current_config = self._config or config
                        try:
                            response = tag_image_with_ai(
                                current_config.ai_model,
                                payload.img_path,
                                payload.target_tags,
                                max_dim=current_config.max_image_dimension,
                                image_b64=payload.image_b64,
                                prompt=payload.prompt,
                                mime_type=payload.mime_type,
                            )
                        except TypeError as te:
                            if "unexpected keyword argument" in str(te) or "takes" in str(te):
                                response = tag_image_with_ai(
                                    current_config.ai_model,
                                    payload.img_path,
                                    payload.target_tags,
                                    max_dim=current_config.max_image_dimension,
                                )
                            else:
                                raise

                        # Map raw model results to target_tags with sanitization
                        cleaned_results: dict[str, Any] = {}
                        for tr in response.results:
                            raw_name = str(tr.tag_name).strip().strip("'\"`_*#[]:").lower()
                            matched_key = None
                            if raw_name in payload.target_tags:
                                matched_key = raw_name
                            else:
                                for target_k in payload.target_tags:
                                    if target_k == raw_name or target_k in raw_name or raw_name in target_k:
                                        matched_key = target_k
                                        break
                            if matched_key:
                                cleaned_results[matched_key] = tr

                        # For any requested candidate tag omitted by the model response, record as not matched
                        for target_k in payload.target_tags:
                            if target_k not in cleaned_results:
                                cleaned_results[target_k] = TagResult(
                                    tag_name=target_k,
                                    score=0.0,
                                    reason="Not identified by vision model",
                                )

                        # 1. Identify which tags exceeded threshold in this response
                        matched_in_response = []
                        for t_name, tr in cleaned_results.items():
                            tag_def = current_config.tags.get(t_name)
                            if tag_def is not None and tr.score >= tag_def.threshold:
                                matched_in_response.append((t_name, tr))

                        # 2. Check hallucination overflow guardrail
                        guardrail_cfg = getattr(current_config, "guardrails", None)
                        max_matched = guardrail_cfg.max_matched_tags if guardrail_cfg else 2
                        guardrail_enabled = guardrail_cfg.enabled if guardrail_cfg else True
                        on_overflow = (guardrail_cfg.on_overflow if guardrail_cfg else "suppress").lower()

                        if guardrail_enabled and len(matched_in_response) > max_matched:
                            matched_names = [t_name for t_name, _ in matched_in_response]
                            if on_overflow == "suppress":
                                logger.warning(
                                    "⚠️ Hallucination guardrail triggered on %s: %d tags matched (%s > max %d). Suppressing EXIF write.",
                                    payload.img_path.name,
                                    len(matched_in_response),
                                    matched_names,
                                    max_matched,
                                )
                                tags_to_apply = set()
                            elif on_overflow == "top_k":
                                sorted_by_score = sorted(matched_in_response, key=lambda x: x[1].score, reverse=True)
                                kept = sorted_by_score[:max_matched]
                                tags_to_apply = {t_name for t_name, _ in kept}
                                logger.warning(
                                    "⚠️ Hallucination guardrail triggered on %s: %d tags matched (%s > max %d). Keeping top %d by score: %s.",
                                    payload.img_path.name,
                                    len(matched_in_response),
                                    matched_names,
                                    max_matched,
                                    max_matched,
                                    [t_name for t_name, _ in kept],
                                )
                            else:  # "warn"
                                logger.warning(
                                    "⚠️ Hallucination guardrail warning on %s: %d tags matched (%s > max %d).",
                                    payload.img_path.name,
                                    len(matched_in_response),
                                    matched_names,
                                    max_matched,
                                )
                                tags_to_apply = {t_name for t_name, _ in matched_in_response}
                        else:
                            tags_to_apply = {t_name for t_name, _ in matched_in_response}

                        is_match = any(t_name in tags_to_apply for t_name in cleaned_results)

                        write_task = WriteTask(
                            img_path=payload.img_path,
                            img_cand_list=payload.img_cand_list,
                            img_id=payload.img_id,
                            img_mtime=payload.img_mtime,
                            cleaned_results=cleaned_results,
                            tags_to_apply=tags_to_apply,
                            current_exif_tags=None,
                            is_match=is_match,
                            error=None,
                        )
                    except Exception as exc:
                        write_task = WriteTask(
                            img_path=payload.img_path,
                            img_cand_list=payload.img_cand_list,
                            img_id=payload.img_id,
                            img_mtime=payload.img_mtime,
                            cleaned_results={},
                            tags_to_apply=set(),
                            current_exif_tags=None,
                            is_match=False,
                            error=exc,
                        )

                    write_queue.put(write_task)

            def writer_worker() -> None:
                nonlocal successfully_tagged, failed_count
                from datetime import UTC, datetime

                while True:
                    self.state.wait_if_paused()

                    try:
                        task = write_queue.get(timeout=0.1)
                    except queue.Empty:
                        continue

                    if task is _WRITE_SENTINEL:
                        break

                    if not isinstance(task, WriteTask):
                        continue

                    try:
                        if task.error is not None:
                            with counters_lock:
                                failed_count += 1
                                errors.append(f"{task.img_path.name}: {task.error}")
                            logger.error("Failed to process %s: %s", task.img_path.name, task.error)
                        elif not task.cleaned_results:
                            pass
                        else:
                            current_config = self._config or config
                            current_tag_hashes = getattr(self, "_live_tag_hashes", tag_hashes) or tag_hashes
                            newly_matched = False

                            for t_name, tr in task.cleaned_results.items():
                                desc_hash = current_tag_hashes.get(t_name, "")
                                is_match = t_name in task.tags_to_apply
                                status_str = "matched" if is_match else "not_matched"

                                record_tag_evaluation(
                                    image_id=task.img_id,
                                    tag_name=t_name,
                                    description_hash=desc_hash,
                                    status=status_str,
                                    score=tr.score,
                                    reason=tr.reason,
                                    model_name=getattr(current_config.ai_model, "model_name", "vision_model"),
                                    image_mtime=task.img_mtime,
                                )

                                if is_match:
                                    newly_matched = True

                            if newly_matched:
                                current_tags: set[str]
                                if task.current_exif_tags is not None:
                                    current_tags = set(task.current_exif_tags)
                                else:
                                    conn = get_connection()
                                    try:
                                        t_rows = conn.execute(
                                            "SELECT tag_name FROM image_tags WHERE image_id = ?", (task.img_id,)
                                        ).fetchall()
                                        current_tags = {tr["tag_name"].lower() for tr in t_rows}
                                    finally:
                                        conn.close()

                                for t_name in task.tags_to_apply:
                                    current_tags.add(t_name)

                                sorted_tags = sorted(current_tags)
                                modified = set_xptags(task.img_path, sorted_tags)

                                # Fetch updated file mtime after EXIF write and sync DB records
                                new_mtime = task.img_path.stat().st_mtime if task.img_path.exists() else task.img_mtime

                                now_iso = datetime.now(UTC).isoformat()
                                conn = get_connection()
                                try:
                                    with conn:
                                        conn.execute(
                                            "UPDATE images SET last_modified = ?, exif_mtime = ? WHERE id = ?",
                                            (new_mtime, new_mtime, task.img_id),
                                        )
                                        conn.execute(
                                            "UPDATE tag_evaluations SET image_mtime = ? WHERE image_id = ?",
                                            (new_mtime, task.img_id),
                                        )
                                        conn.execute("DELETE FROM image_tags WHERE image_id = ?", (task.img_id,))
                                        for t in sorted_tags:
                                            conn.execute(
                                                "INSERT OR IGNORE INTO image_tags (image_id, tag_name, source, added_at) VALUES (?, ?, 'model', ?)",
                                                (task.img_id, t, now_iso),
                                            )
                                finally:
                                    conn.close()

                                if modified:
                                    with counters_lock:
                                        successfully_tagged += 1

                    except Exception as exc:
                        with counters_lock:
                            failed_count += 1
                            errors.append(f"{task.img_path.name}: {exc}")
                        logger.error("Failed in writer for %s: %s", task.img_path.name, exc)
                    finally:
                        self.state.update_progress(task.img_path.name)

            prefetch_thread = threading.Thread(target=prefetch_worker, name="PrefetchWorker")
            writer_thread = threading.Thread(target=writer_worker, name="WriterWorker")

            prefetch_thread.start()
            writer_thread.start()

            with ThreadPoolExecutor(max_workers=concurrency) as executor:
                inference_futures = [executor.submit(ai_inference_worker) for _ in range(concurrency)]

                prefetch_thread.join()

                if self.state.stop_requested:
                    while not prefetch_queue.empty():
                        try:
                            prefetch_queue.get_nowait()
                        except queue.Empty:
                            break
                else:
                    for _ in range(concurrency):
                        with contextlib.suppress(queue.Full):
                            prefetch_queue.put(_PREFETCH_SENTINEL, timeout=1.0)

                for future in inference_futures:
                    try:
                        future.result()
                    except Exception as exc:
                        logger.error("Unexpected worker error: %s", exc)

                with contextlib.suppress(queue.Full):
                    write_queue.put(_WRITE_SENTINEL, timeout=1.0)
                writer_thread.join(timeout=10.0)

            summary = {
                "root_directory": config.root_directory,
                "total_images_found": total_found,
                "total_processed": self.state.processed,
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

    def pause(self) -> dict:
        """Pause current processing session."""
        self.state.set_paused()
        return {
            "status": "paused",
            "processed": self.state.processed,
        }

    def resume(self) -> dict:
        """Resume current processing session with reloaded configuration."""
        from exif_tagger.config import compute_tag_hash
        from exif_tagger.db import evaluate_thresholds_locally

        config = self._load_config()
        self._live_tag_hashes = {name: compute_tag_hash(tag_def.description) for name, tag_def in config.tags.items()}

        # Zero-cost local threshold re-evaluation with updated tags/thresholds
        try:
            evaluate_thresholds_locally(
                root_directory=config.root_directory,
                active_tags=config.tags,
                tag_hashes=self._live_tag_hashes,
            )
        except Exception as e:
            logging.getLogger("exif_tagger").warning("Local threshold re-evaluation failed on resume: %s", e)

        self.state.set_resumed()
        return {
            "status": "resumed",
            "processed": self.state.processed,
        }

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
        return self.state.get_status()


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
