"""Pydantic-modeller för exif-tagger-konfiguration och AI-respons."""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ---------------------------------------------------------------------------
# Image support – vilka filändelser vi accepterar
# ---------------------------------------------------------------------------
IMAGE_EXTENSIONS: frozenset[str] = frozenset({".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp", ".heic", ".heif"})


# ---------------------------------------------------------------------------
# Model configuration (OpenAI-compatible endpoint)
# ---------------------------------------------------------------------------
class ModelConfig(BaseModel):
    """Konfiguration för vision-modellen som anropas via OpenAI-compatible API."""

    base_url: str = Field(description="Base URL to the OpenAI-compatible API endpoint (e.g. https://api.openai.com/v1)")
    model_name: str = Field(description="Name of the vision model (e.g. gpt-4o, claude-3-opus via bridge)")
    api_key: str | None = Field(
        default=None,
        description="API key for authentication. Can be set via env var OPENAI_API_KEY.",
    )
    max_tokens: int = Field(default=500, ge=100, le=4096)
    temperature: float = Field(default=0.1, ge=0.0, le=2.0)
    use_structured_outputs: bool = Field(
        default=False,
        description="When True, uses OpenAI response_format with JSON Schema for guaranteed valid structured output.",
    )
    image_format: str = Field(
        default="jpeg",
        description="Image format sent to the vision API. 'jpeg' (default for max compatibility) or 'webp'.",
    )
    image_quality: int = Field(
        default=80,
        ge=1,
        le=100,
        description="Compression quality for the image sent to the vision API (1–100). Lower = smaller payload.",
    )
    concurrency: int = Field(
        default=1,
        ge=1,
        le=16,
        description="Number of parallel vision API requests. Increase to saturate local GPU batching (2–4 recommended for local models).",
    )
    params: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional parameters passed directly to the vision API call. "
        "Explicit fields like temperature and max_tokens take priority over duplicate keys.",
    )

    @field_validator("image_format", mode="before")
    @classmethod
    def _validate_image_format(cls, value: str) -> str:
        allowed = {"webp", "jpeg"}
        if isinstance(value, str) and value.lower() in allowed:
            return value.lower()
        raise ValueError(f"image_format must be one of {allowed}, got '{value}'")

    model_config = ConfigDict(extra="allow")


# Tag definition
# ---------------------------------------------------------------------------
class TagDefinition(BaseModel):
    """En enskild tagg med beskrivning och tröskelvärde för matchning."""

    description: str = Field(description="Beskrivning av vad en bild ska uppfylla för att matcha denna tagg")
    threshold: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="Tröskel (0-1). Bilder med score >= threshold får taggen.",
    )


# ---------------------------------------------------------------------------
# Top-level configuration
# ---------------------------------------------------------------------------
class GalleryIndexConfig(BaseModel):
    """Settings for the background gallery index poller."""

    enabled: bool = Field(default=True)
    poll_interval_seconds: int = Field(default=10, ge=0, description="0 disables the poller")


class Config(BaseModel):
    """Hela konfigurationen av exif-tagger."""

    root_directory: str = Field(
        default="/data/images",
        description="Sökväg till rot-mappen som ska skannas rekursivt",
    )
    ai_model: ModelConfig = Field(alias="model", default_factory=ModelConfig)
    tags: dict[str, TagDefinition] = Field(default_factory=dict)
    gallery_index: GalleryIndexConfig = Field(default_factory=GalleryIndexConfig)
    exclude_patterns: list[str] = Field(
        default_factory=list,
        description="Reguljära uttryck för sökväg som ska exkluderas från körningen.",
    )
    max_image_dimension: int = Field(
        default=720,
        ge=100,
        le=4096,
        description="Maximal bilddimension (bred eller hög) innan skalning till AI-modellen.",
    )
    log_level: str = Field(
        default="INFO",
        description="Global log level: DEBUG, INFO, WARNING, ERROR, CRITICAL",
    )
    log_dir: str = Field(
        default="/app/logs",
        description="Directory path for daily rotating log files",
    )

    @field_validator("log_level", mode="before")
    @classmethod
    def _validate_log_level(cls, value: Any) -> str:
        valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if isinstance(value, str):
            upper_val = value.strip().upper()
            if upper_val in valid_levels:
                return upper_val
        raise ValueError(f"Invalid log level '{value}'. Must be one of: {', '.join(sorted(valid_levels))}")

    # Validation & convenience methods
    def validate(self) -> None:
        """Run extra validation beyond Pydantic's built-in checks."""
        root = Path(self.root_directory)
        if not root.exists():
            raise ValueError(f"root_directory does not exist: {self.root_directory}")
        if not root.is_dir():
            raise ValueError(f"root_directory is not a directory: {self.root_directory}")

    def validate_exclude_patterns(self) -> None:
        """Verify that all exclude patterns compile as valid regex."""
        for pattern in self.exclude_patterns:
            try:
                re.compile(pattern)
            except re.error as exc:
                raise ValueError(f"Invalid regex pattern '{pattern}': {exc}") from exc

    model_config = ConfigDict(extra="allow")


# ---------------------------------------------------------------------------
# AI response model (structured output from vision model)
# ---------------------------------------------------------------------------
class TagResult(BaseModel):
    """One tag evaluation result from the AI."""

    tag_name: str
    score: float = Field(ge=0.0, le=1.0, description="Confidence score 0-1")
    reason: str | None = None


class TaggingResponse(BaseModel):
    """Full response from vision model for a single image."""

    results: list[TagResult]
    summary: str | None = None


# ---------------------------------------------------------------------------
# Checkpoint data (persisted to JSON)
# ---------------------------------------------------------------------------
class ImageCheckpoint(BaseModel):
    """Status for a single processed image."""

    path: str
    status: str  # "pending", "done", "failed"
    matched_tags: list[str] = Field(default_factory=list)
    error: str | None = None


class CheckpointData(BaseModel):
    """Full checkpoint – tracks progress for resumable runs."""

    version: int = Field(default=1)
    created_at: str  # ISO timestamp
    root_directory: str
    total_images: int
    processed: int
    images: dict[str, ImageCheckpoint]  # path -> status


# ---------------------------------------------------------------------------
# Schedule configuration (persisted to schedules.json)
# ---------------------------------------------------------------------------
class ScheduleModel(BaseModel):
    """A single scheduled processing job."""

    id: str = Field(default_factory=lambda: f"schedule_{int(time.time())}_{hash(str(time.time())) % 10000}")
    name: str = Field(description="Human-readable schedule name")
    folder: str = Field(description="Root directory to scan for images")
    max_images: int | None = Field(default=None, description="Max images per run (None = all)")
    interval_hours: float | None = Field(default=None, ge=0.1, description="Interval in hours (for simple intervals)")
    cron_expression: str | None = Field(default=None, description="Cron expression (e.g. '0 2 * * *')")
    enabled: bool = Field(default=True)
    last_run_at: str | None = Field(default=None, description="ISO timestamp of last run")
    last_status: str | None = Field(default=None, description="'success', 'failed', or None")

    @field_validator("cron_expression", mode="before")
    @classmethod
    def _validate_cron(cls, value):  # type: ignore[no-untyped-def]
        if value is None:
            return None
        parts = str(value).strip().split()
        if len(parts) != 5:
            raise ValueError("Cron expression must have exactly 5 fields (minute hour day month weekday)")
        return value

    model_config = ConfigDict(extra="allow")
