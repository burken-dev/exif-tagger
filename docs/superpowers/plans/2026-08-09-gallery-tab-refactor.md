# Gallery Tab Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor the Gallery Tab so unindexed filesystem images are listed when no tag filter is selected, unindexed images are visually marked in grid and detail view, single images can be synced on demand, and index sync supports both "Sync All" and "Sync Filtered" modes.

**Architecture:** 
The query engine in `db.py` switches dynamically between a direct filesystem scan (for folder selection & search queries without tag filter, enriched with DB status) and SQLite queries (when tag filters are active). FastAPI endpoints in `server.py` support serving raw image files via relative path parameter, on-demand single image sync, and dual-mode background index sync. The React frontend updates cards, detail modal, toolbar, and hooks to expose these capabilities.

**Tech Stack:** Python 3.12, SQLite, FastAPI, Pydantic, React 18, Vite, TypeScript, TailwindCSS, Lucide Icons, pytest.

## Global Constraints
- Folder selection & search filter MUST query the filesystem directly when no tags are selected.
- Sorting order for filesystem image listing MUST be by full path name + file name (`relative_path ASC, filename ASC`).
- Unindexed images MUST be displayed in the gallery and visually marked as unprocessed/unindexed.
- Detail view MUST have a button to sync the single image and import its EXIF info into DB.
- Sync Index button MUST support two modes: "Sync All" and "Sync Filtered".

---

### Task 1: Backend Query Engine Update (`db.py` & `test_gallery_db.py`)

**Files:**
- Modify: `src/exif_tagger/db.py`
- Test: `tests/test_gallery_db.py`

**Interfaces:**
- Produces: `get_gallery_images(offset, limit, tags, search, folder, db_path, root_directory) -> tuple[list[dict], int]`
- Produces: `sync_single_image(relative_or_abs_path, db_path, root_directory) -> dict`

- [ ] **Step 1: Write tests for filesystem-first gallery image listing and single image sync**

Edit `tests/test_gallery_db.py` to add tests verifying unindexed filesystem images are returned when `tags` is empty, and single image sync works.

```python
def test_get_gallery_images_filesystem_unindexed(tmp_path):
    # Setup test directory with unindexed image files
    from exif_tagger.db import init_db, get_gallery_images, sync_single_image
    db_path = tmp_path / "test.db"
    init_db(db_path)

    # Create dummy images on disk
    img1 = tmp_path / "a.jpg"
    img2 = tmp_path / "sub" / "b.png"
    img2.parent.mkdir(parents=True, exist_ok=True)
    img1.write_bytes(b"dummy")
    img2.write_bytes(b"dummy")

    # Call get_gallery_images without tags (should list both from disk even though DB is empty)
    images, total = get_gallery_images(db_path=db_path, root_directory=tmp_path)
    assert total == 2
    assert images[0]["filename"] == "a.jpg"
    assert images[0]["indexed"] is False
    assert images[0]["id"] is None
    assert images[1]["relative_path"] == "sub/b.png"

    # Test sync_single_image
    synced = sync_single_image("a.jpg", db_path=db_path, root_directory=tmp_path)
    assert synced["indexed"] is True
    assert synced["id"] is not None

    # Query again: a.jpg should now be indexed, sub/b.png unindexed
    images, total = get_gallery_images(db_path=db_path, root_directory=tmp_path)
    assert images[0]["indexed"] is True
    assert images[1]["indexed"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_gallery_db.py::test_get_gallery_images_filesystem_unindexed -v`
Expected: FAIL (function `sync_single_image` missing or `get_gallery_images` does not return `indexed` field / filesystem images).

- [ ] **Step 3: Implement `sync_single_image` and update `get_gallery_images` in `src/exif_tagger/db.py`**

Update `get_gallery_images()` to check if `clean_tags` is empty:
- If `clean_tags` is empty:
  - Determine target scan path: `(root_path / folder)` if `folder` else `root_path`.
  - Scan filesystem images via `scan_images(target_path, exclude_patterns)`.
  - Filter by `search` pattern (glob or substring match against `filename` and `relative_path`).
  - Sort matching `Path` objects by `relative_path ASC, filename ASC`.
  - Paginate: `offset` to `offset + limit`.
  - Batch query DB `images` table by `file_path` for the page slice.
  - Return formatted list with `indexed: bool`, `id: int | None`, `tags: list[str]`.
- If `clean_tags` is not empty:
  - Query DB by `tag_name IN (clean_tags)` + folder + search as before, returning `indexed: True`.

Implement `sync_single_image(image_path, db_path=None, root_directory=None)`:
- Index/update specified file, extract EXIF XPTags, write to DB, and return image record with `indexed: True`.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_gallery_db.py -v`
Expected: PASS

- [ ] **Step 5: Commit changes**

```bash
git add src/exif_tagger/db.py tests/test_gallery_db.py
git commit -m "feat(db): update get_gallery_images to scan filesystem when untagged and add sync_single_image"
```

---

### Task 2: FastAPI Server Endpoints Update (`server.py` & `test_server.py`)

**Files:**
- Modify: `src/exif_tagger/server.py`
- Test: `tests/test_server.py`

**Interfaces:**
- Consumes: `get_gallery_images`, `sync_single_image`, `sync_gallery_index` from `db.py`
- Produces: API routes `/api/gallery/images`, `/api/gallery/image/file`, `/api/gallery/image/sync`, `/api/gallery/sync`

- [ ] **Step 1: Write test for image file serving by path, single image sync endpoint, and filtered index sync endpoint**

Add tests to `tests/test_server.py`:

```python
def test_gallery_image_file_by_path(client, tmp_path):
    # Test GET /api/gallery/image/file?path=...
    pass

def test_gallery_sync_single_image_endpoint(client, tmp_path):
    # Test POST /api/gallery/image/sync with relative_path
    pass

def test_gallery_sync_filtered_mode(client, tmp_path):
    # Test POST /api/gallery/sync with { "mode": "filtered", "folder": "sub" }
    pass
```

- [ ] **Step 2: Run test to verify failure**

Run: `.venv/bin/pytest tests/test_server.py::TestGalleryApi -v`
Expected: FAIL

- [ ] **Step 3: Update `src/exif_tagger/server.py`**

- Add `GET /api/gallery/image/file`:
  - Accepts query parameter `path: str`.
  - Resolves path against `root_directory`, verifies security boundary (path must reside inside root_directory) and file extension.
  - Returns `FileResponse(file_path)`.
- Add `POST /api/gallery/image/sync`:
  - Accepts body `{ "relative_path": str }` or `{ "file_path": str }`.
  - Calls `sync_single_image()`.
  - Returns indexed image data.
- Update `POST /api/gallery/sync`:
  - Accepts request model `GallerySyncRequest(mode="all"|"filtered", folder=None, search=None, tags=None)`.
  - Background thread runs `sync_gallery_index` in all or filtered mode.

- [ ] **Step 4: Run tests to verify pass**

Run: `.venv/bin/pytest tests/test_server.py -v`
Expected: PASS

- [ ] **Step 5: Commit changes**

```bash
git add src/exif_tagger/server.py tests/test_server.py
git commit -m "feat(server): add image file by path, single image sync, and dual-mode index sync endpoints"
```

---

### Task 3: Frontend Types & Gallery Hook Update (`types/index.ts`, `useGallery.ts`)

**Files:**
- Modify: `webui/src/types/index.ts`
- Modify: `webui/src/hooks/useGallery.ts`

**Interfaces:**
- Produces: Updated `GalleryImage` type with `id: number | null` and `indexed: boolean`.
- Produces: `syncGalleryIndex(mode, options)` and `syncSingleImage(path)` functions in `useGallery`.

- [ ] **Step 1: Update `webui/src/types/index.ts`**

Update `GalleryImage` interface:
```typescript
export interface GalleryImage {
  id: number | null;
  filename: string;
  relative_path: string;
  file_path?: string;
  tags: string[];
  indexed: boolean;
  last_modified?: number;
  created_at?: string;
  updated_at?: string;
}
```

- [ ] **Step 2: Update `webui/src/hooks/useGallery.ts`**

- Update `syncGalleryIndex`:
  - Accept parameter `mode?: 'all' | 'filtered'`.
  - Send POST payload `{ mode, folder: currentFolder, search: searchQuery, tags: Array.from(selectedTags) }`.
- Add `syncSingleImage(relativePath: string)`:
  - Send POST request to `/api/gallery/image/sync` with `{ relative_path: relativePath }`.
  - On success, refresh tag list and gallery images, returning updated image data.

- [ ] **Step 3: Verify TypeScript compilation**

Run: `cd webui && npm run build` (or `npx tsc --noEmit`)
Expected: Check for any TypeScript type errors in `useGallery.ts`.

- [ ] **Step 4: Commit changes**

```bash
git add webui/src/types/index.ts webui/src/hooks/useGallery.ts
git commit -m "feat(webui): update GalleryImage types and add syncSingleImage & dual-mode sync in useGallery hook"
```

---

### Task 4: Frontend UI Components Update (`ImageCard`, `ImageDetailModal`, `GalleryToolbar`, `GalleryTab`)

**Files:**
- Modify: `webui/src/components/gallery/ImageCard.tsx`
- Modify: `webui/src/components/gallery/ImageDetailModal.tsx`
- Modify: `webui/src/components/gallery/GalleryToolbar.tsx`
- Modify: `webui/src/components/gallery/GalleryTab.tsx`

- [ ] **Step 1: Update `ImageCard.tsx`**

- Change image element source to `/api/gallery/image/file?path=${encodeURIComponent(image.relative_path)}`.
- Render **Unindexed Badge** on thumbnail top-right if `!image.indexed`:
  ```tsx
  {!image.indexed && (
    <span className="absolute top-2 right-2 z-20 text-[10px] font-semibold bg-amber-500/90 text-amber-950 px-1.5 py-0.5 rounded shadow-sm flex items-center gap-1">
      ⚠️ Unindexed
    </span>
  )}
  ```
- Render badge in bottom section showing `Unprocessed` or `Unindexed` when `!image.indexed`.

- [ ] **Step 2: Update `ImageDetailModal.tsx`**

- Render image preview using `/api/gallery/image/file?path=${encodeURIComponent(image.relative_path)}`.
- Render an **Indexed** or **Unindexed** badge in metadata section.
- Add a **"Sync Image"** button:
  ```tsx
  <Button
    type="button"
    variant="outline"
    size="sm"
    onClick={handleSyncImage}
    disabled={isSyncingSingle}
    className="w-full text-xs h-8 gap-1.5 text-amber-400 border-amber-500/40 hover:bg-amber-500/10"
  >
    <RefreshCw className={`w-3.5 h-3.5 ${isSyncingSingle ? 'animate-spin' : ''}`} />
    <span>{isSyncingSingle ? 'Syncing...' : 'Sync Image & Extract Tags'}</span>
  </Button>
  ```
- Handle tag updates for unindexed images (auto-indexing them when saved).

- [ ] **Step 3: Update `GalleryToolbar.tsx` & `GalleryTab.tsx`**

- Update the Sync Index toolbar section to provide **Sync All** and **Sync Filtered** options (e.g. split button or dropdown menu).
- Highlight "Sync Filtered" when folder selection, search query, or tag filters are active.

- [ ] **Step 4: Build webui assets and run full test suite**

Run:
```bash
cd webui && npm run build
.venv/bin/pytest
```
Expected: Build succeeds cleanly with 0 TypeScript/Vite errors and all Python unit tests pass.

- [ ] **Step 5: Commit UI changes**

```bash
git add webui/src/components/gallery/
git commit -m "feat(webui): add unindexed visual markers, single-image sync button, and dual-mode index sync controls"
```
