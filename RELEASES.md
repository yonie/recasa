# Releases

## v1.4.0 - Hero Trail & UX Polish

### New Features

- **Hero Trail** -- animated journey mode on the map view. Replays your route through geotagged photos chronologically, with a date picker to jump to any point. Press the footprints icon to start.
- **Grid size button** -- replaced the S/M/L header toggle with a round cycling button (bottom-right corner) for cleaner UI.

### Improvements

- Tightened face clustering threshold (0.5 to 0.3 cosine distance) for fewer false matches
- Fixed face clustering creating duplicate persons for the same face
- Fixed live photo hover showing gray tile on video load failure
- Stricter face detection with per-stage pipeline clearing
- Better z-index layering for map overlays

## v1.3.0 - Events, Together Albums & People Improvements

### New Features

- **Smart event covers** -- events now select landscape-oriented photos with centered faces as cover images
- **Together albums** -- automatically finds and groups people who frequently appear in the same photos
- **Ignore faces** -- you can now ignore/unignore people in the People browser

### Improvements

- People page loads progressively instead of all at once
- Together display and event cover selection improvements
- Logo is now clickable (navigates home)

## v1.2.0 - Caching & Architecture Overhaul

### New Features

- **API caching** -- all immutable endpoints now return proper cache headers
- **Smart event detection** -- clusters photos by time proximity and location into named events

### Improvements

- Unified pipeline status with clear state machine
- Per-stage skip logic (doesn't reprocess stages that already completed)
- Auto-resume on startup for interrupted scans
- Stricter face detection and logging

## v1.1.0 - Face Detection & Pipeline Improvements

### New Features

- **Face detection and clustering** -- insightface-based detection with 512-dim encodings + DBSCAN clustering into named people
- **Pipeline status UI** -- real-time processing progress with stage indicators

### Improvements

- Show full numbers instead of abbreviated format (21,860 not 21.9K)
- Skip corrupted/invalid images during scan (< 1KB or unopenable)
- Fix HEIC EXIF extraction using getexif() instead of _getexif()
- Non-blocking scan endpoint using BackgroundTasks
- Consistency test for DB vs filesystem verification

## v1.0.0 - Initial Release

Core photo browsing features:
- Timeline, Folders, Years views
- EXIF metadata extraction
- Reverse geocoding (offline)
- Locations browser and map view
- Full-text search
- AI captioning via Ollama
- Duplicate detection (perceptual hashing)
- Favorites
- Live Photos (Apple + Google)
- File watching for real-time new photo detection
- Deep linking and scroll restoration