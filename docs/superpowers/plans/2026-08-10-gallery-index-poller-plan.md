# Gallery Index Poller Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Serve gallery reads from SQLite instead of re-scanning the filesystem on every request, and keep the `images` index in sync with the filesystem via a background poller that reconciles only changed directories.

**Architecture:** A `reconcile_gallery_index` walker in `db.py` mirrors the filesystem's image listing into the `images` table, pruning DB work for directories whose mtime is unchanged since the last poll. `get_gallery_images` is rewritten to pure SQL. A `BackgroundScheduler` interval job in `server.py` runs the walker every N seconds; a synchronous walk on startup guarantees the index exists before reads. EXIF/tag/vision state is decoupled from discovery via a new `exif_mtime` column so the poller's `last_modified` writes can never suppress EXIF extraction.

**Tech Stack:** Python 3.12, SQLite (WAL), APScheduler (already a dependency), FastAPI.

## Global Constraints

- No new runtime dependencies (apscheduler, sqlite3, stdlib only).
- Python `>=3.12`; ruff with `line-length = 120` and the `select`/`ignore` rules in `pyproject.toml`.
- Tests run with `uv run pytest`; test path `tests/`.
- The poller (discovery owner) must never write to `image_tags`, `tag_evaluations`, `user_suppressions`, or `tag_definitions`.
- The poller must never read EXIF (`get_existing_xptags`) or stat image file contents beyond `st_mtime`.
- mtime tolerance constant `_MTIME_EPS = 0.001` (same convention as the existing `> 0.001` check in `db.py:205`).
- All poller + sync DB writes are serialized by the existing `_sync_lock` in `server.py`.

## File Structure

- `src/exif_tagger/db.py` — schema (`dir_mtimes` table, `exif_mtime` column), `reconcile_gallery_index`, EXIF-decoupled `sync_gallery_index`/`update_image_in_db_from_file`, exif_mtime writes in tag paths, DB-only `get_gallery_images`; removal of `_gallery_view_cache`/`_build_gallery_view`.
- `src/exif_tagger/models/schema.py` — `GalleryIndexConfig` + `Config.gallery_index`.
- `src/exif_tagger/config.py` — env var mappings for gallery index settings.
- `src/exif_tagger/server.py` — poller job registration, startup reconcile, `_run_gallery_poll`.
- `config.yaml.example` — `gallery_index:` block.
- `tests/test_gallery_index_poller.py` — new walker/read-path tests.
- Updated: `tests/test_gallery_db.py`, `tests/test_server.py`, `tests/test_config.py`, `tests/test_db_state.py`.

---

## Task 1: Schema and config plumbing

**Files:**
- Modify: `src/exif_tagger/db.py:64-146` (`init_db`)
- Modify: `src/exif_tagger/models/schema.py:86-142` (Config)
- Modify: `src/exif_tagger/config.py:24-36` (ENV_MAPPING)
- Modify: `config.yaml.example`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - `images` table gains column `exif_mtime REAL` (nullable).
  - New table `dir_mtimes(dir_path TEXT PRIMARY KEY, mtime REAL NOT NULL, scanned_at TEXT NOT NULL)`.
  - `Config.gallery_index` of type `GalleryIndexConfig`, with `.enabled: bool = True` and `.poll_interval_seconds: int = 10` (ge=0).
  - Env overrides `EXIFTAGGER_GALLERY_INDEX_ENABLED`, `EXIFTAGGER_GALLERY_INDEX_POLL_INTERVAL_SECONDS`.

- [ ] **Step 1: Write the failing tests** (in `tests/test_config.py`, inside `TestConfig`):

```python
def test_gallery_index_defaults(self):
    from exif_tagger.models.schema import GalleryIndexConfig

    cfg = GalleryIndexConfig()
    assert cfg.enabled is True
    assert cfg.poll_interval_seconds == 10

def test_gallery_index_config_from_yaml(self, tmp_path):
    config_data = {
        "root_directory": str(tmp_path),
        "model": {"base_url": "https://api.test.com/v1", "model_name": "test-model"},
        "gallery_index": {"enabled": False, "poll_interval_seconds": 30},
    }
    config_file = tmp_path / "config.yaml"
    with open(config_file, "w") as fh:
        yaml.dump(config_data, fh)

    config = load_config(str(config_file))
    assert config.gallery_index.enabled is False
    assert config.gallery_index.poll_interval_seconds == 30

def test_gallery_index_env_override(self, tmp_path, monkeypatch):
    config_data = {"root_directory": str(tmp_path),
                   "model": {"base_url": "https://api.test.com/v1", "model_name": "test-model"}}
    config_file = tmp_path / "config.yaml"
    with open(config_file, "w") as fh:
        yaml.dump(config_data, fh)

    monkeypatch.setenv("EXIFTAGGER_GALLERY_INDEX_POLL_INTERVAL_SECONDS", "45")
    config = load_config(str(config_file))
    assert config.gallery_index.poll_interval_seconds == 45
```

Also add a schema test in `tests/test_db.py`-style (extend `tests/test_gallery_db.py::TestGalleryDatabase`):

```python
def test_init_db_creates_dir_mtimes_and_exif_mtime(self, test_db_path):
    from exif_tagger.db import get_connection, init_db

    init_db(test_db_path)
    conn = get_connection(test_db_path)
    try:
        tables = {r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        assert "dir_mtimes" in tables
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(images)")}
        assert "exif_mtime" in cols
    finally:
        conn.close()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_config.py -k gallery_index tests/test_gallery_db.py::TestGalleryDatabase::test_init_db_creates_dir_mtimes_and_exif_mtime -v`
Expected: FAIL — `GalleryIndexConfig` import error and `dir_mtimes`/`exif_mtime` missing.

- [ ] **Step 3: Implement the schema changes**

In `src/exif_tagger/db.py:init_db`, after the `images` table creation, add the column migration (before the existing `image_tags` column migration at line 93):

```python
            images_cols = {row["name"] for row in conn.execute("PRAGMA table_info(images)").fetchall()}
            if "exif_mtime" not in images_cols:
                conn.execute("ALTER TABLE images ADD COLUMN exif_mtime REAL;")
```

And after the `user_suppressions` table creation (after line 135), add:

```python
            conn.execute("""
                CREATE TABLE IF NOT EXISTS dir_mtimes (
                    dir_path TEXT PRIMARY KEY,
                    mtime REAL NOT NULL,
                    scanned_at TEXT NOT NULL
                )
            """)
```

- [ ] **Step 4: Implement the config model**

In `src/exif_tagger/models/schema.py`, above `class Config`, add:

```python
class GalleryIndexConfig(BaseModel):
    """Settings for the background gallery index poller."""

    enabled: bool = Field(default=True)
    poll_interval_seconds: int = Field(default=10, ge=0, description="0 disables the poller")
```

In `class Config`, add the field:

```python
    gallery_index: GalleryIndexConfig = Field(default_factory=GalleryIndexConfig)
```

In `src/exif_tagger/config.py:ENV_MAPPING`, add:

```python
    "EXIFTAGGER_GALLERY_INDEX_ENABLED": ("gallery_index", "enabled"),
    "EXIFTAGGER_GALLERY_INDEX_POLL_INTERVAL_SECONDS": ("gallery_index", "poll_interval_seconds"),
```

In `config.yaml.example`, append before `exclude_patterns`:

```yaml
# Background gallery index poller — keeps the SQLite gallery index in sync with the
# filesystem without scanning the whole library on every request.
gallery_index:
  enabled: true
  poll_interval_seconds: 10   # 0 disables the poller
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_config.py -k gallery_index tests/test_gallery_db.py::TestGalleryDatabase::test_init_db_creates_dir_mtimes_and_exif_mtime -v`
Expected: PASS.

- [ ] **Step 6: Run the broader suite for regressions**

Run: `uv run pytest tests/test_config.py tests/test_gallery_db.py -q`
Expected: PASS (no existing test touches the new table/column).

- [ ] **Step 7: Commit**

```bash
git add src/exif_tagger/db.py src/exif_tagger/models/schema.py src/exif_tagger/config.py config.yaml.example tests/test_config.py tests/test_gallery_db.py
git commit -m "feat(db): add dir_mtimes table and exif_mtime column with gallery_index config"
```

---

## Task 2: The reconcile walker

**Files:**
- Modify: `src/exif_tagger/db.py` (imports + new `reconcile_gallery_index` + `_MTIME_EPS`)
- Create: `tests/test_gallery_index_poller.py`

**Interfaces:**
- Consumes: `init_db`, `get_connection`, `build_exclude_compilers`, `_is_image_path`.
- Produces:
  - `reconcile_gallery_index(root_directory: str | Path, db_path: str | Path | None = None, exclude_patterns: list[str] | None = None, full: bool = False) -> dict[str, int]`
  - Returns `{"total": int, "added": int, "removed": int, "updated": int}`.
  - `total` = number of rows in `images` after the reconcile.

> **Pruning correctness note (differs from the spec pseudocode):** a file added
> inside a subfolder changes only that subfolder's mtime — NOT its parent's. So
> the walker cannot "skip descending" into unchanged directories or it would miss
> deep additions/deletions. Instead it walks (readdirs) every directory but only
> performs DB reconciliation for directories whose mtime differs from the stored
> baseline. "Pruned" therefore means *no DB writes*, not *no traversal*. This is
> what makes the steady state cheap: readdir of N dirs + mtime compare, zero DB
> work, vs the old per-request full scan.

- [ ] **Step 1: Write the failing tests** (new file `tests/test_gallery_index_poller.py`):

```python
"""Tests for reconcile_gallery_index — the discovery-layer walker."""
from __future__ import annotations

from pathlib import Path

from PIL import Image

from exif_tagger.db import get_connection, init_db, reconcile_gallery_index


def make_img(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (20, 20), color="red").save(path, format="JPEG")
    return path


def db_rows(db_path: Path) -> dict[str, dict]:
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            "SELECT id, file_path, filename, relative_path, last_modified, exif_mtime FROM images"
        ).fetchall()
        return {r["relative_path"]: dict(r) for r in rows}
    finally:
        conn.close()


def test_reconcile_adds_new_files(tmp_path):
    db = tmp_path / "g.db"
    root = tmp_path / "gallery"
    root.mkdir()
    make_img(root / "a.jpg")
    make_img(root / "sub" / "b.png")

    stats = reconcile_gallery_index(root, db_path=db)
    rows = db_rows(db)

    assert stats["total"] == 2
    assert stats["added"] == 2
    assert set(rows) == {"a.jpg", "sub/b.png"}
    assert rows["a.jpg"]["exif_mtime"] is None  # discovery never sets it


def test_reconcile_second_run_is_noop(tmp_path):
    db = tmp_path / "g.db"
    root = tmp_path / "gallery"
    root.mkdir()
    make_img(root / "a.jpg")

    reconcile_gallery_index(root, db_path=db)
    mtime_before = db_rows(db)["a.jpg"]["last_modified"]
    stats = reconcile_gallery_index(root, db_path=db)

    assert stats == {"total": 1, "added": 0, "removed": 0, "updated": 0}
    assert db_rows(db)["a.jpg"]["last_modified"] == mtime_before


def test_reconcile_detects_deletion(tmp_path):
    db = tmp_path / "g.db"
    root = tmp_path / "gallery"
    root.mkdir()
    make_img(root / "a.jpg")
    make_img(root / "b.jpg")
    reconcile_gallery_index(root, db_path=db)

    (root / "b.jpg").unlink()
    stats = reconcile_gallery_index(root, db_path=db)

    assert stats["removed"] == 1
    assert set(db_rows(db)) == {"a.jpg"}


def test_reconcile_rename_preserves_id_and_tags(tmp_path):
    from exif_tagger.db import get_connection

    db = tmp_path / "g.db"
    root = tmp_path / "gallery"
    root.mkdir()
    img = make_img(root / "old.jpg")
    reconcile_gallery_index(root, db_path=db)
    old_row = db_rows(db)["old.jpg"]

    conn = get_connection(db)
    conn.execute("INSERT INTO image_tags (image_id, tag_name, source) VALUES (?, 'manual', 'manual_exif')", (old_row["id"],))
    conn.commit()
    conn.close()

    img.rename(root / "new.jpg")
    stats = reconcile_gallery_index(root, db_path=db)
    rows = db_rows(db)

    assert stats["added"] == 0 and stats["removed"] == 0
    assert "new.jpg" in rows and "old.jpg" not in rows
    assert rows["new.jpg"]["id"] == old_row["id"]  # id preserved -> tags kept

    conn = get_connection(db)
    tags = conn.execute("SELECT tag_name FROM image_tags WHERE image_id = ?", (old_row["id"],)).fetchall()
    conn.close()
    assert [t["tag_name"] for t in tags] == ["manual"]


def test_reconcile_new_nested_dir_discovered_after_parent_prune(tmp_path):
    db = tmp_path / "g.db"
    root = tmp_path / "gallery"
    root.mkdir()
    make_img(root / "sub" / "a.jpg")
    reconcile_gallery_index(root, db_path=db)

    # Add a file inside a NEW deeper dir under the (already-indexed) sub dir.
    make_img(root / "sub" / "deeper" / "b.jpg")
    stats = reconcile_gallery_index(root, db_path=db)

    assert stats["added"] == 1
    assert "sub/deeper/b.jpg" in db_rows(db)


def test_reconcile_removed_folder_purges_subtree(tmp_path):
    db = tmp_path / "g.db"
    root = tmp_path / "gallery"
    root.mkdir()
    make_img(root / "sub" / "a.jpg")
    make_img(root / "sub" / "x" / "b.png")
    reconcile_gallery_index(root, db_path=db)

    import shutil
    shutil.rmtree(root / "sub")
    stats = reconcile_gallery_index(root, db_path=db)

    assert stats["removed"] == 2
    assert db_rows(db) == {}
    conn = get_connection(db)
    left = conn.execute("SELECT COUNT(*) AS c FROM dir_mtimes").fetchone()["c"]
    conn.close()
    assert left == 0  # baselines under the removed subtree are gone


def test_reconcile_exclude_patterns(tmp_path):
    db = tmp_path / "g.db"
    root = tmp_path / "gallery"
    root.mkdir()
    make_img(root / "keep.jpg")
    make_img(root / "skip.jpg")

    reconcile_gallery_index(root, db_path=db, exclude_patterns=["skip"])
    assert set(db_rows(db)) == {"keep.jpg"}


def test_reconcile_full_rebuild_matches_incremental(tmp_path):
    db = tmp_path / "g.db"
    root = tmp_path / "gallery"
    root.mkdir()
    make_img(root / "a.jpg")
    make_img(root / "sub" / "b.png")
    reconcile_gallery_index(root, db_path=db)
    stats_full = reconcile_gallery_index(root, db_path=db, full=True)

    assert stats_full["total"] == 2
    assert stats_full["added"] == 0 and stats_full["removed"] == 0
    assert set(db_rows(db)) == {"a.jpg", "sub/b.png"}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_gallery_index_poller.py -v`
Expected: FAIL — `reconcile_gallery_index` not defined.

- [ ] **Step 3: Implement the walker**

Add to `src/exif_tagger/db.py` imports (line 19 area):

```python
from exif_tagger.image_scanner import _is_image_path, build_exclude_compilers, scan_images
```

Add near the cache constants (line 32 area):

```python
_MTIME_EPS = 0.001
```

Add `reconcile_gallery_index` (place it right after `sync_gallery_index`, before `_build_gallery_view`). Full implementation:

```python
def reconcile_gallery_index(
    root_directory: str | Path,
    db_path: str | Path | None = None,
    exclude_patterns: list[str] | None = None,
    full: bool = False,
) -> dict[str, int]:
    """Mirror the filesystem image listing into the `images` table.

    Walks root_directory top-down. Every directory is walked (so deep additions and
    deletions are never missed), but only directories whose mtime differs from the
    stored baseline are reconciled against the DB. Only file paths and mtimes are
    written; EXIF/tag/vision state is never touched (see exif_mtime). full=True
    disables the mtime pruning and reconciles every directory (fallback path).

    Returns {"total": int, "added": int, "removed": int, "updated": int}.
    """
    from datetime import UTC, datetime

    init_db(db_path)
    root = Path(root_directory).resolve()
    conn = get_connection(db_path)
    compilers = build_exclude_compilers(exclude_patterns or [])
    stats = {"total": 0, "added": 0, "removed": 0, "updated": 0}
    now_iso = datetime.now(UTC).isoformat()

    def is_excluded(rel: str) -> bool:
        return any(c.search(rel) for c in compilers)

    def purge_subtree(d_rel: str, d_abs: str) -> None:
        conn.execute(
            "DELETE FROM images WHERE relative_path = ? OR relative_path LIKE ? || '/%'",
            (d_rel, d_rel),
        )
        conn.execute(
            "DELETE FROM dir_mtimes WHERE dir_path = ? OR dir_path LIKE ? || '/%'",
            (d_abs, d_abs),
        )

    try:
        stack: list[str] = [str(root)]
        while stack:
            d_abs = stack.pop()
            d_path = Path(d_abs)
            try:
                d_mtime = os.stat(d_abs).st_mtime
            except OSError:
                continue
            try:
                d_rel = "" if d_path == root else d_path.relative_to(root).as_posix()
            except ValueError:
                d_rel = d_path.name

            if is_excluded(d_rel):
                with conn:
                    purge_subtree(d_rel, d_abs)
                continue

            try:
                with os.scandir(d_abs) as it:
                    entries = list(it)
            except OSError:
                continue

            for e in entries:
                try:
                    if e.is_dir():
                        stack.append(e.path)
                except OSError:
                    continue

            if not full:
                baseline = conn.execute(
                    "SELECT mtime FROM dir_mtimes WHERE dir_path = ?", (d_abs,)
                ).fetchone()
                if baseline is not None and abs(baseline["mtime"] - d_mtime) <= _MTIME_EPS:
                    continue  # walked but unchanged -> no DB work

            pre = d_mtime
            with conn:
                prefix = f"{d_rel}/" if d_rel else ""
                if d_rel:
                    children = conn.execute(
                        "SELECT id, file_path, filename, relative_path, last_modified FROM images "
                        "WHERE relative_path LIKE ? AND relative_path NOT LIKE ?",
                        (prefix + "%", prefix + "%/%"),
                    ).fetchall()
                else:
                    children = conn.execute(
                        "SELECT id, file_path, filename, relative_path, last_modified FROM images "
                        "WHERE relative_path NOT LIKE '%/%'",
                    ).fetchall()

                old_by_seg = {r["relative_path"][len(prefix):] if prefix else r["relative_path"]: r for r in children}

                present_files: dict[str, os.DirEntry[str]] = {}
                present_dirs: set[str] = set()
                for e in entries:
                    try:
                        if e.is_dir():
                            present_dirs.add(e.name)
                            continue
                    except OSError:
                        pass
                    if _is_image_path(Path(e.name)):
                        rel = f"{prefix}{e.name}" if prefix else e.name
                        if not is_excluded(rel):
                            present_files[e.name] = e

                # Rename detection: a stale row whose last_modified matches a NEW file's mtime.
                mtime_to_name: dict[float, str] = {}
                for name, e in present_files.items():
                    try:
                        mtime_to_name.setdefault(e.stat().st_mtime, name)
                    except OSError:
                        continue

                for seg, r in list(old_by_seg.items()):
                    if seg in present_files or seg in present_dirs:
                        continue
                    cand_name = mtime_to_name.get(r["last_modified"]) if r["last_modified"] is not None else None
                    if cand_name is not None and cand_name in present_files:
                        cand_e = present_files.pop(cand_name)
                        try:
                            cand_mtime = cand_e.stat().st_mtime
                        except OSError:
                            cand_mtime = r["last_modified"]
                        conn.execute(
                            "UPDATE images SET file_path = ?, filename = ?, relative_path = ?, last_modified = ? WHERE id = ?",
                            (str((d_path / cand_name).resolve()), cand_name, f"{prefix}{cand_name}", cand_mtime, r["id"]),
                        )
                        stats["updated"] += 1
                        continue
                    seg_rel = f"{prefix}{seg}"
                    conn.execute(
                        "DELETE FROM images WHERE relative_path = ? OR relative_path LIKE ? || '/%'",
                        (seg_rel, seg_rel),
                    )
                    seg_abs = f"{d_abs}/{seg}"
                    conn.execute(
                        "DELETE FROM dir_mtimes WHERE dir_path = ? OR dir_path LIKE ? || '/%'",
                        (seg_abs, seg_abs),
                    )
                    stats["removed"] += 1

                for name, e in present_files.items():
                    try:
                        mtime = e.stat().st_mtime
                    except OSError:
                        continue
                    abs_str = str((d_path / name).resolve())
                    old = old_by_seg.get(name)
                    if old is None:
                        conn.execute(
                            "INSERT INTO images (file_path, filename, relative_path, last_modified, indexed_at) "
                            "VALUES (?, ?, ?, ?, ?)",
                            (abs_str, name, f"{prefix}{name}", mtime, now_iso),
                        )
                        stats["added"] += 1
                    else:
                        conn.execute(
                            "UPDATE images SET file_path = ?, filename = ?, relative_path = ?, last_modified = ? WHERE id = ?",
                            (abs_str, name, f"{prefix}{name}", mtime, old["id"]),
                        )
                        stats["updated"] += 1

            post = os.stat(d_abs).st_mtime
            if abs(pre - post) <= _MTIME_EPS:
                with conn:
                    conn.execute(
                        "INSERT OR REPLACE INTO dir_mtimes (dir_path, mtime, scanned_at) VALUES (?, ?, ?)",
                        (d_abs, post, now_iso),
                    )
            # else: a change raced the scan -> baseline left stale, next poll rescans.

        stats["total"] = conn.execute("SELECT COUNT(*) AS c FROM images").fetchone()["c"]
        return stats
    finally:
        conn.close()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_gallery_index_poller.py -v`
Expected: PASS (8 tests).

- [ ] **Step 5: Commit**

```bash
git add src/exif_tagger/db.py tests/test_gallery_index_poller.py
git commit -m "feat(db): add reconcile_gallery_index dir-mtime pruned walker"
```

---

## Task 3: Decouple EXIF extraction from `last_modified`

**Files:**
- Modify: `src/exif_tagger/db.py` — `sync_gallery_index` (lines 149-273) and `update_image_in_db_from_file` (lines 833-898)
- Test: `tests/test_gallery_db.py` (append)

**Interfaces:**
- Consumes: `exif_mtime` column from Task 1, `_MTIME_EPS` from Task 2.
- Produces: `sync_gallery_index` and `update_image_in_db_from_file` now decide "extract EXIF?" from `exif_mtime`, and set `exif_mtime = disk mtime` after extraction. Signatures unchanged.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_gallery_db.py`):

```python
def test_sync_extracts_exif_when_exif_mtime_null(tmp_path):
    """A row inserted by the poller (exif_mtime NULL) still gets EXIF tags."""
    import os

    from exif_tagger.db import get_connection, init_db, reconcile_gallery_index, sync_gallery_index

    db_path = tmp_path / "test.db"
    init_db(db_path)
    gallery_dir = tmp_path / "gallery"
    gallery_dir.mkdir()
    img = gallery_dir / "photo.jpg"
    img_ = PILImage.new("RGB", (50, 50), color="blue")
    img_.save(img)
    set_xptags(img, ["nature"])

    # Discovery-only pass: inserts the row, must NOT read EXIF.
    reconcile_gallery_index(gallery_dir, db_path=db_path)
    conn = get_connection(db_path)
    try:
        row = conn.execute("SELECT id, exif_mtime FROM images").fetchone()
        assert row["exif_mtime"] is None
        img_id = row["id"]
    finally:
        conn.close()

    sync_gallery_index(gallery_dir, db_path=db_path)

    conn = get_connection(db_path)
    try:
        tags = [r["tag_name"] for r in conn.execute(
            "SELECT tag_name FROM image_tags WHERE image_id = ?", (img_id,))]
        mtime = conn.execute("SELECT exif_mtime FROM images WHERE id = ?", (img_id,)).fetchone()["exif_mtime"]
    finally:
        conn.close()

    assert tags == ["nature"]
    assert abs(mtime - os.stat(img).st_mtime) < 0.001


def test_sync_second_run_is_skip_no_re_extract(tmp_path):
    """A second sync with unchanged mtime must not re-read EXIF or rewrite tags."""
    from exif_tagger.db import get_connection, init_db, sync_gallery_index

    db_path = tmp_path / "test.db"
    init_db(db_path)
    gallery_dir = tmp_path / "gallery"
    gallery_dir.mkdir()
    img = gallery_dir / "photo.jpg"
    PILImage.new("RGB", (50, 50), color="blue").save(img)
    set_xptags(img, ["nature"])

    stats1 = sync_gallery_index(gallery_dir, db_path=db_path)
    # Simulate a manual tag the user added in the UI only (not in EXIF).
    conn = get_connection(db_path)
    img_id = conn.execute("SELECT id FROM images").fetchone()["id"]
    conn.execute(
        "INSERT INTO image_tags (image_id, tag_name, source) VALUES (?, 'useronly', 'manual_ui')",
        (img_id,),
    )
    conn.commit()
    conn.close()

    stats2 = sync_gallery_index(gallery_dir, db_path=db_path)
    assert stats2["updated"] == 0

    conn = get_connection(db_path)
    tags = {r["tag_name"] for r in conn.execute(
        "SELECT tag_name FROM image_tags WHERE image_id = ?", (img_id,))}
    conn.close()
    assert tags == {"nature", "useronly"}  # nothing re-read, nothing wiped


def test_sync_re_extracts_after_file_modification(tmp_path):
    """Changing the file mtime triggers EXIF re-extraction."""
    import os

    from exif_tagger.db import get_connection, init_db, sync_gallery_index

    db_path = tmp_path / "test.db"
    init_db(db_path)
    gallery_dir = tmp_path / "gallery"
    gallery_dir.mkdir()
    img = gallery_dir / "photo.jpg"
    PILImage.new("RGB", (50, 50), color="blue").save(img)
    set_xptags(img, ["nature"])

    sync_gallery_index(gallery_dir, db_path=db_path)

    set_xptags(img, ["architecture"])
    new_mtime = img.stat().st_mtime + 5.0
    os.utime(img, (new_mtime, new_mtime))

    stats = sync_gallery_index(gallery_dir, db_path=db_path)
    assert stats["updated"] == 1

    conn = get_connection(db_path)
    tags = {r["tag_name"] for r in conn.execute("SELECT tag_name FROM image_tags").fetchall()}
    conn.close()
    assert tags == {"architecture"}


def test_update_image_in_db_from_file_gates_on_exif_mtime(tmp_path):
    """update_image_in_db_from_file skips EXIF rewrite when exif_mtime matches."""
    from exif_tagger.db import get_connection, init_db, update_image_in_db_from_file

    db_path = tmp_path / "test.db"
    init_db(db_path)
    img = tmp_path / "single.jpg"
    PILImage.new("RGB", (50, 50), color="yellow").save(img)
    set_xptags(img, ["tag1"])

    update_image_in_db_from_file(img, root_directory=tmp_path, db_path=db_path)
    conn = get_connection(db_path)
    img_id = conn.execute("SELECT id FROM images").fetchone()["id"]
    conn.execute(
        "INSERT INTO image_tags (image_id, tag_name, source) VALUES (?, 'useronly', 'manual_ui')",
        (img_id,),
    )
    conn.commit()
    conn.close()

    update_image_in_db_from_file(img, root_directory=tmp_path, db_path=db_path)

    conn = get_connection(db_path)
    tags = {r["tag_name"] for r in conn.execute(
        "SELECT tag_name FROM image_tags WHERE image_id = ?", (img_id,))}
    conn.close()
    assert tags == {"tag1", "useronly"}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_gallery_db.py -k "exif_mtime or second_run or re_extracts or gates_on" -v`
Expected: FAIL — `exif_mtime` is NULL/None on first-sync rows, so gating behaves like "always extract" and `stats2["updated"]` is not 0.

- [ ] **Step 3: Implement `sync_gallery_index` decoupling**

In `src/exif_tagger/db.py:sync_gallery_index`:

Change the existing-rows SELECT (line 176) to also fetch `exif_mtime`:

```python
            existing_rows = conn.execute(
                "SELECT id, file_path, relative_path, last_modified, exif_mtime FROM images"
            ).fetchall()
```

Replace the `needs_update` computation (line 205):

```python
                db_entry = existing_db_map.get(abs_path_str)
                needs_update = (
                    db_entry is None
                    or db_entry["exif_mtime"] is None
                    or abs(db_entry["exif_mtime"] - mtime) > 0.001
                )
```

Replace the INSERT (lines 217-224) to set `exif_mtime` on new rows:

```python
                        cursor = conn.execute(
                            """
                            INSERT INTO images (file_path, filename, relative_path, last_modified, exif_mtime, indexed_at)
                            VALUES (?, ?, ?, ?, ?, ?)
                            """,
                            (abs_path_str, img_path.name, rel_path, mtime, mtime, now_iso),
                        )
```

Replace the UPDATE (lines 228-235) to set `exif_mtime`:

```python
                        conn.execute(
                            """
                            UPDATE images
                            SET file_path = ?, filename = ?, relative_path = ?, last_modified = ?, exif_mtime = ?, indexed_at = ?
                            WHERE id = ?
                            """,
                            (abs_path_str, img_path.name, rel_path, mtime, mtime, now_iso, image_id),
                        )
```

- [ ] **Step 4: Implement `update_image_in_db_from_file` decoupling**

Replace the whole function body (lines 849-898) with:

```python
    abs_path_str = str(path)

    conn = get_connection(db_path)
    try:
        with conn:
            row = conn.execute(
                "SELECT id, exif_mtime FROM images WHERE file_path = ?", (abs_path_str,)
            ).fetchone()
            if row is None:
                cursor = conn.execute(
                    """
                    INSERT INTO images (file_path, filename, relative_path, last_modified, exif_mtime, indexed_at)
                    VALUES (?, ?, ?, ?, NULL, ?)
                    """,
                    (abs_path_str, path.name, rel_path, mtime, now_iso),
                )
                image_id = cursor.lastrowid
                exif_mtime = None
            else:
                image_id = row["id"]
                exif_mtime = row["exif_mtime"]
                conn.execute(
                    """
                    UPDATE images
                    SET filename = ?, relative_path = ?, last_modified = ?, indexed_at = ?
                    WHERE id = ?
                    """,
                    (path.name, rel_path, mtime, now_iso, image_id),
                )

            if exif_mtime is None or abs(exif_mtime - mtime) > _MTIME_EPS:
                # ponytail: preserves the pre-existing behavior of replacing image_tags with EXIF
                # (wipes model tags); only reached when the file actually changed on disk.
                exif_tags = get_existing_xptags(path)  # lazy: skipped when EXIF is up to date
                conn.execute("DELETE FROM image_tags WHERE image_id = ?", (image_id,))
                for t in exif_tags:
                    clean_tag = t.strip().lower()
                    if clean_tag:
                        conn.execute(
                            "INSERT OR IGNORE INTO image_tags (image_id, tag_name) VALUES (?, ?)",
                            (image_id, clean_tag),
                        )
                conn.execute("UPDATE images SET exif_mtime = ? WHERE id = ?", (mtime, image_id))
        _invalidate_gallery_view_cache()
    finally:
        conn.close()
```

(Keep the existing `if not path.exists(): return` and mtime/rel_path computation at the top of the function. Delete the old unconditional `exif_tags = get_existing_xptags(path)` line that ran before the connection was opened — the read now happens only inside the `if` branch.)

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_gallery_db.py tests/test_db_state.py tests/test_gallery_index_poller.py -q`
Expected: PASS (all four new tests plus existing ones, including `test_sync_gallery_index_detects_manual_exif_removal`).

- [ ] **Step 6: Commit**

```bash
git add src/exif_tagger/db.py tests/test_gallery_db.py
git commit -m "fix(db): gate EXIF extraction on exif_mtime instead of last_modified"
```

---

## Task 4: Set `exif_mtime` when tags are written to EXIF

**Files:**
- Modify: `src/exif_tagger/db.py` — `update_image_tags_in_db_and_exif` (line 710) and `batch_update_tags` (line 782)
- Test: `tests/test_gallery_db.py` (append)

**Interfaces:**
- Consumes: `exif_mtime` column.
- Produces: after any UI/API EXIF write, `images.exif_mtime` is updated to the file's new mtime so the next `sync_gallery_index`/`reconcile` doesn't re-extract or clobber.

- [ ] **Step 1: Write the failing test**

```python
def test_update_image_tags_sets_exif_mtime(tmp_path):
    import os

    from exif_tagger.db import get_connection, init_db, sync_gallery_index, update_image_tags_in_db_and_exif

    db_path = tmp_path / "test.db"
    init_db(db_path)
    gallery_dir = tmp_path / "gallery"
    gallery_dir.mkdir()
    img = gallery_dir / "photo.jpg"
    PILImage.new("RGB", (50, 50), color="blue").save(img)
    set_xptags(img, [])

    sync_gallery_index(gallery_dir, db_path=db_path)
    conn = get_connection(db_path)
    img_id = conn.execute("SELECT id FROM images").fetchone()["id"]
    conn.close()

    assert update_image_tags_in_db_and_exif(img_id, ["edited"], db_path=db_path) is True

    conn = get_connection(db_path)
    row = conn.execute("SELECT last_modified, exif_mtime FROM images WHERE id = ?", (img_id,)).fetchone()
    conn.close()
    assert abs(row["exif_mtime"] - row["last_modified"]) < 0.001
    assert abs(row["last_modified"] - os.stat(img).st_mtime) < 0.001
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_gallery_db.py::test_update_image_tags_sets_exif_mtime -v`
Expected: FAIL — `exif_mtime` is None after the tag write.

- [ ] **Step 3: Implement**

In `src/exif_tagger/db.py:update_image_tags_in_db_and_exif`, change line 710:

```python
            conn.execute("UPDATE images SET last_modified = ? WHERE id = ?", (mtime, image_id))
```

to:

```python
            conn.execute("UPDATE images SET last_modified = ?, exif_mtime = ? WHERE id = ?", (mtime, mtime, image_id))
```

In `src/exif_tagger/db.py:batch_update_tags`, change line 782:

```python
                    conn.execute("UPDATE images SET last_modified = ? WHERE id = ?", (mtime, img_id))
```

to:

```python
                    conn.execute("UPDATE images SET last_modified = ?, exif_mtime = ? WHERE id = ?", (mtime, mtime, img_id))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_gallery_db.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/exif_tagger/db.py tests/test_gallery_db.py
git commit -m "fix(db): keep exif_mtime current when writing EXIF tags"
```

---

## Task 5: DB-only read path

**Files:**
- Modify: `src/exif_tagger/db.py` — rewrite `get_gallery_images` (lines 370-525); delete `_build_gallery_view` (276-367), `_gallery_view_cache`/`_gallery_view_cache_lock`/`_GALLERY_VIEW_CACHE_TTL` (26-32), `_invalidate_gallery_view_cache` (35-37) and its 4 call sites (265, 718, 792, 896).
- Modify: `tests/test_gallery_db.py` — rewrite `test_get_gallery_images_filesystem_unindexed` (175-204) and `test_get_gallery_images_untagged_folder_and_search` (207-237); append new read-path tests.
- Modify: `tests/test_server.py` — `test_gallery_sync_filtered_mode` (428-467) seeds the index.

**Interfaces:**
- Consumes: `exif_mtime`/`dir_mtimes` from Tasks 1-2, DB rows populated by reconcile/sync.
- Produces: `get_gallery_images` with the SAME signature and return shape `(results, total)` as before, but now DB-only. Every returned image has `id` non-null and `indexed: True` (the old `id=None` unindexed branch is removed). `root_directory` and `is_cancelled` params are kept for caller compatibility and ignored.

- [ ] **Step 1: Rewrite the two tests that relied on filesystem-truth reads**

Replace the body of `test_get_gallery_images_filesystem_unindexed` in `tests/test_gallery_db.py`:

```python
def test_get_gallery_images_filesystem_unindexed(tmp_path):
    """Every file on disk is discovered (with an id) once the index is reconciled."""
    from exif_tagger.db import get_gallery_images, init_db, reconcile_gallery_index

    db_path = tmp_path / "test.db"
    init_db(db_path)

    img1 = tmp_path / "a.jpg"
    img2 = tmp_path / "sub" / "b.png"
    img2.parent.mkdir(parents=True, exist_ok=True)
    img1.write_bytes(b"dummy")
    img2.write_bytes(b"dummy")

    reconcile_gallery_index(tmp_path, db_path=db_path)
    images, total = get_gallery_images(db_path=db_path, root_directory=tmp_path)
    assert total == 2
    assert all(img["id"] is not None for img in images)
    assert all(img["indexed"] is True for img in images)
    assert images[0]["filename"] == "a.jpg"
    assert images[1]["relative_path"] == "sub/b.png"
```

Replace the body of `test_get_gallery_images_untagged_folder_and_search`:

```python
def test_get_gallery_images_untagged_folder_and_search(tmp_path):
    from exif_tagger.db import get_gallery_images, init_db, reconcile_gallery_index

    db_path = tmp_path / "test.db"
    init_db(db_path)

    (tmp_path / "root.jpg").write_bytes(b"dummy")
    sub1 = tmp_path / "folder1"
    sub1.mkdir()
    (sub1 / "img1.jpg").write_bytes(b"dummy")
    (sub1 / "photo2.png").write_bytes(b"dummy")

    sub2 = tmp_path / "folder2"
    sub2.mkdir()
    (sub2 / "other.jpg").write_bytes(b"dummy")

    reconcile_gallery_index(tmp_path, db_path=db_path)

    images, total = get_gallery_images(db_path=db_path, folder="folder1", root_directory=tmp_path)
    assert total == 2
    assert [img["filename"] for img in images] == ["img1.jpg", "photo2.png"]

    images_glob, total_glob = get_gallery_images(db_path=db_path, search="*.png", root_directory=tmp_path)
    assert total_glob == 1
    assert images_glob[0]["filename"] == "photo2.png"

    images_sub, total_sub = get_gallery_images(db_path=db_path, search="img1", root_directory=tmp_path)
    assert total_sub == 1
    assert images_sub[0]["filename"] == "img1.jpg"
```

- [ ] **Step 2: Write the new failing read-path tests** (append to `tests/test_gallery_db.py`):

```python
def test_get_gallery_images_is_db_only(monkeypatch, tmp_path):
    """Reads must never touch the filesystem."""
    from exif_tagger.db import get_gallery_images, init_db, reconcile_gallery_index

    db_path = tmp_path / "test.db"
    init_db(db_path)
    root = tmp_path / "gallery"
    root.mkdir()
    (root / "a.jpg").write_bytes(b"x")
    reconcile_gallery_index(root, db_path=db_path)

    def boom(*args, **kwargs):
        raise AssertionError("filesystem must not be scanned during reads")

    monkeypatch.setattr("exif_tagger.db.scan_images", boom)
    images, total = get_gallery_images(db_path=db_path)
    assert total == 1


def test_get_gallery_images_folder_special_chars(tmp_path):
    from exif_tagger.db import get_gallery_images, init_db, reconcile_gallery_index

    db_path = tmp_path / "test.db"
    init_db(db_path)
    root = tmp_path / "gallery"
    root.mkdir()
    special = root / "50%_photos"
    special.mkdir()
    (special / "one.jpg").write_bytes(b"x")
    reconcile_gallery_index(root, db_path=db_path)

    images, total = get_gallery_images(db_path=db_path, folder="50%_photos")
    assert total == 1
    assert images[0]["filename"] == "one.jpg"


def test_get_gallery_images_tag_and_semantics(tmp_path):
    """Selecting multiple tags requires ALL of them (AND), not any."""
    from exif_tagger.db import get_gallery_images, init_db, sync_gallery_index

    db_path = tmp_path / "test.db"
    init_db(db_path)
    root = tmp_path / "gallery"
    root.mkdir()
    for name, tags in [("a.jpg", ["x", "y"]), ("b.jpg", ["x"]), ("c.jpg", ["y"])]:
        p = root / name
        PILImage.new("RGB", (20, 20)).save(p)
        set_xptags(p, tags)
    sync_gallery_index(root, db_path=db_path)

    images, total = get_gallery_images(db_path=db_path, tags=["x", "y"])
    assert total == 1
    assert images[0]["filename"] == "a.jpg"


def test_get_gallery_images_search_unicode_case(tmp_path):
    from exif_tagger.db import get_gallery_images, init_db, reconcile_gallery_index

    db_path = tmp_path / "test.db"
    init_db(db_path)
    root = tmp_path / "gallery"
    root.mkdir()
    (root / "Ångström.jpg").write_bytes(b"x")
    reconcile_gallery_index(root, db_path=db_path)

    images, total = get_gallery_images(db_path=db_path, search="ångström")
    assert total == 1
    images2, total2 = get_gallery_images(db_path=db_path, search="ÅNGSTRÖM")
    assert total2 == 1


def test_get_gallery_images_pagination(tmp_path):
    from exif_tagger.db import get_gallery_images, init_db, reconcile_gallery_index

    db_path = tmp_path / "test.db"
    init_db(db_path)
    root = tmp_path / "gallery"
    root.mkdir()
    for i in range(5):
        (root / f"img{i}.jpg").write_bytes(b"x")
    reconcile_gallery_index(root, db_path=db_path)

    page1, total = get_gallery_images(db_path=db_path, offset=0, limit=2)
    page2, _ = get_gallery_images(db_path=db_path, offset=2, limit=2)
    assert total == 5
    assert len(page1) == 2 and len(page2) == 2
    assert {img["id"] for img in page1}.isdisjoint({img["id"] for img in page2})
```

- [ ] **Step 3: Run the new tests to verify they fail**

Run: `uv run pytest tests/test_gallery_db.py -k "db_only or folder_special_chars or tag_and_semantics or search_unicode_case or pagination" -v`
Expected: FAIL — `test_get_gallery_images_is_db_only` raises the monkeypatched AssertionError; others may pass against the old impl (they were written to be semantics-compatible).

- [ ] **Step 4: Implement the DB-only read path**

Replace the whole `get_gallery_images` body (lines 370-525) with:

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
    """Retrieve paginated images from the DB index with tag/search/folder filters.

    DB-only: the filesystem is never touched. The `images` table is kept in sync
    with disk by reconcile_gallery_index (poller) and sync_gallery_index (manual).
    `root_directory` and `is_cancelled` are kept for caller compatibility and ignored.
    """
    import fnmatch

    init_db(db_path)
    conn = get_connection(db_path)
    try:
        clean_tags = [t.strip().lower() for t in (tags or []) if t.strip()]
        clean_folder = (folder or "").strip().strip("/") if folder else ""
        search_query = (search or "").strip()
        search_pattern = search_query.lower() if search_query else None
        has_glob = bool(search_query) and any(c in search_query for c in ("*", "?", "["))

        clauses: list[str] = []
        params: list[Any] = []

        if clean_folder:
            escaped = clean_folder.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            clauses.append("(i.relative_path = ? OR i.relative_path LIKE ? ESCAPE '\\')")
            params += [clean_folder, escaped + "/%"]
        if clean_tags:
            placeholders = ",".join("?" for _ in clean_tags)
            clauses.append(
                f"i.id IN (SELECT image_id FROM image_tags WHERE tag_name IN ({placeholders}) "
                "GROUP BY image_id HAVING COUNT(DISTINCT tag_name) = ?)"
            )
            params += clean_tags + [len(clean_tags)]

        where = f"WHERE {' AND '.join(clauses)} " if clauses else ""

        rows = conn.execute(
            f"SELECT i.id, i.file_path, i.filename, i.relative_path, i.last_modified "
            f"FROM images i {where}",
            params,
        ).fetchall()

        # Search post-filter in Python: preserves Unicode-aware lower() and fnmatch semantics.
        if search_pattern:
            kept = []
            for r in rows:
                fname_l = r["filename"].lower()
                rel_l = r["relative_path"].lower()
                if has_glob:
                    if fnmatch.fnmatch(fname_l, search_pattern) or fnmatch.fnmatch(rel_l, search_pattern):
                        kept.append(r)
                else:
                    if search_pattern in fname_l or search_pattern in rel_l:
                        kept.append(r)
            rows = kept

        rows.sort(key=lambda r: (r["relative_path"].lower(), r["filename"].lower()))

        total = len(rows)
        page = rows[offset : offset + limit]

        tags_map: dict[int, list[str]] = {}
        ids = [r["id"] for r in page]
        if ids:
            for i in range(0, len(ids), 900):
                chunk = ids[i : i + 900]
                placeholders = ",".join("?" for _ in chunk)
                for tr in conn.execute(
                    f"SELECT image_id, tag_name FROM image_tags WHERE image_id IN ({placeholders}) ORDER BY tag_name ASC",
                    chunk,
                ):
                    tags_map.setdefault(tr["image_id"], []).append(tr["tag_name"])

        results: list[dict[str, Any]] = []
        for r in page:
            results.append(
                {
                    "id": r["id"],
                    "file_path": r["file_path"],
                    "filename": r["filename"],
                    "relative_path": r["relative_path"],
                    "last_modified": r["last_modified"],
                    "indexed": True,
                    "tags": tags_map.get(r["id"], []),
                }
            )
        return results, total
    finally:
        conn.close()
```

- [ ] **Step 5: Remove the scan pipeline and cache**

In `src/exif_tagger/db.py`:
- Delete lines 26-37 (`_gallery_view_cache`, `_gallery_view_cache_lock`, `_GALLERY_VIEW_CACHE_TTL`, `_invalidate_gallery_view_cache`).
- Delete `_build_gallery_view` (lines 276-367).
- Delete the `_invalidate_gallery_view_cache()` calls at what were lines 265 (`sync_gallery_index`), 718 (`update_image_tags_in_db_and_exif`), 792 (`batch_update_tags`), and 896 (`update_image_in_db_from_file`).

- [ ] **Step 6: Fix the filtered-sync server test** (in `tests/test_server.py::test_gallery_sync_filtered_mode`)

Filtered sync now selects candidates from the DB index, so the index must be seeded first. Right after `init_db(db_file)` (line 436), add:

```python
        from exif_tagger.db import reconcile_gallery_index
        reconcile_gallery_index(tmp_path, db_path=db_file)
```

- [ ] **Step 7: Run the suite to verify everything passes**

Run: `uv run pytest tests/test_gallery_db.py tests/test_gallery_folders_and_glob.py tests/test_gallery_api.py tests/test_db_state.py tests/test_gallery_index_poller.py tests/test_server.py -q`
Expected: PASS.

- [ ] **Step 8: Lint**

Run: `uv run ruff check src/exif_tagger/db.py tests/test_gallery_db.py tests/test_server.py`
Expected: no errors (line-length is 120; the long SQL strings are within one expression, ruff only flags the literal if it exceeds 120 — if flagged, split with adjacent string concatenation).

- [ ] **Step 9: Commit**

```bash
git add src/exif_tagger/db.py tests/test_gallery_db.py tests/test_server.py
git commit -m "feat(db): serve gallery reads from the DB index only"
```

---

## Task 6: Server integration — startup reconcile + poller job

**Files:**
- Modify: `src/exif_tagger/server.py` — import block (434-443), new `_run_gallery_poll`, `_setup_scheduler` (165-209), `lifespan` (834-857)
- Test: `tests/test_server.py` (append)

**Interfaces:**
- Consumes: `reconcile_gallery_index`, `Config.gallery_index` (Tasks 1-2).
- Produces: `_run_gallery_poll() -> None` (acquires `_sync_lock` non-blocking), scheduler job id `gallery_index_poll`, and a synchronous discovery build in `lifespan` before the EXIF sync thread starts.

- [ ] **Step 1: Write the failing test** (append to `tests/test_server.py`):

```python
def test_gallery_index_poller_registered(monkeypatch, tmp_path):
    """With the default config, the poller job is registered on startup."""
    from exif_tagger.server import _setup_scheduler, _scheduler

    cfg = tmp_path / "config.yaml"
    cfg.write_text("root_directory: %s\n" % tmp_path)

    monkeypatch.setattr("exif_tagger.server.CONFIG_PATH", str(cfg))
    _setup_scheduler()
    try:
        job = _scheduler.get_job("gallery_index_poll")
        assert job is not None
    finally:
        _scheduler.shutdown(wait=False)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_server.py::test_gallery_index_poller_registered -v`
Expected: FAIL — job `gallery_index_poll` not found.

- [ ] **Step 3: Implement the poller job**

In `src/exif_tagger/server.py`, add `reconcile_gallery_index` to the import block (lines 434-443):

```python
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
```

Add `_run_gallery_poll` right after `_run_gallery_sync` (after line 529, before the `@app.post` decorator at line 530):

```python
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
```

In `_setup_scheduler` (end of the function, after the schedule loop, before the closing of the `for` loop body / function end at line 209), add:

```python
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
```

- [ ] **Step 4: Implement the startup reconcile** in `lifespan` (lines 834-857)

Add `config = None` before the existing `try:` (so a config-load failure leaves `config` bound to `None` rather than unbound):

```python
    config = None
    try:
        config = load_config(CONFIG_PATH)
        log_level = getattr(config, "log_level", "INFO")
        log_dir = getattr(config, "log_dir", "/app/logs")
        setup_secure_logging(level=log_level, log_dir=log_dir)
    except Exception as exc:
        setup_secure_logging()
        logger.warning("Could not load config for server logging setup: %s", exc)
```

Then replace the startup block (lines 846-851):

```python
    logger.info("EXIF Tagger API starting up...")
    _setup_scheduler()
    logger.info(f"Loaded {len(_schedules)} schedules")

    # Build the discovery index synchronously so gallery reads are never empty.
    if config is not None:
        with _sync_lock:
            reconcile_gallery_index(config.root_directory, exclude_patterns=config.exclude_patterns)

    # Start background gallery index sync (EXIF/derived state)
    threading.Thread(target=_run_gallery_sync, daemon=True).start()
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_server.py -q`
Expected: PASS — including `test_gallery_sync_filtered_mode` (index seeded in Task 5) and the new poller registration test.

- [ ] **Step 6: Commit**

```bash
git add src/exif_tagger/server.py tests/test_server.py
git commit -m "feat(server): run gallery index poller and reconcile on startup"
```

---

## Task 7: Integration test and full-suite verification

**Files:**
- Modify: `tests/test_server.py` (append integration test)

- [ ] **Step 1: Write the integration test** (append to `tests/test_server.py`):

```python
def test_poll_refreshes_index_and_reads(tmp_path):
    """A reconcile round makes a newly added file visible to the gallery API."""
    from exif_tagger.db import reconcile_gallery_index
    from exif_tagger.models.schema import Config as SchemaConfig
    from exif_tagger.models.schema import ModelConfig

    gallery = tmp_path / "gallery"
    gallery.mkdir()
    (gallery / "a.jpg").write_bytes(b"\xff\xd8\xff\xe0\x00\x10JFIF\x00")

    dummy_config = SchemaConfig(
        root_directory=str(gallery),
        model=ModelConfig(base_url="http://t/v1", model_name="t"),
    )

    with (
        patch("exif_tagger.server.load_config", return_value=dummy_config),
        patch("exif_tagger.server.CONFIG_PATH", str(tmp_path / "config.yaml")),
        TestClient(server_module.app) as client,
    ):
        # Startup reconcile seeded the index.
        assert client.get("/api/gallery/images").json()["total"] == 1

        # A file added on disk after startup shows up after one reconcile round.
        (gallery / "b.jpg").write_bytes(b"\xff\xd8\xff\xe0\x00\x10JFIF\x00")
        reconcile_gallery_index(gallery, db_path=None)
        assert client.get("/api/gallery/images").json()["total"] == 2
```

- [ ] **Step 2: Run the integration test**

Run: `uv run pytest tests/test_server.py::test_poll_refreshes_index_and_reads -v`
Expected: PASS.

- [ ] **Step 3: Run the full non-e2e suite**

Run: `uv run pytest tests/ -q --ignore=tests/e2e`
Expected: PASS.

- [ ] **Step 4: Lint the whole source tree**

Run: `uv run ruff check src tests`
Expected: no errors. Fix any issues (long lines over 120 in the new SQL strings should be split with adjacent string concatenation).

- [ ] **Step 5: Manual smoke check (optional, Docker/dev)**

Start the server (`uv run python -m exif_tagger.server`), open the gallery tab, verify:
- First load populates the gallery without manual "Sync All".
- Adding an image file into the root or a subfolder appears within one poll interval without pressing Sync.
- Deleting an image removes it within one poll interval.
- Tag selection/filtering and search still work and return promptly.
- The `Sync All` / `Sync Filtered` buttons still work and populate EXIF tags.

- [ ] **Step 6: Commit**

```bash
git add tests/test_server.py
git commit -m "test(server): verify poller refresh is visible to gallery reads"
```

---

## Self-review notes (resolved)

- **Spec coverage:** dir_mtimes table + exif_mtime column (Task 1); walker add/delete/rename/remove-folder/prune/race/exclude/full-rebuild (Task 2); exif_mtime decoupling in sync paths (Tasks 3-4); DB-only reads (Task 5); startup reconcile + poller job + config (Task 6); fallback `full=True` equality test (Task 2); integration test (Task 7). Folder nav stays disk-based — no change needed. The old `id=None` unindexed branch removal is covered by the rewritten `test_get_gallery_images_filesystem_unindexed`.
- **Pruning correction:** the spec pseudocode's "skip descending into unchanged dirs" is unsafe (a deep file addition changes only its own dir's mtime). The walker instead walks every directory but does DB reconciliation only for changed ones. This is documented at the top of Task 2.
- **Known pre-existing behavior left unchanged:** `update_image_in_db_from_file` replaces `image_tags` with EXIF tags when a file's `exif_mtime` differs (marked with a `ponytail:` comment); cross-directory file moves lose tags (delete+insert) since rename detection is scoped to a single directory scan.






