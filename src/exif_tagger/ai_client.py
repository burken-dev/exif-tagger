"""AI client - OpenAI-compatible vision API with batch processing."""

from __future__ import annotations

import base64
import json
import logging
import re
import threading
import time
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Any

from openai import OpenAI
from PIL import Image

_CLIENT_CACHE: dict[tuple[str, str], OpenAI] = {}
_CLIENT_CACHE_LOCK = threading.Lock()


def get_openai_client(base_url: str, api_key: str | None = None) -> OpenAI:
    """Return a cached, persistent OpenAI client instance for connection reuse."""
    key = (base_url or "", api_key or "")
    with _CLIENT_CACHE_LOCK:
        if key not in _CLIENT_CACHE:
            _CLIENT_CACHE[key] = OpenAI(base_url=base_url, api_key=api_key or "EMPTY")
        return _CLIENT_CACHE[key]


def clear_client_cache() -> None:
    """Clear all cached OpenAI client instances."""
    with _CLIENT_CACHE_LOCK:
        _CLIENT_CACHE.clear()


from exif_tagger.models.schema import (
    ModelConfig,
    TagDefinition,
    TaggingResponse,
    TagResult,
)

logger = logging.getLogger(__name__)


class SecretRedactor(logging.Filter):
    SECRET_PATTERNS = [
        r"sk-[a-zA-Z0-9]{20,}",
        r'api_key[=:]\s*["\']?[^\s"\']+["\']?',
        r"Bearer\s+[a-zA-Z0-9\-_]+",
        r"Authorization:\s*[^\s]+",
        r"x-api-key:\s*[^\s]+",
        r"api-key:\s*[^\s]+",
    ]

    def __init__(self, name: str = ""):
        super().__init__(name)
        self._compiled_patterns = [re.compile(p) for p in self.SECRET_PATTERNS]

    def filter(self, record: logging.LogRecord) -> bool:
        original_message = record.getMessage()
        redacted_message = original_message

        for pattern in self._compiled_patterns:
            redacted_message = pattern.sub("[REDACTED]", redacted_message)

        if redacted_message != original_message:
            record.msg = redacted_message
            record.args = ()  # Clear args to prevent formatting with original values

        return True


def setup_secure_logging(
    level: int | str = logging.INFO,
    log_dir: str = "/app/logs",
    logger_name: str = "exif_tagger",
) -> None:
    log_level = getattr(logging, level.upper(), logging.INFO) if isinstance(level, str) else level

    main_logger = logging.getLogger(logger_name)
    main_logger.setLevel(log_level)

    if main_logger.handlers:
        for handler in main_logger.handlers:
            handler.setLevel(log_level)
        return

    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%H:%M:%S")
    redactor = SecretRedactor()

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    stream_handler.addFilter(redactor)
    stream_handler.setLevel(log_level)
    main_logger.addHandler(stream_handler)

    try:
        log_path = Path(log_dir)
        log_path.mkdir(parents=True, exist_ok=True)
        file_handler = TimedRotatingFileHandler(
            log_path / "exif-tagger.log",
            when="midnight",
            interval=1,
            backupCount=30,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        file_handler.addFilter(redactor)
        file_handler.setLevel(log_level)
        main_logger.addHandler(file_handler)
    except (OSError, PermissionError) as exc:
        logger.warning("Could not setup file logging in '%s': %s", log_dir, exc)


MAX_IMAGE_DIMENSION = 1024
MAX_RETRIES = 3
RETRY_BASE_DELAY = 2.0
JPEG_QUALITY = 85


def _image_to_base64(
    image_path: Path,
    max_dim: int = MAX_IMAGE_DIMENSION,
    fmt: str = "jpeg",
    quality: int = 80,
) -> str:
    """Convert a local image file to base64-encoded JPEG or WebP with fast downsampling."""
    import io

    with Image.open(image_path) as img:
        # Fast draft downsample for JPEG
        if hasattr(img, "draft") and img.format == "JPEG":
            img.draft("RGB", (max_dim, max_dim))

        if img.mode != "RGB":
            img = img.convert("RGB")

        if max(img.size) > max_dim:
            img.thumbnail((max_dim, max_dim), Image.Resampling.BILINEAR)

        buffer = io.BytesIO()
        pil_format = "WEBP" if fmt.lower() == "webp" else "JPEG"
        img.save(buffer, format=pil_format, quality=quality)
        return base64.b64encode(buffer.getvalue()).decode("utf-8")


def _build_prompt(
    tag_definitions: dict[str, TagDefinition],
    use_structured_outputs: bool = False,
) -> str:
    """Build the prompt that asks the model to evaluate tags sparsely for one image."""
    lines = [
        "You are an expert image tagging and visual analysis system.",
        "Your task is to analyze the image objectively and evaluate candidate tags strictly based on visible visual evidence.",
        "",
        "Evaluation Instructions:",
        "1. First, write 1 concise factual sentence describing what is visible in the scene ('scene_description') to ground your analysis.",
        "2. Evaluate candidate tags against the visual evidence in the image.",
        "3. In 'results', ONLY include tags that are visibly present or plausibly present (score >= 0.2). Omit all absent tags (omitted tags automatically default to score 0.0). If no tags apply, return an empty list for 'results'.",
        "4. For each included tag, provide a concise 'reason' (max 10 words) referencing visible elements, followed by the 'score' (0.0 to 1.0):",
        "   - Score 0.8 to 1.0: Clearly, prominently, and unambiguously visible.",
        "   - Score 0.4 to 0.7: Partial, ambiguous, or background presence.",
        "   - Score 0.2 to 0.3: Minimal or faint visual presence.",
        "5. ANTI-HALLUCINATION & SPARSITY: Most photos match 0 or at most 1 tag. Do not speculate, guess, or hallucinate elements that cannot be directly seen.",
        "",
        "Tags to evaluate:",
    ]

    for name, definition in sorted(tag_definitions.items()):
        lines.append(f'- {name}: "{definition.description}"')

    if not use_structured_outputs:
        lines.extend(
            [
                "",
                "Respond ONLY with valid JSON. Use this exact structure (no trailing commas):",
                "{",
                '  "scene_description": "<1 concise factual sentence describing what is visible in the image>",',
                '  "results": [',
                "    {",
                '      "tag_name": "<tag>",',
                '      "reason": "<max 10 words referencing visible evidence>",',
                '      "score": 0.85',
                "    }",
                "  ]",
                "}",
                "",
                "Note: Only include tags with score >= 0.2. If no candidate tags apply, return \"results\": [].",
                "Do not include any text outside of the JSON object.",
            ]
        )

    return "\n".join(lines)


def _parse_response(content: str | bytes) -> TaggingResponse:
    """Parse the AI's response string into a structured TaggingResponse."""
    if isinstance(content, bytes):
        content = content.decode("utf-8", errors="replace")

    cleaned = content.strip().lstrip("\ufeff")

    # Strip markdown code fences if present (e.g. ```json ... ``` or ``` ... ```)
    if "```" in cleaned:
        import re

        match = re.search(r"```(?:json|JSON)?\s*\n?(.*?)\n?```", cleaned, re.DOTALL)
        if match:
            cleaned = match.group(1).strip()
        else:
            lines = [l for l in cleaned.splitlines() if not l.strip().startswith("```")]
            cleaned = "\n".join(lines).strip()

    # Strip any text outside the JSON object (keep first '{' to last '}')
    brace_start = cleaned.find("{")
    brace_end = cleaned.rfind("}")
    if brace_start != -1 and brace_end != -1 and brace_end > brace_start:
        cleaned = cleaned[brace_start : brace_end + 1]

    try:
        parsed = json.loads(cleaned, strict=False)
    except json.JSONDecodeError as exc:
        if cleaned != content:
            logger.error(
                "Failed to parse JSON response: %s\nText passed to json.loads:\n%s\nRaw response:\n%s",
                exc,
                cleaned,
                content,
            )
        else:
            logger.error(
                "Failed to parse JSON response: %s\nText passed to json.loads:\n%s",
                exc,
                cleaned,
            )
        raise ValueError(f"AI did not return valid JSON: {exc}\nResponse: {content[:500]}") from exc

    raw_results = parsed.get("results") or []
    tag_results = []
    for item in raw_results:
        try:
            raw_score = float(item.get("score", 0.0))
            clamped_score = max(0.0, min(1.0, raw_score))  # Clamp BEFORE pydantic validation
            tr = TagResult(
                tag_name=str(item["tag_name"]),
                score=clamped_score,
                reason=item.get("reason"),
            )
            tag_results.append(tr)
        except (KeyError, ValueError, TypeError) as exc:
            logger.warning("Skipping invalid tag result in AI response: %s", exc)

    scene_description = parsed.get("scene_description")
    summary = parsed.get("summary") or scene_description
    return TaggingResponse(
        results=tag_results,
        scene_description=scene_description,
        summary=summary,
    )


def _log_api_error_details(
    image_path: Path,
    attempt: int,
    max_retries: int,
    model_config: ModelConfig,
    prompt: str,
    image_b64_len: int,
    exc: Exception,
) -> None:
    """Log structured multi-line block with request and response details on external API error."""
    request_obj = getattr(exc, "request", None)
    url = getattr(request_obj, "url", None) or model_config.base_url

    raw_req_headers = getattr(request_obj, "headers", {}) or {}
    sanitized_req_headers: dict[str, str] = {}
    if isinstance(raw_req_headers, dict) or hasattr(raw_req_headers, "items"):
        for k, v in raw_req_headers.items():
            k_str = str(k)
            v_str = str(v)
            if k_str.lower() in ("authorization", "api-key", "x-api-key") or "sk-" in v_str:
                sanitized_req_headers[k_str] = "[REDACTED]"
            else:
                sanitized_req_headers[k_str] = v_str

    if not sanitized_req_headers:
        sanitized_req_headers = {
            "Authorization": "[REDACTED]",
            "Content-Type": "application/json",
        }

    prompt_snippet = prompt[:200] + "..." if len(prompt) > 200 else prompt
    payload_summary = {
        "model": model_config.model_name,
        "max_tokens": model_config.max_tokens,
        "temperature": model_config.temperature,
        "base_url": model_config.base_url,
        "prompt_snippet": prompt_snippet,
        "image_b64_length": image_b64_len,
    }

    response_obj = getattr(exc, "response", None)
    status_code = getattr(response_obj, "status_code", None)
    if status_code is None:
        status_code = getattr(exc, "status_code", "N/A")

    resp_headers = getattr(response_obj, "headers", None)
    if resp_headers is None:
        resp_headers = getattr(exc, "headers", "N/A")
    elif hasattr(resp_headers, "items") and not isinstance(resp_headers, dict):
        resp_headers = dict(resp_headers)

    resp_body = getattr(response_obj, "text", None)
    if resp_body is None:
        resp_body = getattr(exc, "body", None)
    if resp_body is None:
        resp_body = str(exc)

    error_log = (
        f"\n================ EXTERNAL API REQUEST ERROR ================\n"
        f"Target URL: {url}\n"
        f"HTTP Method: POST\n"
        f"Image: {image_path.name} (Attempt {attempt}/{max_retries})\n"
        f"Request Headers:\n  {sanitized_req_headers}\n"
        f"Request Payload Summary:\n  {payload_summary}\n"
        f"---------------- HTTP RESPONSE DETAILS ----------------\n"
        f"HTTP Status Code: {status_code}\n"
        f"Response Headers:\n  {resp_headers}\n"
        f"Response Body / Details:\n  {resp_body}\n"
        f"==========================================================="
    )
    logger.error(error_log)


def _build_structured_output_config() -> dict:
    """Build the response_format config for OpenAI structured outputs."""
    schema = TaggingResponse.model_json_schema()
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "tagging_response",
            "schema": schema,
        },
    }


def _call_vision_api(
    model_config: ModelConfig,
    image_path: Path,
    prompt: str,
    max_dim: int = MAX_IMAGE_DIMENSION,
    image_b64: str | None = None,
    mime_type: str | None = None,
) -> str:
    """Call the vision API with retries. Raises on persistent failure."""
    fmt = getattr(model_config, "image_format", "jpeg")
    quality = getattr(model_config, "image_quality", 80)
    if image_b64 is None:
        image_b64 = _image_to_base64(image_path, max_dim=max_dim, fmt=fmt, quality=quality)
    if mime_type is None:
        mime_type = "image/webp" if fmt.lower() == "webp" else "image/jpeg"

    # Extract system_prompt and user_prompt from params if present
    params_copy = dict(model_config.params or {})
    system_prompt = params_copy.pop("system_prompt", None)
    user_prompt_extra = params_copy.pop("user_prompt", None)

    final_prompt = prompt
    if user_prompt_extra:
        final_prompt = f"{user_prompt_extra}\n\n{prompt}"

    content_parts = [
        {"type": "text", "text": final_prompt},
        {
            "type": "image_url",
            "image_url": {
                "url": f"data:{mime_type};base64,{image_b64}",
            },
        },
    ]

    messages: list[dict[str, Any]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": content_parts})

    # Standard OpenAI kwargs accepted by client.chat.completions.create
    known_openai_kwargs = {
        "model",
        "messages",
        "max_tokens",
        "temperature",
        "top_p",
        "n",
        "stream",
        "stop",
        "presence_penalty",
        "frequency_penalty",
        "logit_bias",
        "user",
        "response_format",
        "seed",
        "tools",
        "tool_choice",
        "reasoning_effort",
        "extra_body",
        "timeout",
        "extra_headers",
        "extra_query",
    }

    top_level_kwargs: dict[str, Any] = {}
    extra_body: dict[str, Any] = dict(params_copy.pop("extra_body", {}) or {})

    for k, v in params_copy.items():
        if k in known_openai_kwargs:
            top_level_kwargs[k] = v
        else:
            extra_body[k] = v

    if extra_body:
        top_level_kwargs["extra_body"] = extra_body

    kwargs: dict = {}
    if hasattr(model_config, "extra") and model_config.extra:  # type: ignore[attr-defined]
        for key, val in model_config.extra.items():  # type: ignore[union-attr]
            if key in ("timeout",):
                kwargs[key] = val

    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            client = get_openai_client(
                base_url=model_config.base_url,
                api_key=model_config.api_key or "",
            )

            api_kwargs = {
                "model": model_config.model_name,
                "messages": messages,
                "max_tokens": model_config.max_tokens,
                "temperature": model_config.temperature,
                **top_level_kwargs,
            }

            # Structured outputs: guarantee valid JSON matching our schema
            if model_config.use_structured_outputs:  # type: ignore[attr-defined]
                api_kwargs["response_format"] = _build_structured_output_config()

            api_kwargs.update(kwargs)  # caller-provided kwargs still win

            response = client.chat.completions.create(**api_kwargs)
            return response.choices[0].message.content  # type: ignore[return-value]

        except Exception as exc:
            last_error = exc
            _log_api_error_details(
                image_path=image_path,
                attempt=attempt,
                max_retries=MAX_RETRIES,
                model_config=model_config,
                prompt=final_prompt,
                image_b64_len=len(image_b64),
                exc=exc,
            )
            logger.warning(
                "Vision API attempt %d/%d failed for %s: %s",
                attempt,
                MAX_RETRIES,
                image_path.name,
                exc,
            )
            if attempt < MAX_RETRIES:
                delay = RETRY_BASE_DELAY * (2 ** (attempt - 1))
                logger.info("Retrying in %.0f seconds...", delay)
                time.sleep(delay)

    raise RuntimeError(
        f"AI model failed after {MAX_RETRIES} attempts for image '{image_path}'. Last error: {last_error}"
    )


def tag_image_with_ai(
    model_config: ModelConfig,
    image_path: Path,
    tag_definitions: dict[str, TagDefinition],
    max_dim: int = MAX_IMAGE_DIMENSION,
    image_b64: str | None = None,
    prompt: str | None = None,
    mime_type: str | None = None,
) -> TaggingResponse:
    if not tag_definitions:
        logger.debug("No tags defined – skipping AI call for %s", image_path.name)
        return TaggingResponse(results=[])

    if prompt is None:
        use_so = getattr(model_config, "use_structured_outputs", False)  # type: ignore[attr-defined]
        prompt = _build_prompt(tag_definitions, use_structured_outputs=use_so)

    # Call with retry logic
    raw_response = _call_vision_api(
        model_config,
        image_path,
        prompt,
        max_dim=max_dim,
        image_b64=image_b64,
        mime_type=mime_type,
    )

    # Parse the response
    try:
        return _parse_response(raw_response)
    except ValueError as exc:
        logger.error("Failed to parse AI response for %s: %s", image_path.name, exc)
        raise
