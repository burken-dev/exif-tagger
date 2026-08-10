# Technical Design: Aborting Previous Gallery Calls (Frontend & Backend)

**Date**: 2026-08-10  
**Status**: Approved  

---

## 1. Overview & Context

When navigating the Gallery tab in the EXIF Tagger application, switching folders or changing tag/search filters triggers an HTTP GET request to `/api/gallery/images`. Currently:
1. **Frontend**: In-flight `fetch` requests are not cancelled. If a previous call (e.g. root gallery scan) takes longer than a subsequent call (e.g. subfolder scan), the older request completes last and overwrites the active gallery state.
2. **Backend**: When the client navigates away or switches folders, the server continues scanning directory trees and querying SQLite for the abandoned request, wasting CPU and disk I/O.

This specification details the implementation of request cancellation across both the React UI (`useGallery.ts`), the legacy web app JS (`app.js`), and the Python backend (`server.py`, `db.py`, `image_scanner.py`).

---

## 2. Architecture & Data Flow

```
[User Selects Subfolder / Changes Filter]
       │
       ├──> 1. Frontend (useGallery.ts):
       │      • Calls .abort() on active AbortController instance
       │      • Instantiates a new AbortController
       │      • Initiates fetch('/api/gallery/images?...', { signal })
       │      • Suppresses AbortError on cancelled calls
       │
       └──> 2. Backend (FastAPI / Starlette):
              • Server detects disconnect via request.is_disconnected()
              • Sets cancelled_event thread flag
              • scan_images() checks flag during directory walking
              • get_gallery_images() checks flag during SQLite query processing
              • Early-exits execution loop, releasing CPU and I/O resources
```

---

## 3. Detailed Component Specifications

### 3.1 Frontend Implementation (`webui/src/hooks/useGallery.ts`)
- **Controller Refs**:
  - `fetchImagesAbortControllerRef`: `useRef<AbortController | null>(null)`
  - `fetchFoldersAbortControllerRef`: `useRef<AbortController | null>(null)`
- **Request Cancellation**:
  - In `fetchGalleryImages()`:
    ```typescript
    if (fetchImagesAbortControllerRef.current) {
      fetchImagesAbortControllerRef.current.abort();
    }
    const controller = new AbortController();
    fetchImagesAbortControllerRef.current = controller;
    ```
  - Pass `{ signal: controller.signal }` to `fetch(url, { signal: controller.signal })`.
- **Error Handling**:
  - In `catch (err: any)`:
    ```typescript
    if (err.name === 'AbortError' || (err instanceof DOMException && err.name === 'AbortError')) {
      return; // Silently ignore aborted requests
    }
    ```
- **Cleanup**:
  - On component unmount in `useEffect`, call `.abort()` on any active controller ref.

### 3.2 Legacy Web UI (`webui/js/app.js`)
- Maintain a module-level `galleryFetchAbortController`.
- Before making new `fetch` requests to `/api/gallery/images` or `/api/gallery/folders`, abort the previous controller and pass the new signal.

### 3.3 Backend Implementation (`src/exif_tagger/`)

#### 3.3.1 `image_scanner.py` (`scan_images`)
- Add parameter `is_cancelled: Callable[[], bool] | None = None` to `scan_images()`.
- Check `is_cancelled()` inside the directory iteration loop (`for dirpath, _dirnames, filenames in sorted(root.walk()):`).
- If `is_cancelled()` returns `True`, immediately break and return `[]`.

#### 3.3.2 `db.py` (`get_gallery_images`)
- Add parameter `is_cancelled: Callable[[], bool] | None = None` to `get_gallery_images()`.
- Forward `is_cancelled` to `scan_images()`.
- Perform checks for `is_cancelled()` before batch loading DB records and processing tag mapping chunks.

#### 3.3.3 `server.py` (`api_get_gallery_images`)
- Update route handler signature to `async def api_get_gallery_images(request: Request, ...)`:
  ```python
  @app.get("/api/gallery/images")
  async def api_get_gallery_images(
      request: Request,
      offset: int = 0,
      limit: int = 50,
      tags: str | None = None,
      search: str | None = None,
      folder: str | None = None,
  ):
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
      finally:
          cancelled_event.set()
          monitor_task.cancel()
  ```

---

## 4. Verification & Testing Plan

1. **Unit Testing**:
   - `tests/test_image_scanner.py`: Test `scan_images()` with a mock `is_cancelled` callback returning `True` mid-scan.
   - `tests/test_db.py`: Test `get_gallery_images()` with `is_cancelled` returning `True`.
2. **Backend API Testing**:
   - `tests/test_server.py`: Verify `/api/gallery/images` behaves normally for non-cancelled requests.
3. **Frontend E2E & Web UI Testing**:
   - Verify selecting root folder followed immediately by subfolder selection results in displaying only the subfolder contents without UI flicker or state overwrite.
