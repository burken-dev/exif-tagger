"""SQLite database module for indexing and querying images and their XPTags.

Provides fast database indexing of photos in gallery root directory for web UI gallery browsing,
filtering by tags, single image tag editing, batch tag updates, and global tag removal.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from pathlib import Path
from typing import Any

from exif_tagger.exif_writer import get_existing_xptags, set_xptags
from exif_tagger.image_scanner import scan_images

logger = logging.getLogger(__name__)

_config_dir = Path(__file__).resolve().parent.parent.parent
DEFAULT_DB_PATH = _config_dir / "gallery.db"


def get_db_path(custom_path: str | Path | None = None) -> Path:
    """Resolve SQLite database path from param, env var, data dir, or default location."""
    if custom_path:
        return Path(custom_path)
    env_path = os.environ.get("EXIFTAGGER_DB_FILE")
    if env_path:
        return Path(env_path)
    data_dir = os.environ.get("EXIFTAGGER_DATA_DIR")
    if data_dir:
        return Path(data_dir) / "gallery.db"
    return DEFAULT_DB_PATH


def get_connection(db_path: str | Path | None = None) -> sqlite3.Connection:
    """Get a SQLite database connection with row factory enabled."""
    path = get_db_path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    return conn


def init_db(db_path: str | Path | None = None) -> None:
    """Initialize SQLite database tables and indices if they do not exist."""
    conn = get_connection(db_path)
    try:
        with conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS images (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_path TEXT UNIQUE NOT NULL,
                    filename TEXT NOT NULL,
                    relative_path TEXT NOT NULL,
                    last_modified REAL NOT NULL,
                    file_hash TEXT,
                    indexed_at TEXT NOT NULL
                )
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS image_tags (
                    image_id INTEGER NOT NULL,
                    tag_name TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT 'model',
                    added_at TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY (image_id, tag_name),
                    FOREIGN KEY(image_id) REFERENCES images(id) ON DELETE CASCADE
                )
            """)

            # Schema migration check for existing image_tags table
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(image_tags)").fetchall()}
            if "source" not in columns:
                conn.execute("ALTER TABLE image_tags ADD COLUMN source TEXT NOT NULL DEFAULT 'model';")
            if "added_at" not in columns:
                conn.execute("ALTER TABLE image_tags ADD COLUMN added_at TEXT NOT NULL DEFAULT '';")

            conn.execute("""
                CREATE TABLE IF NOT EXISTS tag_definitions (
                    tag_name TEXT PRIMARY KEY,
                    description TEXT NOT NULL,
                    description_hash TEXT NOT NULL,
                    threshold REAL NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS tag_evaluations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    image_id INTEGER NOT NULL,
                    tag_name TEXT NOT NULL,
                    description_hash TEXT NOT NULL,
                    status TEXT NOT NULL,
                    score REAL NOT NULL DEFAULT 0.0,
                    reason TEXT,
                    model_name TEXT NOT NULL,
                    evaluated_at TEXT NOT NULL,
                    image_mtime REAL NOT NULL,
                    FOREIGN KEY(image_id) REFERENCES images(id) ON DELETE CASCADE,
                    UNIQUE(image_id, tag_name)
                )
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS user_suppressions (
                    image_id INTEGER NOT NULL,
                    tag_name TEXT NOT NULL,
                    suppressed_at TEXT NOT NULL,
                    reason TEXT DEFAULT 'manual_removal',
                    PRIMARY KEY (image_id, tag_name),
                    FOREIGN KEY(image_id) REFERENCES images(id) ON DELETE CASCADE
                )
            """)

            conn.execute("CREATE INDEX IF NOT EXISTS idx_images_file_path ON images(file_path);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_images_relative_path ON images(relative_path);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_image_tags_tag_name ON image_tags(tag_name);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_image_tags_image_id ON image_tags(image_id);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_evaluations_image_tag ON tag_evaluations(image_id, tag_name);")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_suppressions_image_tag ON user_suppressions(image_id, tag_name);"
            )
    finally:
        conn.close()


def sync_gallery_index(
    root_directory: str | Path,
    exclude_patterns: list[str] | None = None,
    db_path: str | Path | None = None,
) -> dict[str, int]:
    """Scan root_directory and sync database with image metadata and EXIF XPTags.

    Returns stats dict: {"total": int, "indexed": int, "updated": int, "deleted": int}.
    """
    init_db(db_path)
    root = Path(root_directory).resolve()
    if not root.exists() or not root.is_dir():
        logger.warning("sync_gallery_index: invalid root directory: %s", root_directory)
        return {"total": 0, "indexed": 0, "updated": 0, "deleted": 0}

    scanned_paths = scan_images(root, exclude_patterns=exclude_patterns)
    scanned_map = {str(p.resolve()): p for p in scanned_paths}

    conn = get_connection(db_path)
    updated_count = 0
    deleted_count = 0

    from datetime import UTC, datetime

    try:
        with conn:
            # 1. Purge records for files that no longer exist or are no longer in scanned set
            existing_rows = conn.execute("SELECT id, file_path, relative_path, last_modified FROM images").fetchall()
            existing_db_map = {}
            for row in existing_rows:
                raw_fp = row["file_path"]
                p = Path(raw_fp)
                abs_p = (root / p).resolve() if not p.is_absolute() else p.resolve()
                existing_db_map[str(abs_p)] = row
                existing_db_map[raw_fp] = row

            for abs_db_path, row in list(existing_db_map.items()):
                db_p = Path(abs_db_path)
                try:
                    db_p.relative_to(root)
                    is_under_root = True
                except ValueError:
                    is_under_root = False

                if is_under_root and (abs_db_path not in scanned_map or not db_p.exists()):
                    conn.execute("DELETE FROM images WHERE id = ?", (row["id"],))
                    deleted_count += 1

            # 2. Insert or update scanned images
            for abs_path_str, img_path in scanned_map.items():
                try:
                    mtime = img_path.stat().st_mtime
                except OSError:
                    continue

                db_entry = existing_db_map.get(abs_path_str)
                needs_update = db_entry is None or abs(db_entry["last_modified"] - mtime) > 0.001

                if needs_update:
                    try:
                        rel_path = img_path.relative_to(root).as_posix()
                    except ValueError:
                        rel_path = img_path.name

                    exif_tags = get_existing_xptags(img_path)
                    now_iso = datetime.now(UTC).isoformat()

                    if db_entry is None:
                        cursor = conn.execute(
                            """
                            INSERT INTO images (file_path, filename, relative_path, last_modified, indexed_at)
                            VALUES (?, ?, ?, ?, ?)
                            """,
                            (abs_path_str, img_path.name, rel_path, mtime, now_iso),
                        )
                        image_id = cursor.lastrowid
                    else:
                        image_id = db_entry["id"]

                        conn.execute(
                            """
                            UPDATE images
                            SET file_path = ?, filename = ?, relative_path = ?, last_modified = ?, indexed_at = ?
                            WHERE id = ?
                            """,
                            (abs_path_str, img_path.name, rel_path, mtime, now_iso, image_id),
                        )

                        old_tags = conn.execute(
                            "SELECT tag_name, source FROM image_tags WHERE image_id = ?", (image_id,)
                        ).fetchall()
                        clean_new_exif = {t.strip().lower() for t in exif_tags if t.strip()}
                        old_tags_map = {ot["tag_name"].lower(): ot["source"] for ot in old_tags}

                        # If a tag was in DB index but removed from EXIF on disk, record user suppression & remove from DB
                        for t_name, source in old_tags_map.items():
                            if t_name not in clean_new_exif:
                                conn.execute(
                                    "INSERT OR IGNORE INTO user_suppressions (image_id, tag_name, suppressed_at, reason) VALUES (?, ?, ?, 'exif_removal')",
                                    (image_id, t_name, now_iso),
                                )
                                conn.execute(
                                    "DELETE FROM image_tags WHERE image_id = ? AND tag_name = ?",
                                    (image_id, t_name),
                                )

                    for t in exif_tags:
                        clean_tag = t.strip().lower()
                        if clean_tag:
                            conn.execute(
                                "INSERT OR IGNORE INTO image_tags (image_id, tag_name, source, added_at) VALUES (?, ?, 'manual_exif', ?)",
                                (image_id, clean_tag, now_iso),
                            )

                    updated_count += 1

        return {
            "total": len(scanned_paths),
            "indexed": len(scanned_map),
            "updated": updated_count,
            "deleted": deleted_count,
        }
    finally:
        conn.close()


def get_gallery_images(
    db_path: str | Path | None = None,
    offset: int = 0,
    limit: int = 50,
    tags: list[str] | None = None,
    search: str | None = None,
    folder: str | None = None,
    root_directory: str | Path | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Retrieve paginated images matching optional tag filter, folder scope, or search/glob string.

    Always uses the filesystem as the source of truth. The database is only
    consulted to attach tag information and indexed status to each file found on
    disk. This guarantees that:
      - Every image that exists on disk is visible in the gallery.
      - Deleted files that linger in the DB are never shown.
      - Unindexed images are always shown (without tags).
      - Tag filtering is applied after enriching filesystem results with DB data.

    Returns (images_list, total_count).
    """
    import fnmatch

    init_db(db_path)
    conn = get_connection(db_path)
    try:
        clean_tags = [t.strip().lower() for t in (tags or []) if t.strip()]

        # ------------------------------------------------------------------ #
        # Resolve root directory                                               #
        # ------------------------------------------------------------------ #
        if root_directory is None:
            first_row = conn.execute("SELECT file_path, relative_path FROM images LIMIT 1").fetchone()
            if first_row and first_row["file_path"]:
                abs_p = Path(first_row["file_path"])
                if abs_p.is_absolute():
                    rel_p = Path(first_row["relative_path"])
                    rel_parts = [p for p in rel_p.parts if p and p != "."]
                    inferred = abs_p
                    for _ in rel_parts:
                        inferred = inferred.parent
                    if inferred.exists() and inferred.is_dir():
                        root_directory = inferred

        if root_directory is None:
            from exif_tagger.config import load_config as _load_config

            try:
                _cfg = _load_config()
                root_directory = _cfg.root_directory
                exclude_patterns: list[str] | None = _cfg.exclude_patterns
            except Exception:
                root_directory = Path(".")
                exclude_patterns = None
        else:
            from exif_tagger.config import load_config as _load_config

            try:
                exclude_patterns = _load_config().exclude_patterns
            except Exception:
                exclude_patterns = None

        root_path = Path(root_directory).resolve()

        # ------------------------------------------------------------------ #
        # Determine scan target (root or a specific sub-folder)               #
        # ------------------------------------------------------------------ #
        if folder:
            clean_folder = folder.strip().strip("/")
            target_path = root_path / clean_folder if clean_folder and clean_folder != "." else root_path
        else:
            target_path = root_path

        if not target_path.exists() or not target_path.is_dir():
            return [], 0

        # ------------------------------------------------------------------ #
        # Scan filesystem                                                      #
        # ------------------------------------------------------------------ #
        scanned_paths = scan_images(target_path, exclude_patterns=exclude_patterns)

        has_glob = search and any(char in search for char in ("*", "?", "["))
        search_pattern = search.strip().lower() if search else None

        # Build list of (abs_path, rel_path, filename) matching search filter
        fs_items: list[tuple[Path, str, str]] = []
        for img_path in scanned_paths:
            try:
                rel_p = img_path.relative_to(root_path).as_posix()
            except ValueError:
                rel_p = img_path.name
            fname = img_path.name

            if search_pattern:
                if has_glob:
                    if not (
                        fnmatch.fnmatch(fname.lower(), search_pattern) or fnmatch.fnmatch(rel_p.lower(), search_pattern)
                    ):
                        continue
                else:
                    if search_pattern not in fname.lower() and search_pattern not in rel_p.lower():
                        continue

            fs_items.append((img_path, rel_p, fname))

        fs_items.sort(key=lambda item: (item[1].lower(), item[2].lower()))

        # ------------------------------------------------------------------ #
        # Batch-load all DB records and their tags for every file on disk     #
        # ------------------------------------------------------------------ #
        db_map: dict[str, sqlite3.Row] = {}
        all_db_rows = conn.execute(
            "SELECT id, file_path, filename, relative_path, last_modified FROM images"
        ).fetchall()
        for r in all_db_rows:
            raw_fp = r["file_path"]
            p = Path(raw_fp)
            abs_p = (root_path / p).resolve() if not p.is_absolute() else p.resolve()
            db_map[str(abs_p)] = r
            db_map[raw_fp] = r
            db_map[r["relative_path"]] = r

        unique_db_rows = {r["id"]: r for r in db_map.values()}
        found_ids = list(unique_db_rows.keys())
        tags_map: dict[int, list[str]] = {img_id: [] for img_id in found_ids}
        if found_ids:
            chunk_size = 900
            for i in range(0, len(found_ids), chunk_size):
                chunk = found_ids[i : i + chunk_size]
                id_placeholders = ",".join("?" for _ in chunk)
                tag_rows = conn.execute(
                    f"SELECT image_id, tag_name FROM image_tags WHERE image_id IN ({id_placeholders}) ORDER BY tag_name ASC",
                    chunk,
                ).fetchall()
                for tr in tag_rows:
                    tags_map[tr["image_id"]].append(tr["tag_name"])

        # ------------------------------------------------------------------ #
        # Apply tag filter (in-memory, using DB-sourced tag data)             #
        # ------------------------------------------------------------------ #
        if clean_tags:
            clean_tags_set = set(clean_tags)
            filtered_items: list[tuple[Path, str, str]] = []
            for img_path, rel_p, fname in fs_items:
                abs_str = str(img_path.resolve())
                db_row = db_map.get(abs_str)
                if not db_row:
                    continue  # unindexed → no tags → cannot match tag filter
                img_tags = set(tags_map.get(db_row["id"], []))
                if clean_tags_set.issubset(img_tags):
                    filtered_items.append((img_path, rel_p, fname))
            fs_items = filtered_items

        # ------------------------------------------------------------------ #
        # Paginate and build result dicts                                      #
        # ------------------------------------------------------------------ #
        total_count = len(fs_items)
        page_slice = fs_items[offset : offset + limit]

        results: list[dict[str, Any]] = []
        for img_path, rel_p, fname in page_slice:
            abs_str = str(img_path.resolve())
            db_row = db_map.get(abs_str)
            if db_row:
                img_id = db_row["id"]
                results.append(
                    {
                        "id": img_id,
                        "file_path": db_row["file_path"],
                        "filename": db_row["filename"],
                        "relative_path": db_row["relative_path"],
                        "last_modified": db_row["last_modified"],
                        "indexed": True,
                        "tags": tags_map.get(img_id, []),
                    }
                )
            else:
                try:
                    mtime = img_path.stat().st_mtime
                except OSError:
                    mtime = 0.0
                results.append(
                    {
                        "id": None,
                        "file_path": abs_str,
                        "filename": fname,
                        "relative_path": rel_p,
                        "last_modified": mtime,
                        "indexed": False,
                        "tags": [],
                    }
                )

        return results, total_count
    finally:
        conn.close()


def sync_single_image(
    relative_or_abs_path: str | Path,
    db_path: str | Path | None = None,
    root_directory: str | Path | None = None,
) -> dict[str, Any]:
    """Index or update a single image file in the SQLite database and return its metadata record."""
    from exif_tagger.config import load_config

    if root_directory is None:
        try:
            config = load_config()
            root_directory = config.root_directory
        except Exception:
            root_directory = Path(".")

    root_path = Path(root_directory).resolve()
    p = Path(relative_or_abs_path)

    img_path = p.resolve() if p.is_absolute() else (root_path / p).resolve()

    if not img_path.exists():
        raise FileNotFoundError(f"Image file not found: {img_path}")

    update_image_in_db_from_file(img_path, root_directory=root_path, db_path=db_path)

    abs_str = str(img_path)
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT id, file_path, filename, relative_path, last_modified FROM images WHERE file_path = ?",
            (abs_str,),
        ).fetchone()

        if not row:
            raise RuntimeError(f"Failed to fetch indexed image from database: {abs_str}")

        img_id = row["id"]
        tag_rows = conn.execute(
            "SELECT tag_name FROM image_tags WHERE image_id = ? ORDER BY tag_name ASC",
            (img_id,),
        ).fetchall()

        return {
            "id": img_id,
            "file_path": row["file_path"],
            "filename": row["filename"],
            "relative_path": row["relative_path"],
            "last_modified": row["last_modified"],
            "indexed": True,
            "tags": [tr["tag_name"] for tr in tag_rows],
        }
    finally:
        conn.close()


def get_gallery_folders(
    relative_path: str = "",
    db_path: str | Path | None = None,
    root_directory: str | Path | None = None,
) -> dict[str, Any]:
    """Get all subdirectories under relative_path (from disk and DB) with image count badges."""
    from exif_tagger.config import load_config

    init_db(db_path)
    conn = get_connection(db_path)
    try:
        clean_rel = relative_path.strip().strip("/").replace("\\", "/")
        if clean_rel == ".":
            clean_rel = ""

        # Determine root directory on disk
        if root_directory is None:
            config = load_config()
            root_directory = config.root_directory

        root_path = Path(root_directory).resolve()
        target_dir = (root_path / clean_rel).resolve() if clean_rel else root_path

        all_subfolders: set[str] = set()
        subfolders_count: dict[str, int] = {}

        # 1. Physical disk scan
        if target_dir.exists() and target_dir.is_dir():
            for item in target_dir.iterdir():
                if item.is_dir() and not item.name.startswith("."):
                    all_subfolders.add(item.name)

        # 2. DB scan for image counts and DB-known folders
        rows = conn.execute("SELECT relative_path FROM images").fetchall()
        for r in rows:
            rel_p = r["relative_path"].replace("\\", "/")
            parts = [p for p in rel_p.split("/") if p]
            clean_rel_lower = clean_rel.lower()

            if not clean_rel:
                if len(parts) > 1:
                    child_folder = parts[0]
                    all_subfolders.add(child_folder)
                    subfolders_count[child_folder] = subfolders_count.get(child_folder, 0) + 1
            else:
                rel_parts = [p.lower() for p in clean_rel_lower.split("/") if p]
                depth = len(rel_parts)
                if len(parts) > depth + 1 and [p.lower() for p in parts[:depth]] == rel_parts:
                    child_folder = parts[depth]
                    all_subfolders.add(child_folder)
                    subfolders_count[child_folder] = subfolders_count.get(child_folder, 0) + 1

        folders_list = []
        for name in sorted(all_subfolders):
            full_path = f"{clean_rel}/{name}" if clean_rel else name
            folders_list.append(
                {
                    "name": name,
                    "relative_path": full_path,
                    "image_count": subfolders_count.get(name, 0),
                }
            )

        breadcrumbs = [{"name": "Root", "path": ""}]
        if clean_rel:
            accum = []
            for part in clean_rel.split("/"):
                accum.append(part)
                breadcrumbs.append({"name": part, "path": "/".join(accum)})

        return {
            "current_path": clean_rel,
            "breadcrumbs": breadcrumbs,
            "folders": folders_list,
            "total_images": len(rows),
        }
    finally:
        conn.close()


def get_all_tags(db_path: str | Path | None = None) -> list[str]:
    """Get sorted list of all unique tag names in database."""
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        rows = conn.execute("SELECT DISTINCT tag_name FROM image_tags ORDER BY tag_name ASC").fetchall()
        return [r["tag_name"] for r in rows]
    finally:
        conn.close()


def get_image_by_id(image_id: int, db_path: str | Path | None = None) -> dict[str, Any] | None:
    """Get detailed metadata and tags for a single image by ID."""
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT id, file_path, filename, relative_path, last_modified FROM images WHERE id = ?",
            (image_id,),
        ).fetchone()
        if not row:
            return None

        tag_rows = conn.execute(
            "SELECT tag_name FROM image_tags WHERE image_id = ? ORDER BY tag_name ASC",
            (image_id,),
        ).fetchall()
        tags = [tr["tag_name"] for tr in tag_rows]

        return {
            "id": row["id"],
            "file_path": row["file_path"],
            "filename": row["filename"],
            "relative_path": row["relative_path"],
            "last_modified": row["last_modified"],
            "tags": tags,
        }
    finally:
        conn.close()


def update_image_tags_in_db_and_exif(
    image_id: int,
    tags: list[str],
    db_path: str | Path | None = None,
    base_dir: Path | None = None,
) -> bool:
    """Update EXIF XPTags and database records for a single image."""
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        row = conn.execute("SELECT id, file_path FROM images WHERE id = ?", (image_id,)).fetchone()
        if not row:
            return False

        image_path = Path(row["file_path"])
        clean_tags = sorted({t.strip().lower() for t in tags if t.strip()})

        # Write to EXIF
        if image_path.exists():
            set_xptags(image_path, clean_tags, base_dir=base_dir)

        mtime = image_path.stat().st_mtime if image_path.exists() else row["last_modified"]

        # Get old tags for suppression tracking
        current_tags_rows = conn.execute("SELECT tag_name FROM image_tags WHERE image_id = ?", (image_id,)).fetchall()
        old_tags = {r["tag_name"].lower() for r in current_tags_rows}

        removed_tags = old_tags - set(clean_tags)
        added_tags = set(clean_tags) - old_tags

        for r_tag in removed_tags:
            record_user_suppression(image_id, r_tag, reason="manual_ui_removal", db_path=db_path)
        for a_tag in added_tags:
            remove_user_suppression(image_id, a_tag, db_path=db_path)

        from datetime import UTC, datetime

        now_iso = datetime.now(UTC).isoformat()

        with conn:
            conn.execute("UPDATE images SET last_modified = ? WHERE id = ?", (mtime, image_id))
            conn.execute("DELETE FROM image_tags WHERE image_id = ?", (image_id,))
            for t in clean_tags:
                source = "manual_ui" if t in added_tags else "model"
                conn.execute(
                    "INSERT OR IGNORE INTO image_tags (image_id, tag_name, source, added_at) VALUES (?, ?, ?, ?)",
                    (image_id, t, source, now_iso),
                )
        return True
    finally:
        conn.close()


def batch_update_tags(
    image_ids: list[int],
    add_tags: list[str],
    remove_tags: list[str],
    db_path: str | Path | None = None,
    base_dir: Path | None = None,
) -> int:
    """Batch add and/or remove tags across multiple images by ID.

    Modifies EXIF XPTags and updates the SQLite database index.
    Returns the count of modified images.
    """
    if not image_ids:
        return 0

    to_add = {t.strip().lower() for t in add_tags if t.strip()}
    to_remove = {t.strip().lower() for t in remove_tags if t.strip()}

    if not to_add and not to_remove:
        return 0

    init_db(db_path)
    conn = get_connection(db_path)
    modified_count = 0

    try:
        placeholders = ",".join("?" for _ in image_ids)
        rows = conn.execute(
            f"SELECT id, file_path FROM images WHERE id IN ({placeholders})",
            image_ids,
        ).fetchall()

        from datetime import UTC, datetime

        now_iso = datetime.now(UTC).isoformat()

        for row in rows:
            img_id = row["id"]
            img_path = Path(row["file_path"])

            # Read current tags
            current_tags_rows = conn.execute("SELECT tag_name FROM image_tags WHERE image_id = ?", (img_id,)).fetchall()
            current_tags = {r["tag_name"].lower() for r in current_tags_rows}

            for r_tag in to_remove:
                record_user_suppression(img_id, r_tag, reason="manual_ui_removal", db_path=db_path)
            for a_tag in to_add:
                remove_user_suppression(img_id, a_tag, db_path=db_path)

            new_tags = (current_tags | to_add) - to_remove
            if new_tags != current_tags:
                sorted_tags = sorted(new_tags)
                if img_path.exists():
                    set_xptags(img_path, sorted_tags, base_dir=base_dir)

                mtime = img_path.stat().st_mtime if img_path.exists() else 0.0

                with conn:
                    conn.execute("UPDATE images SET last_modified = ? WHERE id = ?", (mtime, img_id))
                    conn.execute("DELETE FROM image_tags WHERE image_id = ?", (img_id,))
                    for t in sorted_tags:
                        source = "manual_ui" if t in to_add else "model"
                        conn.execute(
                            "INSERT OR IGNORE INTO image_tags (image_id, tag_name, source, added_at) VALUES (?, ?, ?, ?)",
                            (img_id, t, source, now_iso),
                        )
                modified_count += 1

        return modified_count
    finally:
        conn.close()


def remove_tag_globally(
    tag_name: str,
    db_path: str | Path | None = None,
    base_dir: Path | None = None,
) -> int:
    """Remove a specified tag from ALL images in the gallery and update EXIF metadata.

    Returns the count of images modified.
    """
    clean_tag = tag_name.strip().lower()
    if not clean_tag:
        return 0

    init_db(db_path)
    conn = get_connection(db_path)
    try:
        matching_rows = conn.execute(
            "SELECT DISTINCT image_id FROM image_tags WHERE tag_name = ?", (clean_tag,)
        ).fetchall()
        image_ids = [r["image_id"] for r in matching_rows]

        if not image_ids:
            return 0

        return batch_update_tags(
            image_ids=image_ids,
            add_tags=[],
            remove_tags=[clean_tag],
            db_path=db_path,
            base_dir=base_dir,
        )
    finally:
        conn.close()


def update_image_in_db_from_file(
    img_path: str | Path,
    root_directory: str | Path | None = None,
    db_path: str | Path | None = None,
) -> None:
    """Insert or update a single image record and its current EXIF XPTags in the SQLite database."""
    init_db(db_path)
    path = Path(img_path).resolve()
    if not path.exists():
        return

    try:
        mtime = path.stat().st_mtime
    except OSError:
        return

    abs_path_str = str(path)
    if root_directory:
        root = Path(root_directory).resolve()
        try:
            rel_path = path.relative_to(root).as_posix()
        except ValueError:
            rel_path = path.name
    else:
        rel_path = path.name

    exif_tags = get_existing_xptags(path)
    from datetime import UTC, datetime

    now_iso = datetime.now(UTC).isoformat()

    conn = get_connection(db_path)
    try:
        with conn:
            row = conn.execute("SELECT id FROM images WHERE file_path = ?", (abs_path_str,)).fetchone()
            if row is None:
                cursor = conn.execute(
                    """
                    INSERT INTO images (file_path, filename, relative_path, last_modified, indexed_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (abs_path_str, path.name, rel_path, mtime, now_iso),
                )
                image_id = cursor.lastrowid
            else:
                image_id = row["id"]
                conn.execute(
                    """
                    UPDATE images
                    SET filename = ?, relative_path = ?, last_modified = ?, indexed_at = ?
                    WHERE id = ?
                    """,
                    (path.name, rel_path, mtime, now_iso, image_id),
                )
                conn.execute("DELETE FROM image_tags WHERE image_id = ?", (image_id,))

            for t in exif_tags:
                clean_tag = t.strip().lower()
                if clean_tag:
                    conn.execute(
                        "INSERT OR IGNORE INTO image_tags (image_id, tag_name) VALUES (?, ?)",
                        (image_id, clean_tag),
                    )
    finally:
        conn.close()


def record_tag_evaluation(
    image_id: int,
    tag_name: str,
    description_hash: str,
    status: str,
    score: float,
    reason: str | None,
    model_name: str,
    image_mtime: float,
    db_path: str | Path | None = None,
) -> None:
    """Insert or replace a tag evaluation record for an image and tag pair."""
    from datetime import UTC, datetime

    init_db(db_path)
    conn = get_connection(db_path)
    now_iso = datetime.now(UTC).isoformat()
    clean_tag = tag_name.strip().lower()

    try:
        with conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO tag_evaluations
                (image_id, tag_name, description_hash, status, score, reason, model_name, evaluated_at, image_mtime)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    image_id,
                    clean_tag,
                    description_hash,
                    status,
                    score,
                    reason,
                    model_name,
                    now_iso,
                    image_mtime,
                ),
            )
    finally:
        conn.close()


def record_user_suppression(
    image_id: int,
    tag_name: str,
    reason: str = "manual_removal",
    db_path: str | Path | None = None,
) -> None:
    """Record a user suppression for an image and tag pair to prevent future automated tagging."""
    from datetime import UTC, datetime

    init_db(db_path)
    conn = get_connection(db_path)
    now_iso = datetime.now(UTC).isoformat()
    clean_tag = tag_name.strip().lower()

    try:
        with conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO user_suppressions (image_id, tag_name, suppressed_at, reason)
                VALUES (?, ?, ?, ?)
                """,
                (image_id, clean_tag, now_iso, reason),
            )
            # Remove from active image_tags if present
            conn.execute(
                "DELETE FROM image_tags WHERE image_id = ? AND tag_name = ?",
                (image_id, clean_tag),
            )
    finally:
        conn.close()


def remove_user_suppression(
    image_id: int,
    tag_name: str,
    db_path: str | Path | None = None,
) -> None:
    """Remove a user suppression record, allowing future automated re-evaluation."""
    init_db(db_path)
    conn = get_connection(db_path)
    clean_tag = tag_name.strip().lower()

    try:
        with conn:
            conn.execute(
                "DELETE FROM user_suppressions WHERE image_id = ? AND tag_name = ?",
                (image_id, clean_tag),
            )
    finally:
        conn.close()


def get_unevaluated_candidates(
    root_directory: str | Path,
    active_tags: dict[str, Any],
    tag_hashes: dict[str, str],
    subfolder: str | None = None,
    limit: int | None = None,
    db_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Return (image, tag) candidate objects that require Vision Model AI evaluation.

    Excludes tags that are suppressed by user or already evaluated with the current description_hash & mtime.
    """
    init_db(db_path)
    root = Path(root_directory).resolve()
    conn = get_connection(db_path)

    try:
        # Build image filtering query
        query_sql = "SELECT id, file_path, relative_path, last_modified FROM images"
        params: list[Any] = []

        if subfolder:
            clean_sub = subfolder.replace("\\", "/").strip("/").lower()
            if clean_sub and clean_sub != ".":
                query_sql += " WHERE (LOWER(REPLACE(relative_path, '\\', '/')) LIKE ? OR LOWER(REPLACE(relative_path, '\\', '/')) = ?)"
                params.extend([f"{clean_sub}/%", clean_sub])

        query_sql += " ORDER BY id ASC"
        rows = conn.execute(query_sql, params).fetchall()

        # Build lookup set of suppressions: set of (image_id, tag_name)
        sup_rows = conn.execute("SELECT image_id, tag_name FROM user_suppressions").fetchall()
        suppressed_set = {(r["image_id"], r["tag_name"].lower()) for r in sup_rows}

        # Build lookup dict of existing evaluations: (image_id, tag_name) -> (description_hash, image_mtime)
        eval_rows = conn.execute(
            "SELECT image_id, tag_name, description_hash, image_mtime FROM tag_evaluations"
        ).fetchall()
        eval_map = {
            (r["image_id"], r["tag_name"].lower()): (r["description_hash"], r["image_mtime"]) for r in eval_rows
        }

        candidates: list[dict[str, Any]] = []

        for row in rows:
            img_id = row["id"]
            img_path_str = row["file_path"]
            rel_path = row["relative_path"]
            mtime = row["last_modified"]

            for tag_name, tag_def in active_tags.items():
                clean_tag = tag_name.strip().lower()
                desc_hash = tag_hashes.get(clean_tag, "")

                # 1. Skip if suppressed by user
                if (img_id, clean_tag) in suppressed_set:
                    continue

                # 2. Check if already evaluated with matching hash and mtime
                existing_eval = eval_map.get((img_id, clean_tag))
                if existing_eval is not None:
                    e_hash, e_mtime = existing_eval
                    if e_hash == desc_hash and abs(e_mtime - mtime) < 0.001:
                        continue

                candidates.append(
                    {
                        "image_id": img_id,
                        "file_path": img_path_str,
                        "relative_path": rel_path,
                        "tag_name": clean_tag,
                        "tag_def": tag_def,
                        "description_hash": desc_hash,
                        "image_mtime": mtime,
                    }
                )

                if limit and len(candidates) >= limit:
                    return candidates

        return candidates
    finally:
        conn.close()


def evaluate_thresholds_locally(
    root_directory: str | Path,
    active_tags: dict[str, Any],
    tag_hashes: dict[str, str],
    db_path: str | Path | None = None,
) -> dict[str, int]:
    """Re-evaluates existing confidence scores against new thresholds without AI API calls.

    Updates image_tags and EXIF XPTags if a tag score crosses the updated threshold.
    Returns stats dict: {"added": int, "removed": int}.
    """
    init_db(db_path)
    conn = get_connection(db_path)
    added_count = 0
    removed_count = 0

    try:
        # Load all evaluations matching current description hashes
        eval_rows = conn.execute(
            "SELECT image_id, tag_name, description_hash, score, status FROM tag_evaluations"
        ).fetchall()

        # Group by image_id
        image_evals: dict[int, list[sqlite3.Row]] = {}
        for er in eval_rows:
            image_evals.setdefault(er["image_id"], []).append(er)

        # Get existing image tags and suppressions
        tag_rows = conn.execute("SELECT image_id, tag_name, source FROM image_tags").fetchall()
        existing_tags_map: dict[int, set[str]] = {}
        for tr in tag_rows:
            existing_tags_map.setdefault(tr["image_id"], set()).add(tr["tag_name"].lower())

        sup_rows = conn.execute("SELECT image_id, tag_name FROM user_suppressions").fetchall()
        suppressed_set = {(r["image_id"], r["tag_name"].lower()) for r in sup_rows}

        image_rows = conn.execute("SELECT id, file_path FROM images").fetchall()
        img_path_map = {r["id"]: Path(r["file_path"]) for r in image_rows}

        for img_id, evals in image_evals.items():
            img_path = img_path_map.get(img_id)
            if not img_path or not img_path.exists():
                continue

            current_tags = set(existing_tags_map.get(img_id, set()))
            modified = False

            for ev in evals:
                t_name = ev["tag_name"].lower()
                tag_def = active_tags.get(t_name)
                if not tag_def:
                    continue

                curr_hash = tag_hashes.get(t_name, "")
                if ev["description_hash"] != curr_hash:
                    # Skip local update if description changed (needs AI call)
                    continue

                if (img_id, t_name) in suppressed_set:
                    continue

                threshold = getattr(tag_def, "threshold", 0.7)
                score = ev["score"]
                should_be_tagged = (score >= threshold) and (ev["status"] == "matched")

                if should_be_tagged and t_name not in current_tags:
                    current_tags.add(t_name)
                    added_count += 1
                    modified = True
                elif not should_be_tagged and t_name in current_tags:
                    # Only remove if added by model
                    current_tags.remove(t_name)
                    removed_count += 1
                    modified = True

            if modified:
                sorted_tags = sorted(current_tags)
                from exif_tagger.exif_writer import set_xptags

                set_xptags(img_path, sorted_tags)

                mtime = img_path.stat().st_mtime
                from datetime import UTC, datetime

                now_iso = datetime.now(UTC).isoformat()

                with conn:
                    conn.execute("UPDATE images SET last_modified = ? WHERE id = ?", (mtime, img_id))
                    conn.execute("DELETE FROM image_tags WHERE image_id = ?", (img_id,))
                    for t in sorted_tags:
                        conn.execute(
                            "INSERT OR IGNORE INTO image_tags (image_id, tag_name, source, added_at) VALUES (?, ?, 'model', ?)",
                            (img_id, t, now_iso),
                        )

        return {"added": added_count, "removed": removed_count}
    finally:
        conn.close()


def get_image_suppressions(
    image_id: int,
    db_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Get list of user suppressions for a given image ID."""
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            "SELECT tag_name, suppressed_at, reason FROM user_suppressions WHERE image_id = ? ORDER BY tag_name ASC",
            (image_id,),
        ).fetchall()
        return [
            {
                "tag_name": r["tag_name"],
                "suppressed_at": r["suppressed_at"],
                "reason": r["reason"],
            }
            for r in rows
        ]
    finally:
        conn.close()
