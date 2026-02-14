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