# exif-tagger

AI-powered image tagging tool that scans a directory recursively, evaluates each image against configurable tags using a vision model (OpenAI-compatible), and writes matching tag names to the `XPTags` EXIF metadata field.

## ✨ Features

- **Recursive scanning** – finds all images in a root directory tree
- **Configurable tags with thresholds** – define what each tag means; match when AI confidence ≥ threshold
- **Append-mode writing** – existing XPTags are preserved; only new matching tags are added
- **Resumable runs** – evaluation state is stored per image so interrupted runs can resume
- **Regex exclude patterns** – skip directories/files that don't need tagging (e.g., thumbnails)
- **Env-var overrides** – all config values can be overridden via environment variables
- **Verbose / quiet modes** – compact summary by default; per-image details with `--verbose`
- **Docker-ready** – minimal Alpine-based image, ready to run as a container

## 📐 Architecture

```
src/exif_tagger/
├── __init__.py             # Package version (0.1.0)
├── __main__.py             # python -m exif_tagger entrypoint
├── models/schema.py        # Pydantic models: Config, TagDefinition, CheckpointData, etc.
├── config.py               # YAML loading + EXIFTAGGER_* env-var overrides
├── image_scanner.py        # Recursive directory scan with regex exclude patterns
├── ai_client.py            # OpenAI-compatible vision API client (batch strategy B)
├── exif_writer.py          # XPTags read/write via exiftool subprocess
└── main.py                 # CLI: argparse, run pipeline, summary output

tests/                      # 50 pytest tests covering all modules
config.yaml.example         # Example configuration with sample tags
docker-compose.yml          # Ready-to-run Docker Compose setup
Dockerfile                  # Multi-stage build (Alpine + exiftool via cpan/perl)
pyproject.toml              # Python ≥3.12, setuptools build system
```

### Processing pipeline

```
┌───────────────┐    ┌───────────────┐    ┌──────────────┐    ┌──────────────┐
│  Config Load  │ →  │   Image Scan  │ →  │   AI Vision  │ →  │ EXIF Write   │
│ (YAML + env)  │    │(regex filter) │    │  (batch B)   │    │  (append)    │
└───────────────┘    └───────────────┘    └──────────────┘    └──────────────┘
       │                    │                     │                      │
       ▼                    ▼                     ▼                      ▼
┌───────────────┐    ┌───────────────┐    ┌──────────────┐    ┌──────────────┐
│ .exif-tagger  │←───│ Checkpoint    │←───│ Retry (×3)   │←───│ .exif-tagger │
│ -checkpoint.  │    │ JSON          │    │ + backoff    │    │ -checkpoint. │
└───────────────┘    └───────────────┘    └──────────────┘    └──────────────┘
```

## 🚀 Quick Start

### 1. Docker (recommended)

All application state (`config.yaml`, SQLite database `gallery.db`, `schedules.json`) is stored in `/app/data` via `EXIFTAGGER_DATA_DIR=/app/data`, requiring a single persistent volume mount (`./data:/app/data`).

```bash
# Create local data directory and set up configuration
mkdir -p data
cp config.yaml.example data/config.yaml
# Edit data/config.yaml: set root_directory, model endpoint, API key

# Run with docker-compose
docker compose run --rm exif-tagger
# Or with verbose output:
docker compose run --rm exif-tagger -v
```

### 2. Local Python (development)

```bash
python -m venv .venv && source .venv/bin/activate
pip install ".[dev]"

# Run the tool
python -m exif_tagger --config config.yaml
python -m exif_tagger --verbose        # per-image logging
```

## ⚙️ Configuration

Configuration is loaded from `config.yaml` with environment variable overrides (priority order: env vars > YAML values > defaults).

### config.yaml.example

```yaml
root_directory: "/data/images"       # Recursive search root
exclude_patterns:                     # Regex patterns for paths to skip
  - "^\\.DS_Store"
  - "/\\."
  - "thumbs?_?(db|cache)?/i?"

model:                                # OpenAI-compatible vision endpoint
  base_url: "https://api.openai.com/v1"
  model_name: "gpt-4o"
  api_key: ""                         # Or set OPENAI_API_KEY env var
  max_tokens: 500
  temperature: 0.1

tags:                                 # Tag definitions with descriptions + thresholds
  landscape:
    description: "Natural scenery – mountains, forests, water, open vistas"
    threshold: 0.7                    # Score ≥ 0.7 → tag applied
  portrait:
    description: "A person's face clearly visible and in focus"
    threshold: 0.8
  architecture:
    description: "Buildings, bridges, towers, or constructed structures"
    threshold: 0.6
```

### Environment variable overrides

All config values can be overridden with `EXIFTAGGER_` prefixed variables:

| Env Var | YAML Path | Example | Description |
|---------|-----------|---------|-------------|
| `EXIFTAGGER_DATA_DIR` | – | `/app/data` | Single volume directory for config, DB (`gallery.db`), and `schedules.json` |
| `EXIFTAGGER_ROOT_DIRECTORY` | root_directory | `/data/images` | Directory tree containing images to scan and tag |
| `EXIFTAGGER_CONFIG_FILE` | – | `/path/to/custom/config.yaml` | Explicit path override for `config.yaml` |
| `EXIFTAGGER_MODEL_BASE_URL` | model.base_url | `https://ollama.local:11434/v1` | Base URL for OpenAI-compatible API |
| `EXIFTAGGER_MODEL_MODEL_NAME` | model.model_name | `llava` | Model identifier |
| `EXIFTAGGER_MODEL_API_KEY` | model.api_key | `sk-...` | API key for vision model endpoint |
| `OPENAI_API_KEY` (standard) | model.api_key fallback | `sk-...` | Standard OpenAI API key environment fallback |

## 🖥️ CLI Reference

```
python -m exif_tagger [OPTIONS]

Options:
  -c, --config PATH        Path to config.yaml (default: ./config.yaml or $EXIFTAGGER_CONFIG_FILE)
  -v, --verbose            Enable per-image logging during processing
  --list-tags              List all configured tags with descriptions & thresholds, then exit
```

### Exit codes

- `0` – successful run (all images processed or already tagged)
- `1` – error occurred (AI model failure after retries, invalid config, etc.)

## 📊 How tagging works

1. **Scan** – recursively find all supported image files (jpg, jpeg, png, tif, tiff, webp, heic, heif), excluding paths matching configured regex patterns
2. **Check evaluation state** – skip images whose tags already match the current tag descriptions
3. **AI evaluation** – for each image, send it to the vision model with ALL tag definitions in one request (batch strategy B). The model returns a confidence score 0.0–1.0 for each tag
4. **Threshold check** – if score ≥ tag's threshold → tag matches
5. **Append write** – new matching tags are appended to existing XPTags field; duplicates are skipped; already-existing tags remain untouched

### XPTags format

Tags are stored as semicolon-separated strings in the XMP `XPTags` EXIF field (tag 40094):
```
landscape;portrait;architecture
```

## 🧪 Testing

```bash
# Run all tests
pytest tests/ -v

# With coverage
pytest tests/ --cov=exif_tagger --cov-report=term-missing
```

50 passing unit tests covering:
- Configuration loading and validation (env vars, YAML)
- Image scanning with exclude patterns and deterministic ordering
- AI client prompt building, JSON parsing, score clamping, retry logic
- EXIF XPTags read/write/append/deduplication via exiftool mock
- Checkpoint persistence, resume detection, edge cases

## 🔧 Requirements

- **Python ≥ 3.12** (recommended for type annotations and performance)
- **exiftool** – required at runtime for XPTags metadata support (installed automatically in Docker image)
- OpenAI-compatible API endpoint with vision capability (e.g., gpt-4o, Claude via bridge, local Ollama + LLaVA)

### Docker image

The Dockerfile uses a multi-stage build:
1. **Builder stage**: installs Python dependencies from `requirements.txt`
2. **Runtime stage**: Alpine 3.19 with `exiftool` installed via CPAN, plus the Python packages copied from builder

## 📝 License

MIT
