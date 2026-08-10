"""SQLite database module for indexing and querying images and their XPTags.

Provides fast database indexing of photos in gallery root directory for web UI gallery browsing,
filtering by tags, single image tag editing, batch tag updates, and global tag removal.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

from exif_tagger.exif_writer import get_existing_xptags, set_xptags
from exif_tagger.image_scanner import _is_image_path, build_exclude_compilers, scan_images

logger = logging.getLogger(__name__)

_config_dir = Path(__file__).resolve().parent.parent.parent
DEFAULT_DB_PATH = _config_dir / "gallery.db"
_MTIME_EPS = 0.001


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

            images_cols = {row["name"] for row in conn.execute("PRAGMA table_info(images)").fetchall()}
            if "exif_mtime" not in images_cols:
                conn.execute("ALTER TABLE images ADD COLUMN exif_mtime REAL;")

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

            conn.execute("""
                CREATE TABLE IF NOT EXISTS dir_mtimes (
                    dir_path TEXT PRIMARY KEY,
                    mtime REAL NOT NULL,
                    scanned_at TEXT NOT NULL
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
            existing_rows = conn.execute("SELECT id, file_path, relative_path, last_modified, exif_mtime FROM images").fetchall()
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
                needs_update = (
                    db_entry is None
                    or db_entry["exif_mtime"] is None
                    or abs(db_entry["exif_mtime"] - mtime) > 0.001
                )

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
                            INSERT INTO images (file_path, filename, relative_path, last_modified, exif_mtime, indexed_at)
                            VALUES (?, ?, ?, ?, ?, ?)
                            """,
                            (abs_path_str, img_path.name, rel_path, mtime, mtime, now_iso),
                        )
                        image_id = cursor.lastrowid
                    else:
                        image_id = db_entry["id"]

                        conn.execute(
                            """
                            UPDATE images
                            SET file_path = ?, filename = ?, relative_path = ?, last_modified = ?, exif_mtime = ?, indexed_at = ?
                            WHERE id = ?
                            """,
                            (abs_path_str, img_path.name, rel_path, mtime, mtime, now_iso, image_id),
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
                    if cand_name is not None and cand_name in present_files and cand_name not in old_by_seg:
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
                    cur = conn.execute(
                        "DELETE FROM images WHERE relative_path = ? OR relative_path LIKE ? || '/%'",
                        (seg_rel, seg_rel),
                    )
                    seg_abs = f"{d_abs}/{seg}"
                    conn.execute(
                        "DELETE FROM dir_mtimes WHERE dir_path = ? OR dir_path LIKE ? || '/%'",
                        (seg_abs, seg_abs),
                    )
                    stats["removed"] += cur.rowcount

                # Subtree purge for removed/renamed child dirs: absent from scandir
                # but still present in dir_mtimes baselines.
                stored_children = conn.execute(
                    "SELECT dir_path FROM dir_mtimes "
                    "WHERE dir_path LIKE ? AND dir_path NOT LIKE ?",
                    (f"{d_abs}/%", f"{d_abs}/%/%"),
                ).fetchall()
                for sc in stored_children:
                    if Path(sc["dir_path"]).name in present_dirs:
                        continue
                    child_rel = Path(sc["dir_path"]).relative_to(root).as_posix()
                    cur = conn.execute(
                        "DELETE FROM images WHERE relative_path = ? OR relative_path LIKE ? || '/%'",
                        (child_rel, child_rel),
                    )
                    conn.execute(
                        "DELETE FROM dir_mtimes WHERE dir_path = ? OR dir_path LIKE ? || '/%'",
                        (sc["dir_path"], sc["dir_path"]),
                    )
                    stats["removed"] += cur.rowcount

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
    """Get subdirectories under relative_path directly from disk (no image counts)."""
    from exif_tagger.config import load_config

    if root_directory is None:
        try:
            config = load_config()
            root_directory = config.root_directory
        except Exception:
            root_directory = Path(".")

    clean_rel = relative_path.strip().strip("/").replace("\\", "/")
    if clean_rel == ".":
        clean_rel = ""

    root_path = Path(root_directory).resolve()
    target_dir = (root_path / clean_rel).resolve() if clean_rel else root_path

    all_subfolders: set[str] = set()
    if target_dir.exists() and target_dir.is_dir():
        for item in target_dir.iterdir():
            if item.is_dir() and not item.name.startswith("."):
                all_subfolders.add(item.name)

    folders_list = [
        {"name": name, "relative_path": f"{clean_rel}/{name}" if clean_rel else name} for name in sorted(all_subfolders)
    ]

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
    }


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
            conn.execute("UPDATE images SET last_modified = ?, exif_mtime = ? WHERE id = ?", (mtime, mtime, image_id))
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
                    conn.execute("UPDATE images SET last_modified = ?, exif_mtime = ? WHERE id = ?", (mtime, mtime, img_id))
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

    from datetime import UTC, datetime

    now_iso = datetime.now(UTC).isoformat()

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
                    conn.execute("UPDATE images SET last_modified = ?, exif_mtime = ? WHERE id = ?", (mtime, mtime, img_id))
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
