# Agent Guidelines for Recasa

## Running the Application

**This app runs in Docker, from the single `docker-compose.yml`.** Do not run backend/frontend directly with uvicorn/npm, and do not add extra compose files for hosts or dev modes: per-host values go in `.env`.

It runs on **velvet** (Raspberry Pi 5), in `~/code/recasa`, container `recasa-recasa-1`, UI on port 7000.

```bash
docker compose up -d --build     # apply any change (backend, frontend, deps)
docker compose logs -f recasa    # logs
docker compose restart recasa    # restart without rebuilding
```

### The index is precious

`RECASA_DATA_PATH` in `.env` (on velvet `/mnt/ssd/recasa/data`) holds the database with ~40k photos' captions, faces, tags and person names - weeks of processing. Compose refuses to start without `PHOTOS_PATH` and `RECASA_DATA_PATH`; keep it that way. On 2026-10-22 a rebuild with a since-removed desktop compose file mounted an empty volume instead, and Recasa silently re-indexed and re-captioned the whole library for two weeks.

- Never `docker compose down -v`, and never delete the data directory. Nightly snapshots are in `/mnt/ssd/recasa/backups`.
- After any recreate, check it is the real index: `docker inspect recasa-recasa-1` must show `/mnt/ssd/recasa/data` on `/data`, and the startup log must not report tens of thousands of photos "needing captioning".
- Schema changes are additive only (see Migration Strategy). Never drop, rebuild or "reset" the database to get a schema change in.

### Architecture

- **Backend**: Python FastAPI app in `backend/`
- **Frontend**: React/Vite/TypeScript app in `frontend/`
- **Container**: one container with nginx (port 8080) reverse-proxying `/api/` to uvicorn (port 8000) and serving the frontend from `/app/frontend/dist`. nginx also serves generated thumbnails straight from `/data/thumbs` and falls back to the API for anything else. The Dockerfile builds the frontend itself, so no host `npm run build` is needed.

### Making changes

Source code is baked into the image, not mounted. Any change - Python, React, dependencies, Dockerfile, nginx, `start.sh` - goes live with `docker compose up -d --build`. A plain restart does not pick up code changes. `UVICORN_RELOAD` stays `false` (auto-reload hurts performance a lot).

Test in the browser on port 7000 (nginx), not on a Vite dev server.

### Verifying Changes Are Live

```bash
docker exec recasa-recasa-1 cat /app/frontend/dist/index.html          # latest Vite asset hash
docker exec recasa-recasa-1 grep "function_name" /app/backend/app/api/some_file.py
curl -s http://localhost:7000/api/health
```

### Testing

- Unit tests: `python -m pytest backend/tests/unit` (no Docker, network or ML models)
- Integration tests: `docker-compose -f docker-compose.test.yml up --build --abort-on-container-exit`
- Consistency test: `docker exec -it recasa-recasa-1 python -m backend.tests.test_consistency`
- Frontend tests: Located in `frontend/tests/` (Playwright)

---

## Design Philosophy

### Core Principle: No State Flags

**Photos are immutable.** Once a photo exists on disk with a specific hash, it never changes. Therefore:

1. **No boolean processing flags** in the Photo model (no `exif_extracted`, `thumbnail_generated`, etc.)
2. **Data existence IS the state** - if `camera_make` is populated, EXIF was extracted
3. **File existence IS the state** - if `thumbs/{hash}_200.jpg` exists, thumbnail is generated

### Processing Stages

Three stages can be switched off in `.env`; the rest always run:

```
ENABLE_GEOCODING=true
ENABLE_FACE_DETECTION=true
ENABLE_CAPTIONING=true
```

EXIF, thumbnails, motion photos and hashing have no switch: timeline order,
every grid and duplicate detection depend on them. Older `.env` files may still
set `ENABLE_EXIF_EXTRACTION`, `ENABLE_THUMBNAILS`, `ENABLE_MOTION_PHOTOS` or
`ENABLE_HASHING`; nothing reads them, and setting one to `false` is logged as
ignored at startup.

**Key behaviors:**
- Even with ALL optional stages disabled, photos are visible in the app (sorted by file_modified)
- If a stage is enabled, rescan will process photos missing that stage's output
- If output already exists for a stage, that stage is skipped (not the whole photo!)

### Per-Stage Skip Logic

Each stage is checked INDEPENDENTLY. A photo flows through the pipeline:

```
Photo enters pipeline:
  → EXIF stage: camera_make exists? YES → skip EXIF, continue
               camera_make exists? NO  → process EXIF, continue
  
  → Thumbnails stage: thumb file exists? YES → skip thumbs, continue
                      thumb file exists? NO  → generate thumbs, continue
  
  → Faces stage: faces records exist? YES → skip faces, continue
                 faces records exist? NO  → detect faces, continue
  
  → Captioning stage: caption record exists? YES → skip, done
                      caption record exists? NO  → generate caption, done
```

**Key insight:** Skip per-stage, not per-photo. A photo might have EXIF but no faces, or thumbnails but no caption.

### How to Check if Stage Output Exists

These rules live in one place, `backend/app/workers/stages.py`, used by the
scanner, startup resume and the workers alike. Changing one means
re-processing (or never processing) part of the library.

| Stage | "Output Exists?" Check |
|-------|----------------------|
| EXIF | `camera_make IS NOT NULL` OR `date_taken IS NOT NULL` (a photo without EXIF gets its file date) |
| Geocoding | `location_city IS NOT NULL` (only applies to photos with both `gps_latitude` and `gps_longitude`) |
| Thumbnails | File exists: `/data/thumbs/{file_hash[:2]}/{file_hash}_200.webp` (written last of the three sizes) |
| Motion Photos | No check: runs for every photo, a no-op unless `motion_photo` is set and `live_photo_video` is not. The video goes to `/data/motion_videos/{file_hash[:2]}/{file_hash}_motion.mp4`; videos named after the file stem by older versions stay readable |
| Hashing | Record exists in `photo_hashes` table for this file_hash |
| Faces | Record exists in `faces` table for this file_hash (a row with NULL `encoding` is the "checked, no faces" marker) |
| Captioning | Record exists in `captions` table for this file_hash (a row with NULL `caption` is the "done, nothing usable" marker; no row is written while Ollama is unreachable, so the photo is retried) |

Videos only get a poster thumbnail; every other stage skips them.

### Processing Flow

1. **Scan**: Walk filesystem, add photos to DB (minimal: hash, path, filename, size, file_modified)
2. **Queue**: Queue each photo once, at its first stage that is enabled, applies, has no output and has no recorded failure
3. **Worker**: Pick `file_hash` from queue, check output existence again (idempotent), process if needed
4. **Flow**: After a stage (processed or skipped), the photo proceeds to the next stage: EXIF, geocoding, thumbnails, motion photos, hashing, faces, captioning, then the batch step (face clustering, duplicates, events)
5. **Dashboard**: Query actual data existence (COUNT where camera_make IS NOT NULL, etc.)

### No Memory State

The queue system keeps ONLY:
- An `asyncio.Queue` holding `file_hash` strings for worker parallelism and backpressure
- NO pending/processing/completed counters (query DB/disk instead)
- NO `_processed` sets (check DB/disk instead)

**Why this works:**
- Crash recovery: On startup, query photos missing each enabled stage's output, queue them
- Progress visibility: Dashboard queries actual data existence
- No corrupted state: DB and filesystem are the only sources of truth

### Auto-Resume on Startup

On app startup, auto-queue photos with incomplete processing:
- Load every stage's output in bulk and queue each photo at its first needed stage (same rules as the scanner)
- The log reports "Found N photos needing <stage>" per stage, counting only photos that will really be processed
- This handles crashes gracefully - processing resumes automatically
- No user action needed

### Error Handling

- Log errors per-photo when they happen (standard Python logging)
- Transient errors (a service down, network) are not stored: the photo simply
  lacks that stage's output and a later scan or restart retries it
- Permanent errors (the file itself is unreadable, a decoder hangs past 300s)
  raise `PermanentStageError` and are recorded in `stage_failures`. Scans,
  resume and the workers all skip a stage with a recorded failure, so a broken
  file is not retried forever. The pipeline page lists them
  (`/api/pipeline/failures`); rebuilding a stage (`/api/scan/clear-stage/...`)
  clears its records and retries everything.

### Migration Strategy

The index is never dropped and rebuilt for a schema change: it holds weeks of
face detection and captioning (see "The index is precious").

- Schema changes are additive only: new tables, new nullable or defaulted
  columns, new indexes. Never rename, drop or retype a column.
- `init_db()` in `backend/app/database.py` applies them idempotently on every
  startup: `create_all()` creates missing tables, `_ADDED_COLUMNS` adds columns
  that older indexes lack, `_ADDED_INDEXES` creates indexes with
  `CREATE INDEX IF NOT EXISTS`.
- `backend/tests/unit/test_schema.py` pins the live schema
  (`schema_baseline.sql`); update the baseline and the test's list of added
  indexes together with any schema change, deliberately.

### Photo Visibility

**Photos are ALWAYS visible**, regardless of processing state:
- Timeline shows photos sorted by `file_modified` (filesystem date)
- If `date_taken` is available (EXIF extracted), use that instead
- Processing stages add richness (captions, faces, locations) but don't gate visibility

---

## Database Consistency

### Why This Matters

The app indexes photos from the filesystem into a SQLite database. If these get out of sync:
- **Missing photos**: Users won't see recent photos (e.g., 2024-2026 photos missing)
- **Orphaned records**: DB has photos that no longer exist on disk
- **Wrong totals**: Dashboard shows wrong counts

This has happened before when:
- New year folders were added but scan wasn't run
- Scanner was interrupted during indexing
- Container was rebuilt before scan completed

### Consistency Test

Run this to check if DB matches filesystem:

```bash
# Inside container
docker exec -it recasa-recasa-1 python -m backend.tests.test_consistency

# Or via pytest
docker exec -it recasa-recasa-1 pytest backend/tests/test_consistency.py -v
```

**What it checks:**
1. All year folders on disk have corresponding photos in DB
2. Total photo counts are within 5% tolerance
3. Newest photo year is recent (within 1 year of current date)

**If it fails:**
```
⚠️  Years with photos MISSING from DB: ['2024', '2025', '2026']
```

Run a rescan:
```bash
curl -X POST http://localhost:7000/api/scan/trigger
```

### Scanner Behavior

The scanner (`backend/app/services/scanner.py`) has safeguards:

1. **Skips corrupted files**: Files < 1KB or unopenable by PIL are skipped
2. **Idempotent**: Running multiple times is safe - unchanged files are skipped
3. **Resumable**: Interrupted scans can be resumed
4. **Library paths only**: `is_library_path()` excludes every path with a
   component starting with `.` (Syncthing's `.stversions`, NAS thumbnail
   caches, macOS `._` files) and Syncthing temp files. The sweep, the file
   watcher and cleanup share it; an indexed path that fails it is removed like
   a deleted file.
5. **Stays inside /photos**: symlinked directories are never descended into,
   and a symlinked file is only indexed when it resolves inside the library.
6. **Refuses to empty the index**: cleanup does nothing when the library is
   unreadable or a sweep finds no photos at all (see docs/RASPBERRY-PI.md).
7. **In-place edits replace the old version**: a file whose content changed
   is indexed under its new hash, and the old hash loses that path. An old
   version with no other copy left is removed like a deleted file; its
   favourite, print and flag marks move to the new version.
8. **Self-repairing primary path**: a photo whose `file_path` is not one of
   its own `photo_paths` (left by older code after a move) is pointed at its
   first remaining path, and its "file not found / cannot read (OSError)"
   stage failures are cleared so those stages run once more.

### Common Issues

| Issue | Cause | Fix |
|-------|-------|-----|
| Missing recent years | Scan not run after adding folders | Trigger rescan |
| Gray tiles in timeline | Corrupted images indexed | Scanner now skips < 1KB files; delete from DB |
| Photos appearing first with wrong date | Corrupted files with filesystem date | Already fixed in scanner |
| DB shows more photos than disk | Files deleted but not cleaned up | Scanner cleans up missing files |

### Adding New Photos

For new folders (e.g., copying from phone):
1. Copy photos to `PHOTOS_DIR`
2. Trigger rescan or wait for file watcher
3. Verify with consistency test

---

## Performance Notes

### Docker build

The Dockerfile has three stages: the frontend build, a Python dependency
stage with the compiler toolchain (insightface compiles from source on arm64),
and a slim runtime that copies the dependency venv. A backend-only change
re-copies `backend/` and nothing else; a frontend change re-runs only the npm
build; only a `pyproject.toml` change re-installs dependencies.

### Keeping the API responsive

The API and the pipeline share one event loop. Anything CPU-bound or blocking
(image decoding, face detection, DBSCAN clustering, event clustering,
duplicate comparison, directory walks) runs in a thread, never inline in async
code. SQLite is tuned per connection in `database.py` (WAL, mmap, larger page
cache, in-memory temp storage); do not add `ANALYZE`, it changes the schema
and can change query plans.

### Known Issues

| Issue | Status | Fix Needed |
|-------|--------|------------|
| Scan blocks API | FIXED | BackgroundTasks in `/api/scan/trigger` |
| WebSocket 403 errors | WORKAROUND | Use HTTP polling |
| Thumbnail generation slow | OK | Normal, memory-intensive |
| Face detection slow | OK | Normal, CPU-intensive |

---

## File Watcher vs Scanner

The app has two mechanisms for detecting new photos:
1. **File watcher** (`watchdog`, inotify): indexes a new or renamed-into-place
   photo once it has been quiet for 3 seconds. inotify does not cross Docker
   bind mounts on Windows/macOS hosts, so there it never fires.
2. **Periodic sweep** (`WATCH_INTERVAL`, default 300s): walks the library,
   stats only files in directories whose mtime changed, indexes new and changed
   files and cleans up removed ones. A manual rescan (`POST /api/scan/trigger`)
   also re-checks every unchanged photo for missing stage output.

Both write through the same lock, so they cannot index the same file twice.

---

## What Was Fixed Today (2026-03-03)

1. **Pipeline page NaN** - Changed from queue sizes to "photos needing processing" based on DB
2. **Sidebar offline** - WebSocket getting 403, switched to HTTP polling  
3. **Events showing 0** - Added events to processing-stats API
4. **Corrupted photos indexed** - Scanner now skips files < 1KB and unopenable images
5. **Missing 2024-2026 photos** - Consistency test revealed 10K+ missing photos; rescan triggered
6. **Confusing UI metrics** - Changed to "Indexed Photos" / "Queued" / "Status"
7. **Scan API blocking** - Made `/api/scan/trigger` non-blocking with BackgroundTasks

---

## Running Tests

### Unit Tests

```bash
python -m pytest backend/tests/unit     # from the repo root; no Docker needed
```

They cover the stage rules, resume, workers, queues, the scanner and the
schema guard. See docs/TESTING.md.

### Consistency Test

```bash
# Inside container
docker exec -it recasa-recasa-1 python -m backend.tests.test_consistency

# Check specific years
docker exec -it recasa-recasa-1 python -c "
import asyncio
from backend.app.database import async_session
from backend.app.models import Photo
from backend.app.config import settings
from sqlalchemy import select, func
# ... count photos on disk vs in DB
"
```

### Expected Results

When all photos are indexed:
- Disk total ≈ DB total (within 5% tolerance)
- All years with photos on disk have entries in DB
- Newest year in DB is within 1 year of current date