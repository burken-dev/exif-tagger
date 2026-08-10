# Gallery Request Aborting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Abort in-flight gallery image loading calls when switching folders/filters on the frontend, and immediately cancel background directory scanning / DB queries on the server when a client disconnects.

**Architecture:** Frontend uses React `useRef<AbortController>` in `useGallery.ts` (and `app.js`) to abort prior HTTP fetches before issuing new ones, while catching and suppressing `AbortError`. The FastAPI server `/api/gallery/images` endpoint uses an `async def` handler with a background disconnect monitoring task that sets a `cancelled_event` flag, which `get_gallery_images` and `scan_images` check during directory walking and SQLite query chunking to stop early.

**Tech Stack:** Python 3.10+, FastAPI / Starlette, SQLite3, TypeScript / React 18, Vite.

## Global Constraints

- Preserve all existing public signatures and parameter defaults where possible.
- Do not introduce breaking changes to CLI tools or non-web calls.
- Suppress `AbortError` / `DOMException` on the frontend so UI loading state and errors remain clean.

---

### Task 1: Backend `image_scanner.py` Cancellation Support

**Files:**
- Modify: `src/exif_tagger/image_scanner.py:31-88`
- Test: `tests/test_image_scanner.py`

**Interfaces:**
- Consumes: `Callable[[], bool]` for `is_cancelled` check callback.
- Produces: `scan_images(root_directory, exclude_patterns=None, is_cancelled=None)`

- [ ] **Step 1: Write the failing unit test**

Create or update `tests/test_image_scanner.py`:
```python
import pytest
from pathlib import Path
from exif_tagger.image_scanner import scan_images

def test_scan_images_cancellation(tmp_path: Path):
    # Create sample nested directories and files
    dir1 = tmp_path / "sub1"
    dir1.mkdir()
    (dir1 / "test1.jpg").write_text("dummy")
    dir2 = tmp_path / "sub2"
    dir2.mkdir()
    (dir2 / "test2.jpg").write_text("dummy")

    calls = 0
    def is_cancelled() -> bool:
        nonlocal calls
        calls += 1
        return calls > 1  # Cancel after 1st check

    results = scan_images(tmp_path, is_cancelled=is_cancelled)
    assert len(results) < 2
```

- [ ] **Step 2: Run test to verify failure**

Run: `pytest tests/test_image_scanner.py::test_scan_images_cancellation -v`
Expected: FAIL with `unexpected keyword argument 'is_cancelled'`

- [ ] **Step 3: Implement cancellation check in `scan_images`**

Update `src/exif_tagger/image_scanner.py`:
```python
from typing import Callable

def scan_images(
    root_directory: str | Path,
    exclude_patterns: list[str] | None = None,
    is_cancelled: Callable[[], bool] | None = None,
) -> list[Path]:
    root = Path(root_directory).resolve()
    if not root.exists():
        raise FileNotFoundError(f"Directory does not exist: {root}")
    if not root.is_dir():
        raise NotADirectoryError(f"Not a directory: {root}")

    compilers = build_exclude_compilers(exclude_patterns or [])
    image_paths: list[Path] = []

    for dirpath, _dirnames, filenames in sorted(root.walk()):
        if is_cancelled and is_cancelled():
            logger.debug("scan_images aborted due to cancellation check")
            return []

        current_dir = Path(dirpath)
        try:
            rel_path = current_dir.relative_to(root).as_posix()
        except ValueError:
            rel_path = ""

        for filename in sorted(filenames):
            file_path = current_dir / filename
            if not _is_image_path(file_path):
                continue

            full_rel = (file_path.relative_to(root)).as_posix() if file_path.is_file() else ""

            excluded = False
            for compiler in compilers:
                if compiler.search(full_rel):
                    logger.debug("Excluded %s (matched pattern '%s')", file_path, compiler.pattern)
                    excluded = True
                    break

            if not excluded:
                image_paths.append(file_path)

    image_paths.sort()
    logger.info("Found %d images in %s", len(image_paths), root)
    return image_paths
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_image_scanner.py::test_scan_images_cancellation -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/exif_tagger/image_scanner.py tests/test_image_scanner.py
git commit -m "feat(backend): add cancellation check support to scan_images"
```

---

### Task 2: Backend `db.py` `get_gallery_images` Cancellation Support

**Files:**
- Modify: `src/exif_tagger/db.py:259-400`
- Test: `tests/test_db.py`

**Interfaces:**
- Consumes: `is_cancelled: Callable[[], bool] | None`
- Produces: `get_gallery_images(..., is_cancelled=None)`

- [ ] **Step 1: Write the failing unit test**

Create or update `tests/test_db.py`:
```python
def test_get_gallery_images_cancellation(tmp_path: Path):
    from exif_tagger.db import get_gallery_images
    db_path = tmp_path / "test.db"
    (tmp_path / "img1.jpg").write_text("dummy")
    
    # Pass is_cancelled returning True immediately
    images, total = get_gallery_images(db_path=db_path, root_directory=tmp_path, is_cancelled=lambda: True)
    assert images == []
    assert total == 0
```

- [ ] **Step 2: Run test to verify failure**

Run: `pytest tests/test_db.py::test_get_gallery_images_cancellation -v`
Expected: FAIL with `unexpected keyword argument 'is_cancelled'`

- [ ] **Step 3: Implement cancellation support in `get_gallery_images`**

Update `src/exif_tagger/db.py` `get_gallery_images`:
```python
def get_gallery_images(
    db_path: str | Path | None = None,
    offset: int = 0,
    limit: int = 50,
    tags: list[str] | None = None,
    search: str | None = None,
    folder: str | None = None,
    root_directory: str | Path | None = None,
    is_cancelled: Callable[[], bool] | None = None,
) -> tuple[list[dict[str, Any]], int]:
    if is_cancelled and is_cancelled():
        return [], 0
        
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        clean_tags = [t.strip().lower() for t in (tags or []) if t.strip()]
        ...
        scanned_paths = scan_images(target_path, exclude_patterns=exclude_patterns, is_cancelled=is_cancelled)
        if is_cancelled and is_cancelled():
            return [], 0
        ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_db.py::test_get_gallery_images_cancellation -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/exif_tagger/db.py tests/test_db.py
git commit -m "feat(backend): add cancellation check to get_gallery_images"
```

---

### Task 3: Backend `server.py` Async Route & Disconnect Monitoring

**Files:**
- Modify: `src/exif_tagger/server.py:560-588`
- Test: `tests/test_server.py`

**Interfaces:**
- Consumes: `starlette.requests.Request`, `starlette.concurrency.run_in_threadpool`
- Produces: `async def api_get_gallery_images(request: Request, ...)`

- [ ] **Step 1: Write unit / integration test for server endpoint**

Update `tests/test_server.py`:
```python
def test_api_get_gallery_images_endpoint(client):
    response = client.get("/api/gallery/images")
    assert response.status_code == 200
    data = response.json()
    assert "images" in data
    assert "total" in data
```

- [ ] **Step 2: Run test to verify current state**

Run: `pytest tests/test_server.py::test_api_get_gallery_images_endpoint -v`
Expected: PASS

- [ ] **Step 3: Refactor `api_get_gallery_images` in `server.py`**

Update `src/exif_tagger/server.py`:
```python
import asyncio
from fastapi import Request
from starlette.concurrency import run_in_threadpool

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
    cancelled_event = threading.Event()

    async def monitor_disconnect():
        while not cancelled_event.is_set():
            if await request.is_disconnected():
                cancelled_event.set()
                break
            await asyncio.sleep(0.1)

    monitor_task = asyncio.create_task(monitor_disconnect())
    try:
        config = load_config(CONFIG_PATH)
        tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None
        images, total = await run_in_threadpool(
            get_gallery_images,
            offset=offset,
            limit=limit,
            tags=tag_list,
            search=search,
            folder=folder,
            root_directory=config.root_directory,
            is_cancelled=cancelled_event.is_set,
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
        monitor_task.cancel()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_server.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/exif_tagger/server.py tests/test_server.py
git commit -m "feat(server): update api_get_gallery_images to async with disconnect monitoring"
```

---

### Task 4: Frontend `useGallery.ts` AbortController Integration

**Files:**
- Modify: `webui/src/hooks/useGallery.ts:140-190`

**Interfaces:**
- Consumes: Browser `AbortController` API
- Produces: Clean, race-condition-free `fetchGalleryImages` and `fetchFolders`

- [ ] **Step 1: Add AbortController refs to `useGallery.ts`**

Add refs near top of `useGallery`:
```typescript
const fetchImagesAbortControllerRef = useRef<AbortController | null>(null);
const fetchFoldersAbortControllerRef = useRef<AbortController | null>(null);
```

- [ ] **Step 2: Update `fetchGalleryImages` with cancellation & error suppression**

```typescript
  // Fetch Images
  const fetchGalleryImages = useCallback(async () => {
    if (fetchImagesAbortControllerRef.current) {
      fetchImagesAbortControllerRef.current.abort();
    }
    const controller = new AbortController();
    fetchImagesAbortControllerRef.current = controller;

    setLoading(true);
    setError(null);
    try {
      const page = currentPageRef.current;
      const size = pageSizeRef.current;
      const tags = selectedTagsRef.current;
      const query = searchQueryRef.current;
      const folder = currentFolderRef.current;

      const offset = (page - 1) * size;
      const tagQuery = Array.from(tags).join(',');
      const trimmedSearch = query.trim();

      let url = `/api/gallery/images?offset=${offset}&limit=${size}`;
      if (tagQuery) url += `&tags=${encodeURIComponent(tagQuery)}`;
      if (trimmedSearch) url += `&search=${encodeURIComponent(trimmedSearch)}`;
      if (folder) url += `&folder=${encodeURIComponent(folder)}`;

      const resp = await fetch(url, { signal: controller.signal });
      if (!resp.ok) throw new Error('Failed to fetch gallery images');
      const data = await resp.json();

      setImages(data.images || []);
      setTotalImages(data.total || 0);
    } catch (err: any) {
      if (err.name === 'AbortError' || (err instanceof DOMException && err.name === 'AbortError')) {
        // Silently ignore cancelled fetches
        return;
      }
      setError(err.message || 'Error loading images');
      setImages([]);
      setTotalImages(0);
    } finally {
      if (fetchImagesAbortControllerRef.current === controller) {
        setLoading(false);
      }
    }
  }, []);
```

- [ ] **Step 3: Update `fetchFolders` with cancellation**

```typescript
  // Fetch Folders for modal / breadcrumbs navigation
  const fetchFolders = useCallback(async (path = '') => {
    if (fetchFoldersAbortControllerRef.current) {
      fetchFoldersAbortControllerRef.current.abort();
    }
    const controller = new AbortController();
    fetchFoldersAbortControllerRef.current = controller;

    setModalFolder(path);
    try {
      const resp = await fetch(`/api/gallery/folders?path=${encodeURIComponent(path)}`, {
        signal: controller.signal,
      });
      if (!resp.ok) throw new Error('Failed to fetch folders');
      const data: FoldersResponse = await resp.json();
      setFolders(data.folders || []);
      setFolderBreadcrumbs(data.breadcrumbs || []);
    } catch (err: any) {
      if (err.name === 'AbortError' || (err instanceof DOMException && err.name === 'AbortError')) {
        return;
      }
      console.error('Failed to load modal folders:', err);
      setFolders([]);
      setFolderBreadcrumbs([]);
    }
  }, []);
```

- [ ] **Step 4: Add unmount cleanup effect**

```typescript
  useEffect(() => {
    return () => {
      if (fetchImagesAbortControllerRef.current) {
        fetchImagesAbortControllerRef.current.abort();
      }
      if (fetchFoldersAbortControllerRef.current) {
        fetchFoldersAbortControllerRef.current.abort();
      }
    };
  }, []);
```

- [ ] **Step 5: Run web UI build to verify TypeScript compilation**

Run: `cd webui && npm run build`
Expected: Build succeeds with 0 errors.

- [ ] **Step 6: Commit**

```bash
git add webui/src/hooks/useGallery.ts
git commit -m "feat(frontend): abort previous gallery fetch calls using AbortController"
```

---

### Task 5: Legacy `webui/js/app.js` AbortController Integration

**Files:**
- Modify: `webui/js/app.js:290-330`

- [ ] **Step 1: Add global `galleryFetchAbortController` in `app.js`**

Declare variable at scope level:
```javascript
let galleryFetchAbortController = null;
```

- [ ] **Step 2: Abort prior fetch before new request in `loadGalleryImages`**

```javascript
if (galleryFetchAbortController) {
    galleryFetchAbortController.abort();
}
galleryFetchAbortController = new AbortController();

const resp = await fetch(url, { signal: galleryFetchAbortController.signal });
```
Catch `AbortError` and suppress.

- [ ] **Step 3: Commit**

```bash
git add webui/js/app.js
git commit -m "feat(legacy-ui): add AbortController to app.js gallery fetches"
```

---

### Task 6: End-to-End Verification & Test Suite Execution

**Files:**
- All changed files and tests.

- [ ] **Step 1: Run complete backend test suite**

Run: `pytest -v`
Expected: All tests pass.

- [ ] **Step 2: Run frontend build verification**

Run: `cd webui && npm run build`
Expected: Success.

- [ ] **Step 3: Final Commit**

```bash
git commit --allow-empty -m "chore: completed gallery request aborting implementation"
```
