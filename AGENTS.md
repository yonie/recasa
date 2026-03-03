# Agent Guidelines for Recasa

## Running the Application

**This app runs in Docker.** Do not attempt to run backend/frontend directly with uvicorn/npm commands.

### Common Commands

```bash
# Build and start all services
docker-compose up --build

# View logs
docker-compose logs -f

# View specific service logs
docker-compose logs -f backend
docker-compose logs -f frontend

# Restart services
docker-compose restart

# Stop services
docker-compose down
```

### Architecture

- **Backend**: Python FastAPI app in `backend/`
- **Frontend**: React/Vite/TypeScript app in `frontend/`
- **Services**: Defined in `docker-compose.yml`

### Development Flow

1. Make code changes
2. Rebuild affected service: `docker-compose up --build backend` or `docker-compose up --build frontend`
3. Check logs for errors: `docker-compose logs -f backend`

### Testing

- Backend tests: `docker-compose exec backend pytest`
- Frontend tests: Located in `frontend/tests/` (Playwright)

---

## Design Philosophy

### Core Principle: No State Flags

**Photos are immutable.** Once a photo exists on disk with a specific hash, it never changes. Therefore:

1. **No boolean processing flags** in the Photo model (no `exif_extracted`, `thumbnail_generated`, etc.)
2. **Data existence IS the state** - if `camera_make` is populated, EXIF was extracted
3. **File existence IS the state** - if `thumbs/{hash}_200.jpg` exists, thumbnail is generated

### Processing Stages

Each stage is controlled by a config flag:

```
ENABLE_EXIF_EXTRACTION=true
ENABLE_GEOCODING=true
ENABLE_THUMBNAILS=true
ENABLE_MOTION_PHOTOS=true
ENABLE_HASHING=true
ENABLE_FACE_DETECTION=false
ENABLE_CAPTIONING=false
```

**Key behaviors:**
- Even with ALL stages disabled, photos are visible in the app (sorted by file_modified)
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

| Stage | "Output Exists?" Check |
|-------|----------------------|
| EXIF | `camera_make IS NOT NULL` OR `date_taken IS NOT NULL` |
| Geocoding | `location_city IS NOT NULL` |
| Thumbnails | File exists: `/data/thumbs/{file_hash}_200.jpg` |
| Motion Photos | DB field `motion_photo = true` (this is data, not a flag) |
| Hashing | Record exists in `photo_hashes` table for this file_hash |
| Faces | Record exists in `faces` table for this file_hash |
| Captioning | Record exists in `captions` table for this file_hash |

### Processing Flow

1. **Scan**: Walk filesystem, add photos to DB (minimal: hash, path, filename, size, file_modified)
2. **Queue**: For each photo, for each enabled stage, check if output exists. If not → queue for that stage
3. **Worker**: Pick `file_hash` from queue, check output existence again (idempotent), process if needed
4. **Flow**: After stage completes, photo proceeds to next stage in pipeline
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
- For each enabled stage, query photos missing that stage's output
- This handles crashes gracefully - processing resumes automatically
- No user action needed

### Error Handling

- Log errors per-photo when they happen (standard Python logging)
- No retry counters, no error queues, no complex state
- Failed photos simply don't have that stage's output - user can re-trigger scan to retry

### Migration Strategy

No migrations needed. When making schema changes:
- Drop the database and rebuild from scratch
- We are the only users of this app
- Keep it simple

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

## Performance Issues (NEEDS FIX)

### Docker Build is SLOW

Docker builds take 1-2 minutes even for minor changes because:
- No proper layer caching for Python dependencies
- Frontend rebuilds even when only backend changed
- `apt-get purge` runs on every build (should be in base image)

**Potential fixes:**
1. Split Dockerfile into base + app stages
2. Copy `pyproject.toml` and install deps BEFORE copying code
3. Only rebuild frontend when `frontend/` changes
4. Move `apt-get purge` to base image layer

### API Blocking Issues

The `/api/scan/trigger` endpoint is **blocking** - it runs the entire scan before returning. This means:
- Frontend hangs waiting for response
- Scan progress isn't visible
- timeouts on large photo libraries

**Fix:** Use BackgroundTasks to run scan async, return immediately with status.

### Known Issues

| Issue | Status | Fix Needed |
|-------|--------|------------|
| Scan blocks API | FIXED | BackgroundTasks in `/api/scan/trigger` |
| WebSocket 403 errors | WORKAROUND | Use HTTP polling |
| Thumbnail generation slow | OK | Normal, memory-intensive |
| Face detection slow | OK | Normal, CPU-intensive |

---

## Architecture Issues (TODO)

### Docker Build Performance

The Dockerfile rebuilds take 1-2 minutes because:
1. No layer caching for Python dependencies
2. `apt-get purge` runs on every build (should be in base layer)
3. Frontend rebuilds even when only backend changed

**Recommended fix:** Multi-stage Dockerfile with better layer caching.

### File Watcher vs Scanner

The app has two mechanisms for detecting new photos:
1. **File watcher** (`watchdog`) - Detects new files in real-time
2. **Scanner** - Walks filesystem on demand/trigger

Current state: File watcher runs but the scanner must be manually triggered for initial indexing or after adding many new folders. The watcher may miss directories added while the app was down.

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