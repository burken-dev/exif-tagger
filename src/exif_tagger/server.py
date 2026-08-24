"""FastAPI server for exif-tagger web dashboard.

Provides REST API endpoints and serves the single-page dashboard UI.
Runs as a long-lived service (uvicorn) instead of CLI batch execution.
"""

from __future__ import annotations

import io
import json
import logging
import os
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from PIL import Image
from pydantic import BaseModel

from exif_tagger.ai_client import SecretRedactor, setup_secure_logging
from exif_tagger.config import get_config_path, load_config
from exif_tagger.main import PipelineEngine, validate_and_resolve_subfolder
from exif_tagger.models.schema import IMAGE_EXTENSIONS, ScheduleModel, TagDefinition

logger = logging.getLogger(__name__)


app = FastAPI(title="EXIF Tagger", version="0.1.0")

_engine: PipelineEngine | None = None
_engine_lock = threading.Lock()
_schedules: dict[str, ScheduleModel] = {}
_scheduler: BackgroundScheduler | None = None
_config_dir = Path(__file__).resolve().parent.parent.parent


def get_schedules_file_path() -> Path:
    env_path = os.environ.get("EXIFTAGGER_SCHEDULES_FILE")
    if env_path:
        return Path(env_path)
    data_dir = os.environ.get("EXIFTAGGER_DATA_DIR")
    if data_dir:
        return Path(data_dir) / "schedules.json"
    return _config_dir / "schedules.json"


CONFIG_PATH = str(get_config_path())
SCHEDULES_FILE = get_schedules_file_path()


# Setup server-log folder for debugging server errors
SERVER_LOG_DIR = _config_dir / "server-log"
SERVER_LOG_DIR.mkdir(parents=True, exist_ok=True)


_log_formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

_error_file_handler = logging.FileHandler(SERVER_LOG_DIR / "error.log")
_error_file_handler.setLevel(logging.ERROR)
_error_file_handler.setFormatter(_log_formatter)
_error_file_handler.addFilter(SecretRedactor())

_server_file_handler = logging.FileHandler(SERVER_LOG_DIR / "server.log")
_server_file_handler.setLevel(logging.INFO)
_server_file_handler.setFormatter(_log_formatter)
_server_file_handler.addFilter(SecretRedactor())

_root_logger = logging.getLogger()
_root_logger.addHandler(_error_file_handler)
_root_logger.addHandler(_server_file_handler)


class StartRequest(BaseModel):
    rootDirectory: str | None = None
    maxImages: int | None = None


class ScheduleCreateRequest(BaseModel):
    name: str
    folder: str
    interval_hours: float | None = None
    cron_expression: str | None = None
    enabled: bool = True
    max_images: int | None = None


def _get_engine() -> PipelineEngine:
    """Get or create the pipeline engine instance."""
    global _engine
    if _engine is None:
        _engine = PipelineEngine(config_path=CONFIG_PATH, verbose=True)
    return _engine


def _load_schedules() -> dict[str, ScheduleModel]:
    """Load schedules from disk."""
    schedules_file = get_schedules_file_path()
    if schedules_file.exists():
        try:
            with open(schedules_file) as f:
                data = json.load(f)
            return {sid: ScheduleModel(**sdata) for sid, sdata in data.items()}
        except (json.JSONDecodeError, Exception):
            pass
    return {}


def _save_schedules() -> None:
    """Persist schedules to disk."""
    schedules_file = get_schedules_file_path()
    schedules_file.parent.mkdir(parents=True, exist_ok=True)
    with open(schedules_file, "w") as f:
        json.dump({sid: s.model_dump() for sid, s in _schedules.items()}, f, indent=2)


def _compute_next_run(schedule: ScheduleModel) -> str | None:
    """Compute next run time based on schedule type."""
    now = datetime.now(UTC)
    if schedule.cron_expression:
        parts = schedule.cron_expression.strip().split()
        if len(parts) == 5:
            minute, hour, dom, month, dow = parts
            try:
                from apscheduler.triggers.cron import CronTrigger

                trigger = CronTrigger(minute=minute, hour=hour, day=dom, month=month, day_of_week=dow, timezone=UTC)
                next_fire = trigger.get_next_fire_time(None, now)
                return next_fire.isoformat() if next_fire else None
            except Exception:
                return None
    elif schedule.interval_hours:
        from datetime import timedelta

        next_run = now.replace(microsecond=0) + timedelta(hours=schedule.interval_hours)
        return next_run.isoformat()
    return None


def _run_schedule_job(schedule_id: str) -> None:
    """Execute a scheduled job."""
    global _engine
    schedule = _schedules.get(schedule_id)
    if not schedule or not schedule.enabled:
        return

    logger.info("Running scheduled job: %s (folder=%s)", schedule.name, schedule.folder)

    job_engine = PipelineEngine(config_path=CONFIG_PATH, verbose=False)
    summary = job_engine.start_session(
        root_directory=schedule.folder,
        max_images=schedule.max_images,
    )

    now = datetime.now(UTC).isoformat()
    schedule.last_run_at = now
    schedule.last_status = "success" if not summary.get("errors") else "failed"
    _save_schedules()


def _setup_scheduler() -> None:
    """Initialize or reinitialize APScheduler with loaded schedules."""
    global _scheduler

    # Shutdown any existing scheduler before creating a new one.
    if _scheduler and _scheduler.running:
        logger.info("Shutting down existing scheduler before rebuild")
        _scheduler.shutdown(wait=False)

    _schedules.clear()
    _schedules.update(_load_schedules())

    from apscheduler.triggers.cron import CronTrigger
    from apscheduler.triggers.interval import IntervalTrigger

    _scheduler = BackgroundScheduler(timezone=UTC)
    _scheduler.start()

    for sid, schedule in _schedules.items():
        if not schedule.enabled:
            continue

        trigger = None
        if schedule.cron_expression:
            parts = schedule.cron_expression.strip().split()
            if len(parts) == 5:
                minute, hour, dom, month, dow = parts
                try:
                    trigger = CronTrigger(minute=minute, hour=hour, day_of_week=dow, day=dom, month=month, timezone=UTC)
                except Exception as e:
                    logger.warning("Invalid cron expression for schedule '%s': %s", sid, e)
        elif schedule.interval_hours:
            trigger = IntervalTrigger(hours=schedule.interval_hours, timezone=UTC)

        if trigger:
            try:
                _scheduler.add_job(
                    _run_schedule_job,
                    trigger=trigger,
                    args=[sid],
                    id=f"schedule_{sid}",
                    replace_existing=True,
                )
            except Exception as e:
                logger.warning("Failed to add job for schedule '%s': %s", sid, e)

    try:
        cfg = load_config(CONFIG_PATH)
        gidx = cfg.gallery_index
        if gidx.enabled and gidx.poll_interval_seconds > 0:
            _scheduler.add_job(
                _run_gallery_poll,
                trigger=IntervalTrigger(seconds=gidx.poll_interval_seconds, timezone=UTC),
                id="gallery_index_poll",
                replace_existing=True,
                coalesce=True,
                max_instances=1,
            )
            logger.info("Gallery index poller registered (every %ss)", gidx.poll_interval_seconds)
    except Exception as exc:
        logger.warning("Failed to register gallery index poller: %s", exc)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error("Unhandled exception processing request %s %s: %s", request.method, request.url, exc, exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": f"Internal server error: {exc}"},
    )


@app.get("/api/status")
def api_status():
    engine = _get_engine()
    status = engine.get_status()
    summary = engine.state.summary
    # Ensure total is consistent between top-level and summary.
    if "total" in status and summary is not None:
        status["total"] = summary.get("total_processed", status["total"])
    return {**status, "summary": summary}


@app.post("/api/start")
def api_start(req: StartRequest):
    global _engine

    with _engine_lock:
        if _engine and _engine.state.running:
            raise HTTPException(status_code=409, detail="A processing session is already running")

        engine = _get_engine()
        config = engine._load_config()
        base_gallery_root = Path(config.root_directory).resolve()
        try:
            validate_and_resolve_subfolder(req.rootDirectory, base_gallery_root)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        _engine = PipelineEngine(config_path=CONFIG_PATH, verbose=True)

    def run_session():
        _get_engine().start_session(
            root_directory=req.rootDirectory,
            max_images=req.maxImages,
        )

    thread = threading.Thread(target=run_session, daemon=True)
    thread.start()
    return {"status": "started"}


@app.post("/api/pause")
def api_pause():
    engine = _get_engine()
    if not engine.state.running:
        raise HTTPException(status_code=400, detail="No active processing session is running")
    if engine.state.paused:
        raise HTTPException(status_code=400, detail="Processing session is already paused")

    result = engine.pause()
    return result


@app.post("/api/resume")
def api_resume():
    engine = _get_engine()
    if not engine.state.running:
        raise HTTPException(status_code=400, detail="No active processing session is running")
    if not engine.state.paused:
        raise HTTPException(status_code=400, detail="Processing session is not paused")

    result = engine.resume()
    return result


@app.post("/api/stop")
def api_stop():
    engine = _get_engine()
    if not engine.state.running:
        raise HTTPException(status_code=400, detail="No processing session is running")

    result = engine.stop()
    return result


@app.get("/api/config")
def api_get_config():
    try:
        config = load_config(CONFIG_PATH)
        return {
            "root_directory": config.root_directory,
            "model": {
                "base_url": config.ai_model.base_url,
                "model_name": config.ai_model.model_name,
                "max_tokens": config.ai_model.max_tokens,
                "temperature": config.ai_model.temperature,
                "api_key": config.ai_model.api_key or "",
                "use_structured_outputs": getattr(config.ai_model, "use_structured_outputs", False),
                "max_image_dimension": getattr(
                    config.ai_model, "max_image_dimension", getattr(config, "max_image_dimension", 720)
                ),
                "image_format": getattr(config.ai_model, "image_format", "jpeg"),
                "image_quality": getattr(config.ai_model, "image_quality", 80),
                "concurrency": getattr(config.ai_model, "concurrency", 1),
                "params": config.ai_model.params or {},
            },
            "tags": {name: td.model_dump() for name, td in config.tags.items()},
            "exclude_patterns": config.exclude_patterns or [],
            "log_level": getattr(config, "log_level", "INFO"),
            "log_dir": getattr(config, "log_dir", "/app/logs"),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load config: {e}")


@app.put("/api/config")
def api_update_config(updates: dict[str, Any]):
    import yaml

    try:
        if Path(CONFIG_PATH).exists():
            with open(CONFIG_PATH) as f:
                current = yaml.safe_load(f) or {}
        else:
            current = {}

        if "root_directory" in updates:
            current["root_directory"] = updates["root_directory"]

        if "model" in updates and isinstance(updates["model"], dict):
            model_section = current.setdefault("model", {})
            for key, val in updates["model"].items():
                model_section[key] = val

        if "tags" in updates:
            tag_defs = {}
            for name, tdata in updates["tags"].items():
                td = TagDefinition(**tdata)
                tag_defs[name] = td.model_dump()
            current["tags"] = tag_defs

        if "exclude_patterns" in updates:
            patterns = updates["exclude_patterns"]
            if isinstance(patterns, str):
                patterns = [patterns]
            current["exclude_patterns"] = patterns

        if "log_level" in updates:
            current["log_level"] = updates["log_level"]

        if "log_dir" in updates:
            current["log_dir"] = updates["log_dir"]

        from exif_tagger.models.schema import Config as SchemaConfig

        validated = SchemaConfig(**current)
        validated.validate()
        validated.validate_exclude_patterns()

        with open(CONFIG_PATH, "w") as f:
            yaml.safe_dump(current, f, default_flow_style=False, sort_keys=False)

        return {"status": "updated"}

    except Exception as e:
        # Format Pydantic validation errors into a human-readable message
        error_detail = str(e)
        try:
            import re

            # Extract field: error pairs from Pydantic output
            matches = re.findall(r"(\w+):\s*(.+?)(?=,\s*\w+:|$)", error_detail)
            if matches:
                error_detail = "; ".join(f"{field}: {msg.strip()}" for field, msg in matches)
        except Exception:
            pass
        raise HTTPException(status_code=400, detail=f"Invalid config update: {error_detail}")


# ---------------------------------------------------------------------------
# API Routes — Schedules
# ---------------------------------------------------------------------------


@app.get("/api/schedule")
def api_list_schedules():
    """List all configured schedules with computed next_run_at."""
    result = []
    for sid, schedule in _schedules.items():
        entry_data = schedule.model_dump()
        entry_data["next_run_at"] = _compute_next_run(schedule)
        result.append(entry_data)
    return result


@app.post("/api/schedule")
def api_create_schedule(req: ScheduleCreateRequest):
    """Add a new processing schedule."""
    sid = f"schedule_{uuid.uuid4().hex[:8]}"

    schedule = ScheduleModel(
        id=sid,
        name=req.name,
        folder=req.folder,
        max_images=req.max_images,
        interval_hours=req.interval_hours,
        cron_expression=req.cron_expression,
        enabled=req.enabled,
    )

    _schedules[sid] = schedule
    _save_schedules()

    # Add to scheduler if enabled
    if req.enabled:
        _setup_scheduler()  # Rebuild all jobs

    return {"id": sid}


@app.delete("/api/schedule/{schedule_id}")
def api_delete_schedule(schedule_id: str):
    """Remove a schedule."""
    if schedule_id not in _schedules:
        raise HTTPException(status_code=404, detail="Schedule not found")

    del _schedules[schedule_id]
    _save_schedules()

    # Rebuild scheduler without this job
    _setup_scheduler()

    return {"status": "deleted"}


@app.post("/api/schedule/{schedule_id}/run")
def api_run_schedule(schedule_id: str):
    if schedule_id not in _schedules:
        raise HTTPException(status_code=404, detail="Schedule not found")
    thread = threading.Thread(target=_run_schedule_job, args=[schedule_id], daemon=True)
    thread.start()
    return {"status": "started"}


# ---------------------------------------------------------------------------
# API Routes — Gallery
# ---------------------------------------------------------------------------

from exif_tagger.db import (
    batch_update_tags,
    get_all_tags,
    get_gallery_images,
    get_image_by_id,
    reconcile_gallery_index,
    remove_tag_globally,
    sync_gallery_index,
    sync_single_image,
    update_image_tags_in_db_and_exif,
)


class BatchTagRequest(BaseModel):
    image_ids: list[int]
    add_tags: list[str] = []
    remove_tags: list[str] = []


class GlobalTagRemoveRequest(BaseModel):
    tag_name: str


class ImageTagsUpdateRequest(BaseModel):
    tags: list[str]


class SingleImageSyncRequest(BaseModel):
    relative_path: str | None = None
    file_path: str | None = None


class GallerySyncRequest(BaseModel):
    mode: str = "all"
    folder: str | None = None
    search: str | None = None
    tags: list[str] | str | None = None


_sync_lock = threading.Lock()
_sync_state: dict[str, Any] = {
    "status": "idle",
    "stats": None,
    "error": None,
}


def _run_gallery_sync(req: GallerySyncRequest = GallerySyncRequest()) -> None:
    global _sync_state
    with _sync_lock:
        _sync_state["status"] = "running"
        _sync_state["error"] = None
    try:
        config = load_config(CONFIG_PATH)
        if req.mode == "filtered":
            tag_list = None
            if isinstance(req.tags, str):
                tag_list = [t.strip() for t in req.tags.split(",") if t.strip()]
            elif isinstance(req.tags, list):
                tag_list = req.tags

            images, total = get_gallery_images(
                offset=0,
                limit=100000,
                tags=tag_list,
                search=req.search,
                folder=req.folder,
                root_directory=config.root_directory,
            )
            synced_count = 0
            for img in images:
                path_to_sync = img.get("file_path") or img.get("relative_path")
                if path_to_sync:
                    sync_single_image(path_to_sync, root_directory=config.root_directory)
                    synced_count += 1
            stats = {
                "total": total,
                "indexed": synced_count,
                "updated": synced_count,
                "deleted": 0,
            }
        else:
            stats = sync_gallery_index(
                root_directory=config.root_directory,
                exclude_patterns=config.exclude_patterns,
            )
        logger.info("Gallery index sync complete (%s): %s", req.mode, stats)
        with _sync_lock:
            _sync_state["status"] = "complete"
            _sync_state["stats"] = stats
    except Exception as e:
        logger.warning("Gallery index sync failed: %s", e)
        with _sync_lock:
            _sync_state["status"] = "error"
            _sync_state["error"] = str(e)


def _run_gallery_poll() -> None:
    """Periodic discovery reconcile. Skips the round if a manual sync is running."""
    if not _sync_lock.acquire(blocking=False):
        logger.debug("Gallery poll skipped: sync in progress")
        return
    try:
        config = load_config(CONFIG_PATH)
        reconcile_gallery_index(config.root_directory, exclude_patterns=config.exclude_patterns)
    except Exception as exc:
        logger.warning("Gallery poll failed: %s", exc)
    finally:
        _sync_lock.release()


@app.post("/api/gallery/sync")
def api_gallery_sync(req: GallerySyncRequest = GallerySyncRequest()):
    """Trigger manual re-sync of gallery database index in background."""
    with _sync_lock:
        if _sync_state["status"] == "running":
            return {"status": "running", "message": "Gallery index sync is already running"}
        _sync_state["status"] = "running"
        _sync_state["error"] = None
        _sync_state["stats"] = None

    thread = threading.Thread(target=_run_gallery_sync, args=(req,), daemon=True)
    thread.start()
    return {"status": "started", "message": "Gallery index sync started"}


@app.get("/api/gallery/sync/status")
def api_gallery_sync_status():
    """Get status of gallery index sync."""
    with _sync_lock:
        return dict(_sync_state)


@app.get("/api/gallery/images")
async def api_get_gallery_images(
    request: Request,
    offset: int = 0,
    limit: int = 50,
    tags: str | None = None,
    search: str | None = None,
    folder: str | None = None,
):
    """List images with pagination and optional tag/search/folder filtering."""
    import asyncio

    cancelled_event = threading.Event()

    async def _monitor():
        while not cancelled_event.is_set():
            try:
                if await request.is_disconnected():
                    cancelled_event.set()
                    return
            except Exception:
                pass
            await asyncio.sleep(0.1)

    # Start disconnect monitor in background
    monitor_task = asyncio.create_task(_monitor())

    def is_cancelled():
        return cancelled_event.is_set()

    try:
        config = load_config(CONFIG_PATH)
        tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None
        images, total = get_gallery_images(
            offset=offset,
            limit=limit,
            tags=tag_list,
            search=search,
            folder=folder,
            root_directory=config.root_directory,
            is_cancelled=is_cancelled,
        )
        return {
            "images": images,
            "total": total,
            "offset": offset,
            "limit": limit,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to query gallery images: {e}")
    finally:
        cancelled_event.set()
        if not monitor_task.done():
            monitor_task.cancel()


@app.get("/api/gallery/folders")
def api_get_gallery_folders(path: str = ""):
    """Get folder hierarchy and subfolder image counts for gallery folder navigation."""
    from exif_tagger.db import get_gallery_folders

    try:
        config = load_config(CONFIG_PATH)
        data = get_gallery_folders(relative_path=path, root_directory=config.root_directory)
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to query gallery folders: {e}")


@app.get("/api/gallery/tags")
def api_get_gallery_tags():
    """Get list of all unique tags present across gallery images."""
    try:
        tag_names = get_all_tags()
        return {"tags": tag_names}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch gallery tags: {e}")


@app.get("/api/gallery/image/file")
def api_get_gallery_image_file_by_path(path: str):
    """Serve raw image file specified by query parameter `path` (relative or absolute)."""
    try:
        config = load_config(CONFIG_PATH)
        root_dir = Path(config.root_directory).resolve()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load config: {e}")

    p = Path(path)
    resolved_path = p.resolve() if p.is_absolute() else (root_dir / p).resolve()

    try:
        resolved_path.relative_to(root_dir)
    except ValueError:
        raise HTTPException(status_code=403, detail="Access denied: path is outside root directory")

    if not resolved_path.exists() or not resolved_path.is_file():
        raise HTTPException(status_code=404, detail="Image file does not exist on disk")

    if resolved_path.suffix.lower() not in IMAGE_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Invalid image file extension")

    if resolved_path.suffix.lower() in (".heic", ".heif"):
        with Image.open(resolved_path) as img:
            if img.mode != "RGB":
                img = img.convert("RGB")
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=85)
            return Response(content=buf.getvalue(), media_type="image/jpeg")

    return FileResponse(resolved_path)


@app.post("/api/gallery/image/sync")
def api_sync_single_image_endpoint(req: SingleImageSyncRequest):
    """Sync a single image by relative or absolute path into the database index."""
    target_path = req.relative_path or req.file_path
    if not target_path:
        raise HTTPException(status_code=400, detail="Path to image is required (relative_path or file_path)")

    try:
        config = load_config(CONFIG_PATH)
        result = sync_single_image(
            relative_or_abs_path=target_path,
            root_directory=Path(config.root_directory),
        )
        return result
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to sync image: {e}")


@app.get("/api/gallery/image/{image_id}")
def api_get_gallery_image(image_id: int):
    """Get single image metadata and tags by ID."""
    image_data = get_image_by_id(image_id)
    if not image_data:
        raise HTTPException(status_code=404, detail="Image not found")
    return image_data


@app.get("/api/gallery/image/{image_id}/file")
def api_get_gallery_image_file(image_id: int):
    """Serve the raw image file for rendering in the web gallery UI."""
    image_data = get_image_by_id(image_id)
    if not image_data:
        raise HTTPException(status_code=404, detail="Image not found")

    file_path = Path(image_data["file_path"])
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Image file does not exist on disk")

    if file_path.suffix.lower() in (".heic", ".heif"):
        with Image.open(file_path) as img:
            if img.mode != "RGB":
                img = img.convert("RGB")
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=85)
            return Response(content=buf.getvalue(), media_type="image/jpeg")

    return FileResponse(file_path)


@app.put("/api/gallery/image/{image_id}/tags")
def api_update_gallery_image_tags(image_id: int, req: ImageTagsUpdateRequest):
    """Manually update tags for a single image."""
    try:
        config = load_config(CONFIG_PATH)
        success = update_image_tags_in_db_and_exif(
            image_id=image_id,
            tags=req.tags,
            base_dir=Path(config.root_directory),
        )
        if not success:
            raise HTTPException(status_code=404, detail="Image not found")
        return {"status": "updated"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update image tags: {e}")


@app.post("/api/gallery/batch-tags")
def api_batch_update_tags(req: BatchTagRequest):
    """Batch add/remove tags across multiple images."""
    try:
        config = load_config(CONFIG_PATH)
        modified = batch_update_tags(
            image_ids=req.image_ids,
            add_tags=req.add_tags,
            remove_tags=req.remove_tags,
            base_dir=Path(config.root_directory),
        )
        return {"status": "success", "modified": modified}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed batch update: {e}")


@app.post("/api/gallery/remove-tag-global")
def api_remove_tag_global(req: GlobalTagRemoveRequest):
    """Remove a specified tag from ALL images in the gallery."""
    try:
        config = load_config(CONFIG_PATH)
        modified = remove_tag_globally(
            tag_name=req.tag_name,
            base_dir=Path(config.root_directory),
        )
        return {"status": "success", "modified": modified}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to remove tag globally: {e}")


@app.get("/api/gallery/image/{image_id}/suppressions")
def api_get_gallery_image_suppressions(image_id: int):
    """Get list of user suppressions (blacklisted tags) for an image."""
    from exif_tagger.db import get_image_suppressions

    try:
        suppressions = get_image_suppressions(image_id)
        return {"suppressions": suppressions}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch suppressions: {e}")


@app.delete("/api/gallery/image/{image_id}/suppressions/{tag_name}")
def api_delete_gallery_image_suppression(image_id: int, tag_name: str):
    """Remove a user suppression, unblacklisting the tag for future automated runs."""
    from exif_tagger.db import remove_user_suppression

    try:
        remove_user_suppression(image_id, tag_name)
        return {"status": "removed"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to remove suppression: {e}")


from fastapi.staticfiles import StaticFiles

# ---------------------------------------------------------------------------
# UI Routes — serve the dashboard
# ---------------------------------------------------------------------------

WEBUI_DIR = Path(__file__).parent.parent.parent / "webui"
WEBUI_DIST_DIR = WEBUI_DIR / "dist"

assets_dir = WEBUI_DIST_DIR / "assets"
if not assets_dir.exists():
    assets_dir.mkdir(parents=True, exist_ok=True)
app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")


def _get_index_response() -> FileResponse:
    """Return compiled dist/index.html if built, otherwise fallback to webui/index.html."""
    dist_index = WEBUI_DIST_DIR / "index.html"
    if dist_index.exists():
        return FileResponse(dist_index)
    return FileResponse(WEBUI_DIR / "index.html")


@app.get("/")
def index():
    """Serve the main dashboard page."""
    return _get_index_response()


@app.get("/processing")
@app.get("/gallery")
@app.get("/config")
@app.get("/schedule")
def ui_routes():
    """Support direct SPA routing to dashboard tabs."""
    return _get_index_response()


# ---------------------------------------------------------------------------
# Startup & Shutdown lifespan (modern FastAPI pattern, replaces deprecated @app.on_event)
# ---------------------------------------------------------------------------

from contextlib import asynccontextmanager


@asynccontextmanager
async def lifespan(app_instance: FastAPI):  # type: ignore[no-untyped-def]
    """Lifespan context manager for startup and shutdown events."""
    config = None
    try:
        config = load_config(CONFIG_PATH)
        log_level = getattr(config, "log_level", "INFO")
        log_dir = getattr(config, "log_dir", "/app/logs")
        setup_secure_logging(level=log_level, log_dir=log_dir)
    except Exception as exc:
        setup_secure_logging()
        logger.warning("Could not load config for server logging setup: %s", exc)

    logger.info("EXIF Tagger API starting up...")
    _setup_scheduler()
    logger.info(f"Loaded {len(_schedules)} schedules")

    # Build the discovery index synchronously so gallery reads are never empty.
    if config is not None:
        with _sync_lock:
            reconcile_gallery_index(config.root_directory, exclude_patterns=config.exclude_patterns)

    # Start background gallery index sync (EXIF/derived state)
    threading.Thread(target=_run_gallery_sync, daemon=True).start()

    yield
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)


app.router.lifespan_context = lifespan


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8080)
