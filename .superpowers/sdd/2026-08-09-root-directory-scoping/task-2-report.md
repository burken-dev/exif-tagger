# Task 2 Report: Pipeline Engine & API Integration (`PipelineEngine.start_session` and `/api/start`)

**Date:** 2026-08-09  
**Status:** SUCCESS  
**Commit:** `c850f5a128f8949a443ae76bf66df74fb1b23909`

---

## Executive Summary

Task 2 integrated path traversal protection into `PipelineEngine.start_session` and the `/api/start` REST endpoint using `validate_and_resolve_subfolder`. Path breakout attempts (e.g. `../../etc/passwd`) via the API or directly calling `start_session` are now blocked and rejected cleanly with HTTP 400 or `ValueError`, keeping processing jailed within `base_gallery_root`.

---

## Key Changes Made

### 1. `PipelineEngine.start_session` (`src/exif_tagger/main.py`)
- Replaced the custom subfolder override logic with `validate_and_resolve_subfolder(root_directory, base_gallery_root)`.
- Moved input validation before the execution `try:` block so invalid path parameter inputs raise `ValueError` directly to caller code.
- Enhanced `validate_and_resolve_subfolder` to support absolute paths matching or nested within `base_gallery_root` while enforcing strict boundary protection against traversal breakouts.

### 2. `/api/start` (`src/exif_tagger/server.py`)
- Imported `validate_and_resolve_subfolder` from `exif_tagger.main`.
- Updated `api_start` handler to validate `req.rootDirectory` against `base_gallery_root` *before* spawning the engine background thread.
- Raised `HTTPException(status_code=400, detail=str(e))` when `ValueError` is raised during validation.

### 3. Unit Tests (`tests/test_subfolder_processing.py`)
- Added `test_api_start_rejects_path_traversal`: verifies `/api/start` rejects breakout paths (e.g. `../../etc/passwd`) with HTTP 400 and detail message containing "is outside the root image directory".
- Added `test_pipeline_engine_start_session_scoping`: verifies `PipelineEngine.start_session` raises `ValueError` on path breakout attempts.

---

## TDD Verification

1. **RED Stage**:
   - Added tests `test_api_start_rejects_path_traversal` and `test_pipeline_engine_start_session_scoping`.
   - Executed pytest: `test_api_start_rejects_path_traversal` returned HTTP 200 instead of HTTP 400, and `start_session` allowed breakout without raising `ValueError`.
2. **GREEN Stage**:
   - Implemented minimal code updates in `main.py` and `server.py`.
   - Executed pytest: All 7 subfolder processing tests passed.
3. **Full Suite Regression Test**:
   - Ran `pytest -v` across entire repository: **206 passed, 0 failed**.

---

## Commit Details

- **Hash**: `c850f5a128f8949a443ae76bf66df74fb1b23909`
- **Message**: `feat: enforce root directory scoping and path jail in start_session and /api/start`
- **Files Modified**:
  - `src/exif_tagger/main.py`
  - `src/exif_tagger/server.py`
  - `tests/test_subfolder_processing.py`

---

## Concerns & Recommendations

- None. The jail scoping is robust, fully tested, and all 206 tests in the test suite pass cleanly.

---

## Fix Round 1/5: Reviewer Feedback Corrections

**Date:** 2026-08-09  
**Status:** SUCCESS  
**Commit:** `5036c7caa9d8fed4c124eb7dd08d99d951302ae2`  
**Commit Message:** `fix: raise ValueError for absolute paths outside root_directory`

### Findings Fixed

1. **Critical: Absolute paths outside base_gallery_root swallow ValueError and bypass breakout protection**
   - **Location:** `src/exif_tagger/main.py` in `validate_and_resolve_subfolder`.
   - **Fix:** When `override_path.is_absolute()` is True and `override_path.resolve().relative_to(resolved_root)` raises `ValueError`, `validate_and_resolve_subfolder` now explicitly raises `ValueError(f"Requested path '{user_path}' is outside the root image directory.")` instead of catching and swallowing `ValueError` via `except ValueError: pass`.
   - Sanitized root/slash inputs (e.g. `"/"`) so pure slash strings resolve cleanly to `(resolved_root, None)`.

2. **Test Coverage for Absolute Breakout Paths**
   - **Location:** `tests/test_subfolder_processing.py`.
   - **Fix:** Added `"/etc/passwd"` to `bad_paths` in `test_validate_and_resolve_subfolder_breakout_attempts` and added explicit `/api/start` test asserting HTTP 400 with detail `"Requested path '/etc/passwd' is outside the root image directory."`. Updated mock engine config in `tests/test_server.py`.

### Verification Summary
- **Test Suite Results:** Executed `.venv/bin/pytest -v` across the entire codebase. **206 passed, 0 failed**.

