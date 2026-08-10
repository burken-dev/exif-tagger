# Gallery Index Poller — DB-backed Gallery Reads

**Date:** 2026-08-10
**Status:** Approved for planning

## Problem

Every gallery read (`GET /api/gallery/images`) currently performs a full
recursive filesystem scan (`scan_images`), enriches the result with SQLite tags,
and filters in memory — cached only for 3 seconds in `_gallery_view_cache`
(`db.py:26-32`). Every cache miss (folder change, tag toggle, search keystroke,
page turn) pays the full O(N) walk. The filesystem is treated as the source of
truth on every request.

Goal: scan the gallery once, serve reads from the database (fast SQL), and keep
the index in sync with the filesystem via a lightweight background poller that
reconciles only changed folders.

## Decisions (agreed during brainstorming)

1. **Change detection:** periodic poll using the existing `BackgroundScheduler`
   (apscheduler). No inotify/watchdog dependency; robust on Docker/NFS mounts.
2. **Rescan scope:** the poller refreshes the **file listing only** (paths +
   mtimes). It never reads EXIF and never touches tags or vision state.
3. **Read path:** gallery image queries become **DB-only** (pure SQL). The
   on-disk scan-per-request code path is removed.
4. **Folder navigation:** `get_gallery_folders` stays disk-based (cheap single
   `iterdir()`), keeping empty folders visible.
5. **Primary approach:** dir-mtime pruning (`dir_mtimes` table). Full-walk diff
   reconcile is the fallback if pruning misbehaves.
6. **Workload profile:** library is mostly static; only the current month churns.
   Steady-state poll cost must approach zero.

## Architecture

```
┌─────────────────────────── server.py ───────────────────────────┐
│  BackgroundScheduler (already exists)                            │
│    ├─ user schedules (as today)                                  │
│    └─ NEW: IndexPoller job  (interval, coalesce=True)            │
│         │  guarded by _sync_lock  (never overlaps manual sync)   │
│         ▼                                                        │
│  reconcile_gallery_index(root) ── dir-mtime pruning               │
│         ▼                                                        │
│  gallery.db  images / dir_mtimes   ◀── discovery layer            │
│               ▲                                                 │
│   GET /api/gallery/images  ── pure SQL reads (no fs access)      │
│   get_gallery_folders      ── unchanged (disk iterdir)            │
└──────────────────────────────────────────────────────────────────┘
```

Two owners, strictly separated:

- **Discovery** (`images` + new `dir_mtimes`): owned by the poller. Mirrors what
  is on disk. Never reads EXIF, never touches tags.
- **Derived** (`image_tags`, `tag_evaluations`, `user_suppressions`): owned by
  the existing sync/pipeline. Unchanged.

The old `_build_gallery_view`, the `scan_images`-per-request pipeline, and the
3s `_gallery_view_cache` are removed. `_invalidate_gallery_view_cache` call
sites become no-ops.

## Data model

```sql
-- NEW: pruning baselines (one row per scanned directory)
CREATE TABLE IF NOT EXISTS dir_mtimes (
    dir_path   TEXT PRIMARY KEY,   -- absolute dir path
    mtime      REAL NOT NULL,      -- os.stat(dir).st_mtime at last good scan
    scanned_at TEXT NOT NULL
);

-- NEW column on images: decouples discovery from EXIF bookkeeping
ALTER TABLE images ADD COLUMN exif_mtime REAL;  -- NULL = EXIF never extracted
```

### The `exif_mtime` decoupling (correctness requirement)

Today `sync_gallery_index` uses `last_modified` as its "re-extract EXIF?" signal
(`needs_update = mtime differs`, `db.py:205`). If the poller also wrote
`last_modified` = disk mtime, then:

- poller inserts a new file → `sync_gallery_index` sees
  `last_modified == disk mtime` → **skips EXIF extraction** → new files never get
  tags;
- exactly the "folder looks populated but untagged and processing never kicks
  in" hazard.

Fix: the poller owns `last_modified` (display freshness); the sync compares
against the new `exif_mtime` column instead.

- Walker sets `file_path` / `filename` / `relative_path` / `last_modified`,
  never `exif_mtime`.
- `sync_gallery_index` / `sync_single_image` extract EXIF where
  `exif_mtime IS NULL OR abs(exif_mtime - disk_mtime) > 0.001`, then set
  `exif_mtime = disk_mtime`.
- `update_image_tags_in_db_and_exif` sets `exif_mtime` after writing EXIF.

## The reconcile walker

Hand-rolled top-down scandir walk (new function `reconcile_gallery_index` in
`db.py`), *not* `scan_images` — pruning needs per-dir control.

```
walk(root):
  stack = [root]
  for each dir d popped:
    stat d  (missing → skip)
    stored = dir_mtimes[d]
    if stored is not None and |stored - d.mtime| <= 0.001:   # unchanged
        continue                                              # prune, don't descend
    pre = stat(d).mtime                                       # snapshot before scan
    scan d:
      - list children via scandir
      - push subdirs onto stack
      - collect image filenames (reuse _is_image_path)
    reconcile d's files:
      - delete images rows whose relative_path starts with d's rel + '/'
        that are no longer present
      - delete stored child dirs (dir_mtimes where dir_path LIKE d + '/%')
        whose subdir is absent → subtree purge handles removed/renamed folders
      - upsert present files (file_path, filename, relative_path, last_modified)
        — NEVER touch exif_mtime
    post = stat(d).mtime
    if |pre - post| <= 0.001:   dir_mtimes[d] = post   # clean, set baseline
    else:                       leave baseline stale    # raced → next poll rescans
```

Correctness notes:

- **New dirs** — no baseline → treated as changed → scanned.
- **Removed dirs** — removing a child updates the parent's dir mtime, so the
  parent is rescanned; the child is absent from scandir → subtree purge (delete
  child's images rows by relative-path prefix).
- **Renames** — appear as delete+insert on the parent scan, **but must update
  the images row in place (match by old `file_path`, update paths, keep `id`)**
  so that `image_tags` (FK'd to `images.id`) is not orphaned.
- **Validate-before-commit** — the pre/post re-stat. Any change racing the scan
  leaves the baseline stale, so the next poll re-scans that dir. Self-healing.
- **Errors** — unreadable dir → log + leave baseline stale (retry next poll).
  Root missing → log, skip round. WAL + `busy_timeout` for SQLite contention;
  poller serialized with manual syncs by `_sync_lock`.
- **eps** — `0.001` mtime tolerance, same convention as `db.py:205`.

### Fallback (Approach A)

If the poller fails or pruning misbehaves, a full-walk reconcile rebuilds all
baselines — same function with the pruning check disabled. Invoked manually or
automatically after N failed poll rounds. Reads remain DB-only either way.

## Read path (SQL)

Rewrite `get_gallery_images` to a DB-only query, preserving today's exact
semantics:

```sql
SELECT i.id, i.file_path, i.filename, i.relative_path, i.last_modified
FROM images i
WHERE (:folder = '' OR i.relative_path = :folder OR i.relative_path LIKE :folder || '/%')
  AND i.id IN (
      SELECT image_id FROM image_tags
      WHERE tag_name IN (:t1, :t2, ...)          -- lowercased, parameterized
      GROUP BY image_id HAVING COUNT(DISTINCT tag_name) = :n
  )
ORDER BY i.relative_path COLLATE NOCASE, i.filename COLLATE NOCASE
```

The tag subquery is **only added when tags are non-empty** (an empty `IN ()`
clause is invalid SQL); with no tags selected the `id IN (...)` clause is
omitted entirely.

Then in Python (mirrors current `_build_gallery_view:304-312` exactly):

- **Search** applied as a post-filter on the result rows — substring or `fnmatch`
  on filename/relative_path. Done in Python (not SQL) to preserve the current
  Unicode-aware `.lower()` behavior (Swedish filenames with å/ä/ö) and exact
  fnmatch semantics, at no extra cost since the filtered set is already loaded
  for the count.
- **Tag filter** in SQL via the `HAVING COUNT` subquery (AND semantics, same as
  today's `issubset`).
- Then paginate the in-memory list (`offset`/`limit`) and batch-load `image_tags`
  for just the page slice (chunked, as today).

Result: zero filesystem access per request; one indexed query for folder+tag;
search is O(filtered set) substring checks.

**Unindexed images** — the `id = null` branch (`db.py:506-521`) disappears:
every file on disk now has an `images` row, so `indexed: true` always and the
response no longer carries `id: null`. Frontend null-id handling can be
simplified later (out of scope).

`get_gallery_folders` and `get_all_tags` stay as-is.

## Startup & config

**Startup** (`lifespan`, `server.py:835`): the current `_run_gallery_sync()`
thread (full EXIF sync) stays — it is the derived-state owner. New behavior:

1. Run `reconcile_gallery_index` once, **synchronously**, before serving — first
   pass has no baselines so it is a full walk (the "scan once" warm-up, seconds
   for ~100k files). Guarantees the gallery never reads an empty index.
2. Register the poller with the existing `BackgroundScheduler`
   (`server.py:180`): `IntervalTrigger(seconds=poll_interval)`, `coalesce=True`,
   `max_instances=1`, acquiring `_sync_lock` per run.
3. The EXIF sync thread then proceeds under the same lock — with the
   `exif_mtime` decoupling it extracts tags for every file with
   `exif_mtime IS NULL` (all on first boot), independent of what the walker
   wrote.

**Config** (`config.yaml`): two knobs, both with defaults:

```yaml
gallery_index:
  poll_interval_seconds: 10   # 0 disables the poller
  enabled: true
```

**Edge:** the rename case is the one place tag preservation depends on
implementation care — match by old `file_path`, update in place, keep `id`. This
is called out explicitly in the implementation plan.

## Testing

Existing tests that exercise the scan path get updated to the SQL path:

- `tests/test_gallery_db.py`, `test_gallery_api.py`,
  `test_gallery_folders_and_glob.py`, `test_db_state.py`,
  `tests/test_server.py` — filter/search/tag/folder assertions stay the same,
  backend swaps.
- `test_gallery_images_filesystem_unindexed` — the "unindexed file shows with
  id=null" behavior goes away; test becomes "file appears with id and empty
  tags".

New unit tests for the walker:

- add file → appears; delete → removed; rename → same `id`, tags preserved,
  paths updated.
- unchanged dir → pruned (instrument: assert its files aren't re-stat'd).
- new nested dir → discovered; removed folder → subtree purged (images rows +
  `dir_mtimes`).
- race: dir mtime changes during scan → baseline left stale → caught next round.
- `exif_mtime`: poller insert leaves it NULL; `sync_gallery_index` then extracts
  EXIF and sets it; in-place file edit triggers re-extract.
- fallback: full-walk reconcile == incremental reconcile (same resulting
  `images` set).

Integration: poller round + read endpoint e2e; poller vs manual sync under the
shared lock.

## Out of scope

- Frontend simplification of null-id / unindexed handling.
- Watchdog/inotify realtime events (polling chosen deliberately).
- Changes to `tag_evaluations`, `user_suppressions`, `tag_definitions` semantics.
