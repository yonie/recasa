# Testing Guide

Recasa has three test suites:

- **Unit tests** (`backend/tests/unit/`): the pipeline's decision logic,
  scanner, queues, schema migrations and media helpers, against temp dirs and
  a throwaway SQLite index. No Docker, network or ML models.
- **Integration tests** (`backend/tests/test_*.py`): the full pipeline in
  Docker against fixture images.
- **Frontend tests** (`frontend/tests/`): Playwright against a running instance.

## Unit tests

From the repository root, with the backend dependencies installed:

```bash
python -m pytest backend/tests/unit
```

`test_schema.py` checks that startup migrations never change the schema of an
existing index: `schema_baseline.sql` is the live index's `sqlite_master`
(`SELECT sql || ';' FROM sqlite_master WHERE sql IS NOT NULL ORDER BY sql`),
and the only allowed difference is the indexes listed in the test. To also
run it against a copy of a real index (it is copied, never opened in place):

```bash
RECASA_PRISTINE_DB=/path/to/copy/of/recasa.db python -m pytest backend/tests/unit/test_schema.py
```

## Integration tests

### Overview

Recasa includes a comprehensive integration test suite that validates the complete photo processing pipeline:

- **Scanner** - Photo indexing and discovery
- **EXIF Extraction** - Camera metadata and GPS coordinates
- **Geocoding** - City name resolution from GPS
- **Thumbnails** - Multi-size thumbnail generation
- **Hashing** - Perceptual hash computation for duplicate detection
- **Faces** - Face detection and person clustering
- **Captioning** - AI-generated captions and tags

Tests run against a Docker container with built-in fixture images, requiring no external dependencies.

### Quick Start

```bash
# Run the full test suite (autonomous)
docker-compose -f docker-compose.test.yml up --build --abort-on-container-exit

# Check exit code
echo $?  # 0 = pass, 1 = fail
```

This command:
1. Builds the Docker image with test configuration
2. Starts the app container with test fixtures mounted
3. Waits for the app to be healthy
4. Runs the integration tests (`backend/tests/test_*.py`) inside the tester
   container: it clears the index, scans the fixtures and waits until no scan
   runs and every stage queue is empty (`PIPELINE_TIMEOUT`, default 900s)
5. Exits with code 0 (success) or 1 (failure)

The tester skips `tests/unit/` (run those without Docker, see above) and
`test_consistency.py` (it compares a real library with its index, from inside
the app container).

Two tests depend on services outside the container:

- **Captioning** (`test_captioning.py::test_captions_generated`,
  `test_pipeline.py::test_captioning`) needs a vision model in Ollama. Set
  `OLLAMA_URL` and `OLLAMA_MODEL` for the run, for example
  `OLLAMA_URL=http://192.168.1.170:11434 OLLAMA_MODEL=qwen3.8:latest`. With
  Ollama unreachable no caption is stored and these two fail.
- **Face detection** (`test_faces.py::test_faces_detected`,
  `test_pipeline.py::test_face_detection`) loads the insightface model, which
  is downloaded on first use and kept in the test data volume.

## Test Data

Test fixtures are located in `backend/tests/fixtures/images/`:

| Directory | Files | Purpose |
|-----------|-------|---------|
| `faces/alice/` | 2 | Same person, multiple angles (clustering test) |
| `faces/bob/` | 2 | Same person, multiple angles |
| `faces/carol/` | 2 | Same person, multiple angles |
| `faces/group/` | 1 | Multiple people in one photo |
| `landscapes/` | 1 | Nature photo (no faces) |
| `portraits/` | 1 | Single-person portrait |
| `formats/` | 3 | Other formats (HEIC, WebP, PNG) |

**Total: 12 test images** (all listed in `manifest.json`)

### Adding Test Images

Test images are committed to the repository. To add new images:

1. Place images in the appropriate subdirectory under `backend/tests/fixtures/images/`
2. Update `backend/tests/fixtures/manifest.json` with expected attributes
3. Re-run tests

### Downloading Images

Run the download script to fetch CC0/public domain images:

```bash
# Inside the container or with dependencies installed
cd backend/tests/fixtures
python download_fixtures.py
```

This downloads images from:
- **Unsplash** - CC0 licensed portraits, landscapes, city photos
- **Wikimedia Commons** - Public domain historical figures

## Test Configuration

The test configuration is in `docker-compose.test.yml`:

```yaml
environment:
  - OLLAMA_URL=${OLLAMA_URL:-http://host.docker.internal:11434}
  - OLLAMA_MODEL=${OLLAMA_MODEL:-qwen3-vl:235b-instruct-cloud}
  - ENABLE_GEOCODING=true
  - ENABLE_FACE_DETECTION=true
  - ENABLE_CAPTIONING=true
  - MAX_CONCURRENT=2
```

Every stage is enabled (EXIF, thumbnails, motion photos and hashing always run).

## Running Specific Tests

The integration tests only need the API, so they also run from a checkout
against any instance with the fixtures as its library:

```bash
# from backend/, with pytest, pytest-asyncio and httpx installed
BASE_URL=http://localhost:7001 python -m pytest tests --ignore=tests/unit \
    --ignore=tests/test_consistency.py -v

# one file or one test
BASE_URL=http://localhost:7001 python -m pytest tests/test_exif.py -v
BASE_URL=http://localhost:7001 python -m pytest \
    tests/test_pipeline.py::TestPipelineIntegration::test_exif_extraction -v
```

Do not point them at an instance with a real library: the session setup
clears the index.

## Test Stages

### Scanner Tests (`test_scanner.py`)

Validates that:
- Photos are correctly indexed from the filesystem
- File hashes are computed
- MIME types are detected
- File sizes are recorded

### EXIF Tests (`test_exif.py`)

Validates that:
- Camera make/model extracted
- Date taken parsed correctly
- GPS coordinates valid (lat/lng ranges)
- Photos without EXIF handled gracefully

### Geocoding Tests (`test_geocoding.py`)

Validates that:
- GPS coordinates resolve to city names
- Country codes populated
- Location data format correct

### Thumbnail Tests (`test_thumbnails.py`)

Validates that:
- Thumbnails generated at 200/600/1200px
- Files exist on disk
- Processing stats accurate

### Hashing Tests (`test_hashing.py`)

Validates that:
- Perceptual hashes computed
- Hash values non-empty

### Face Tests (`test_faces.py`)

Validates that:
- Faces detected in portraits
- Multiple faces detected in group photos
- No false positives in landscapes
- Face bounding boxes valid
- Person clustering works (same person grouped)

### Captioning Tests (`test_captioning.py`)

Validates that:
- AI captions generated
- Tags extracted
- Captions contain relevant keywords
- Model name recorded

## Test Manifest

Test expectations are defined in `backend/tests/fixtures/manifest.json`:

```json
{
  "images": [
    {
      "filename": "faces/alice/alice_01.jpg",
      "category": "faces",
      "exif": {"has_exif": true, "camera_make": "Canon"},
      "gps": {"has_gps": true, "expected_city": "Amsterdam"},
      "faces": {"min_faces": 1, "expected_person": "alice"},
      "caption_keywords": ["portrait", "woman", "outdoor"]
    }
  ]
}
```

Each image specifies:
- **category**: Type of image for filtering tests
- **exif**: Expected EXIF data presence
- **gps**: Whether GPS data exists and expected city
- **faces**: Minimum faces expected and person ID for clustering
- **caption_keywords**: Keywords that should appear in AI caption

## Demo Mode

The test fixtures also serve as demo data for new users:

```bash
# Start with test data for demo
docker-compose -f docker-compose.test.yml up

# Access the app
open http://localhost:7001
```

This shows the app with the fixture images: portraits, a group photo, a landscape and a few other formats.

## Troubleshooting

### Tests fail with "API did not become ready"

The app container may take longer to start. Increase timeout:

```bash
# In conftest.py, adjust wait_for_ready timeout
await client.wait_for_ready(max_seconds=180)  # Default is 120
```

### Captioning tests fail

Ensure Ollama is running and accessible:

```bash
# Check Ollama status
curl http://localhost:11434/api/tags

# If using Docker, ensure host.docker.internal resolves
docker-compose -f docker-compose.test.yml exec app curl http://host.docker.internal:11434/api/tags
```

### Face detection tests fail

`test_faces.py` reads `faces_found` from `/api/pipeline/processing-stats`:
at least one fixture must have a detected face, and not all of them (the
landscape and the format samples have none). `completed` is not used: it
counts every photo face detection looked at, faces or not.

### Tests hang

Captioning dominates the run, one model round trip per photo. Give the
pipeline longer with `PIPELINE_TIMEOUT` (seconds) in the tester's
environment; on timeout the failure lists what is still in each stage.

## Frontend (Playwright) tests

Browser tests live in `frontend/tests/` and run against a *running* instance on
`localhost:7000`; they do not start the app themselves.

```bash
cd frontend

# Run serially. See the caveat below before using the default worker count.
npx playwright test --project=chromium --workers=1

# Safari/WebKit, which matters for HEIC and for iOS scroll behaviour
npx playwright test --config=playwright.webkit.config.ts
```

### Run them with `--workers=1`

`playwright.config.ts` sets `workers: 4`, but on a large library the backend
cannot serve four concurrent browser contexts and tests fail on timeouts
unrelated to whatever they are testing.

If a run has already left the backend struggling, restart before the next one:

```bash
docker compose restart recasa
```

### Some tests require an idle pipeline

Most of `pipeline.spec.ts` is gated on `waitForPipelineComplete`, so those tests
cannot pass while a scan is running, and with `WATCH_INTERVAL` at its default a
scan runs often.

Because of that, a failure here is often environmental rather than a real
regression. Get a baseline before concluding otherwise: stash the change,
rebuild the frontend, and run the same tests. Failures present in both runs are
not caused by the change.

### Prefer bounded queries when writing tests

Tests that need a photo grid should drive it from a route backed by a paged
query (`/search?q=...`, `/to-print`, `/favorites`, all `api.getPhotos`, ~10ms)
rather than the home timeline, which is the one endpoint that stalls under
load. `viewer-swap.spec.ts` does this.

Two other traps worth knowing:

- **Previews are served immutable**, so a prefetched image is answered from
  cache and a `page.route()` added *after* navigation never sees the request.
  Install interception before the first `goto`.
- **Several synthesised `keydown` events in one tick collapse into a single
  navigation**, because the handler closes over the current index until React
  re-renders. Use `keyboard.press()`, which dispatches across tasks, when you
  mean several steps.

## Continuous Integration

For CI pipelines:

```yaml
# Example GitHub Actions
- name: Run Tests
  run: |
    docker-compose -f docker-compose.test.yml up --build --abort-on-container-exit
    exit_code=$?
    docker-compose -f docker-compose.test.yml down -v
    exit $exit_code
```

## Architecture

The test suite uses a two-container architecture:

```
┌──────────────────────────────────────────────────────────────────────┐
│                     docker-compose.test.yml                           │
├──────────────────────────────────────────────────────────────────────┤
│                                                                       │
│   ┌─────────────────┐         ┌─────────────────┐                    │
│   │    app          │  :8000  │    tester        │                    │
│   │                 │◄───────►│                  │                    │
│   │ FastAPI server  │  http   │ pytest runner    │                    │
│   │                 │         │ validates API    │                    │
│   └────────┬────────┘         └────────┬─────────┘                    │
│            │                           │                              │
│            │  /photos:ro               │  /tests:ro                   │
│            │                           │                              │
│   ┌────────┴────────────────────────────┴─────────────────────────────┐
│   │            recasa_test_data (shared volume)                       │
│   │         Database, thumbnails, faces, etc.                        │
│   └───────────────────────────────────────────────────────────────────┘
│                                                                       │
└──────────────────────────────────────────────────────────────────────┘
```

- **app**: Runs the Recasa application
- **tester**: Runs pytest, validates API responses
- Both share the same data volume for database consistency