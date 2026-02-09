from datetime import datetime

from pydantic import BaseModel


class PhotoBase(BaseModel):
    file_hash: str
    file_path: str
    file_name: str
    file_size: int
    mime_type: str | None = None
    width: int | None = None
    height: int | None = None
    date_taken: datetime | None = None
    is_favorite: bool = False


class PhotoSummary(PhotoBase):
    """Minimal photo data for grid views."""

    thumbnail_url: str | None = None
    has_live_photo: bool = False
    caption: str | None = None

    model_config = {"from_attributes": True}


class PhotoLocation(BaseModel):
    latitude: float | None = None
    longitude: float | None = None
    altitude: float | None = None
    country: str | None = None
    city: str | None = None
    address: str | None = None


class PhotoExif(BaseModel):
    camera_make: str | None = None
    camera_model: str | None = None
    lens_model: str | None = None
    focal_length: float | None = None
    aperture: float | None = None
    shutter_speed: str | None = None
    iso: int | None = None
    orientation: int | None = None


class FaceSummary(BaseModel):
    face_id: int
    person_id: int | None = None
    person_name: str | None = None
    bbox_x: int | None = None
    bbox_y: int | None = None
    bbox_w: int | None = None
    bbox_h: int | None = None

    model_config = {"from_attributes": True}


class PhotoDetail(PhotoBase):
    """Full photo data for detail view."""

    file_modified: datetime | None = None
    location: PhotoLocation | None = None
    exif: PhotoExif | None = None
    faces: list[FaceSummary] = []
    caption: str | None = None
    live_photo_video: str | None = None
    motion_photo: bool = False
    thumbnail_url: str | None = None
    indexed_at: datetime | None = None

    model_config = {"from_attributes": True}


class PhotoPage(BaseModel):
    """Paginated list of photos."""

    items: list[PhotoSummary]
    total: int
    page: int
    page_size: int
    has_more: bool


class TimelineGroup(BaseModel):
    """Photos grouped by date."""

    date: str  # ISO date string (year, year-month, or full date)
    count: int
    photos: list[PhotoSummary] = []


class DirectoryNode(BaseModel):
    """A node in the directory tree."""

    name: str
    path: str
    photo_count: int = 0
    children: list["DirectoryNode"] = []


class PersonSummary(BaseModel):
    person_id: int
    name: str | None = None
    photo_count: int = 0
    face_thumbnail_url: str | None = None

    model_config = {"from_attributes": True}


class PersonUpdate(BaseModel):
    name: str


class PersonMerge(BaseModel):
    source_id: int
    target_id: int


class EventSummary(BaseModel):
    event_id: int
    name: str | None = None
    start_date: datetime | None = None
    end_date: datetime | None = None
    location: str | None = None
    photo_count: int = 0
    cover_photo: PhotoSummary | None = None

    model_config = {"from_attributes": True}


class DuplicateGroupSummary(BaseModel):
    group_id: int
    photos: list[PhotoSummary] = []


class ScanStatus(BaseModel):
    is_scanning: bool = False
    total_files: int = 0
    processed_files: int = 0
    current_file: str | None = None
    phase: str | None = None  # "discovery", "exif", "geocoding", "thumbnails", "motion_photos", "hashing", "faces", "captioning", "events"
    phase_progress: int = 0
    phase_total: int = 0


class LibraryStats(BaseModel):
    total_photos: int = 0
    total_size_bytes: int = 0
    total_faces: int = 0
    total_persons: int = 0
    total_events: int = 0
    total_duplicates: int = 0
    oldest_photo: datetime | None = None
    newest_photo: datetime | None = None
    locations_count: int = 0
    favorites_count: int = 0
