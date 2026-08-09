# Root Directory Scoping & Path Jail Design

## Context & Goal
The EXIF Tagger application uses a configured `root_directory` (e.g., `/data/images`) as the base gallery root for storing and tagging image files. 

Previously, user folder selections could be interpreted as absolute system filesystem paths or allow path traversal beyond the configured root directory.

The goal of this feature is to:
1. Enforce `config.root_directory` as a strict jail root for all image processing operations.
2. Treat all user-entered folder paths (e.g. `/vacation`, `vacation`, `/`) as relative to the configured image root directory.
3. Automatically reject any path traversal or breakout attempts (e.g. `../../etc/passwd` or `/../outside`) with a clear error message displayed to the user via the Web UI.
4. Ensure the frontend never exposes or requires knowledge of the underlying host filesystem path (`/data/images`), keeping all UI paths relative to the image root.

## Architectural Changes

### 1. Path Resolution & Boundary Check Helper
A helper function `validate_and_resolve_subfolder(user_path: str | None, base_gallery_root: Path) -> tuple[Path, str | None]` will be implemented in `src/exif_tagger/main.py`.

- **Normalizing Leading Slashes**:
  Any leading slashes (`/` or `\`) in `user_path` are stripped, so `/folder/subfolder` is converted to relative string `folder/subfolder`.
- **Resolving Target Path**:
  The candidate path is computed as `(base_gallery_root / clean_relative_path).resolve()`.
- **Boundary Verification**:
  Boundary compliance is verified using `candidate.relative_to(base_gallery_root.resolve())`.
  If `relative_to` raises `ValueError` (indicating the path is outside `base_gallery_root`), `validate_and_resolve_subfolder` raises `ValueError(f"Requested path '{user_path}' is outside the root image directory.")`.
- **Return Value**:
  Returns `(base_gallery_root, relative_subfolder_str)` where `relative_subfolder_str` is a POSIX-formatted relative string (e.g. `"folder/subfolder"`) or `None` if pointing to the root itself.

### 2. API Validation (`src/exif_tagger/server.py`)
In `/api/start` (`POST /api/start`):
- Before spawning the processing session background thread, `req.rootDirectory` is validated synchronously against `validate_and_resolve_subfolder`.
- If a `ValueError` is caught, `/api/start` returns `HTTPException(status_code=400, detail=str(e))`.
- The Web UI's `useProcessing.ts` receives HTTP 400 with `errData.detail` and triggers `showToast(res.error, 'error')`, displaying a clear red error message to the user.

### 3. Pipeline Execution (`src/exif_tagger/main.py`)
In `PipelineEngine.start_session`:
- Calls `validate_and_resolve_subfolder(root_directory, base_gallery_root)`.
- Scopes DB queries and image scanning exclusively to `target_subfolder`.
- If an unhandled exception or validation failure occurs in the thread, updates `self.state.error` to reflect the failure message.

## Edge Cases Handled
- `root_directory` = `None`, `""`, `/`, `.`: All resolve to root (`target_subfolder = None`).
- `root_directory` = `"/sub1/sub2"`: Stripped to `"sub1/sub2"`, resolves to `<gallery_root>/sub1/sub2`.
- `root_directory` = `"../../etc"` or `"/../outside"`: Boundary check fails $\rightarrow$ raises `ValueError` $\rightarrow$ 400 Bad Request error returned to user.

## Testing Strategy
- Unit tests in `tests/test_subfolder_processing.py`:
  - Verify `/subfolder` and `subfolder` resolve identically to `<gallery_root>/subfolder`.
  - Verify directory breakout attempts (`/../`, `../../`, `/etc/passwd`) raise `ValueError`.
  - Verify `/api/start` returns HTTP 400 with error detail when passed an escaping path.
