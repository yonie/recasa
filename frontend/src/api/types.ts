/** Response shapes of the Recasa API, as the frontend uses them. */

export interface PhotoSummary {
  file_hash: string;
  file_path: string;
  file_name: string;
  file_size: number;
  mime_type: string | null;
  width: number | null;
  height: number | null;
  date_taken: string | null;
  is_favorite: boolean;
  marked_for_print: boolean;
  flagged_for_removal: boolean;
  is_video: boolean;
  duration: number | null;
  thumbnail_url: string | null;
  has_live_photo: boolean;
  caption: string | null;
}

export interface PhotoLocation {
  latitude: number | null;
  longitude: number | null;
  altitude: number | null;
  country: string | null;
  city: string | null;
  address: string | null;
}

export interface PhotoExif {
  camera_make: string | null;
  camera_model: string | null;
  lens_model: string | null;
  focal_length: number | null;
  aperture: number | null;
  shutter_speed: string | null;
  iso: number | null;
  orientation: number | null;
}

export interface FaceSummary {
  face_id: number;
  person_id: number | null;
  person_name: string | null;
  bbox_x: number | null;
  bbox_y: number | null;
  bbox_w: number | null;
  bbox_h: number | null;
}

export interface TagRef {
  tag_id: number;
  name: string;
  category: string | null;
}

export interface TagCount extends TagRef {
  count: number;
}

export interface TagList {
  items: TagCount[];
  total: number;
}

export interface PhotoDetail extends PhotoSummary {
  file_modified: string | null;
  location: PhotoLocation | null;
  exif: PhotoExif | null;
  faces: FaceSummary[];
  tags: TagRef[];
  caption: string | null;
  live_photo_video: string | null;
  motion_photo: boolean;
  indexed_at: string | null;
}

export interface PhotoPage {
  items: PhotoSummary[];
  total: number;
  page: number;
  page_size: number;
  has_more: boolean;
}

export interface DirectoryNode {
  name: string;
  path: string;
  photo_count: number;
  children: DirectoryNode[];
}

export interface TimelineGroup {
  date: string;
  count: number;
  photos: PhotoSummary[];
}

export interface YearCount {
  year: number;
  count: number;
  previews: string[];
}

export interface QueueStats {
  queue_type: string;
  pending: number;
  processing: number;
  current_file_hash: string | null;
  current_file_path: string | null;
}

export interface StageStats {
  status: string;
  queued: number;
  completed: number;
  total: number;
  enabled: boolean;
  failed: number;
  faces_found?: number;
  captions_generated?: number;
  count?: number;
}

/** Pipeline stages in display order; also the keys of ProcessingStats.stages. */
export const STAGES = [
  "discovery",
  "exif",
  "geocoding",
  "thumbnails",
  "motion_photos",
  "hashing",
  "faces",
  "captioning",
  "events",
] as const;

export type StageName = (typeof STAGES)[number];

export interface ProcessingStats {
  total_photos: number;
  total_videos: number;
  // Partial: a stage the backend does not report renders as an empty row.
  stages: Partial<Record<StageName, StageStats>>;
}

export interface StageFailureItem {
  file_hash: string;
  file_path: string;
  file_name: string;
  stage: string;
  error: string | null;
  failed_at: string | null;
}

export interface WatcherStatus {
  inotify_active: boolean;
  sweep_interval: number;
  last_scan_at: string | null;
  last_scan_stats: { total: number; new: number; updated: number; errors: number } | null;
}

export interface PipelineStats {
  state: "idle" | "scanning" | "processing" | "done";
  watcher?: WatcherStatus;
  scan_progress: {
    is_scanning: boolean;
    total_files: number;
    scanned_files: number;
    current_directory: string | null;
    discovery_phase: string | null;
    discovery_files_collected: number;
  } | null;
  processing_progress: {
    files_queued: number;
    files_processing: number;
    elapsed_seconds: number;
  } | null;
  completion_summary: {
    files_processed: number;
    elapsed_seconds: number;
    completed_at: string | null;
    scan_stats: {
      total: number;
      new: number;
      updated: number;
      skipped: number;
      fully_processed: number;
      errors: number;
    } | null;
  } | null;
  error_log: Array<{
    timestamp: string;
    queue: string;
    file_hash: string;
    file_path: string | null;
    error: string;
  }>;
  error_count: number;
  queues: Record<string, QueueStats>;
}

export interface LibraryStats {
  total_photos: number;
  total_size_bytes: number;
  total_faces: number;
  total_persons: number;
  total_tags: number;
  total_events: number;
  total_duplicates: number;
  oldest_photo: string | null;
  newest_photo: string | null;
  locations_count: number;
  favorites_count: number;
  to_print_count: number;
  flagged_count: number;
  videos_count: number;
}

export interface DuplicatePhotoSummary extends PhotoSummary {
  location: string | null;
  camera: string | null;
  people: string[];
}

export interface DuplicateGroup {
  group_id: number;
  photos: DuplicatePhotoSummary[];
}

export interface PersonSummary {
  person_id: number;
  name: string | null;
  photo_count: number;
  face_thumbnail_url: string | null;
}

export interface PersonGroup {
  persons: PersonSummary[];
  shared_photo_count: number;
  cover_photo: PhotoSummary | null;
}

export interface HiddenGroup {
  group_key: string;
  persons: PersonSummary[];
}

export interface EventSummary {
  event_id: number;
  name: string | null;
  start_date: string | null;
  end_date: string | null;
  location: string | null;
  photo_count: number;
  cover_photo: PhotoSummary | null;
  summary: string | null;
}

export interface CountryCount {
  country: string;
  count: number;
}

export interface CityCount {
  city: string;
  country: string;
  count: number;
}

export interface MapPoint {
  latitude: number;
  longitude: number;
  count: number;
  representative_hash: string;
  city: string | null;
  country: string | null;
  thumbnail_url: string;
}

export interface TrailPhoto {
  file_hash: string;
  thumbnail_url: string;
}

export interface TrailStop {
  date: string;
  latitude: number;
  longitude: number;
  city: string | null;
  country: string | null;
  photos: TrailPhoto[];
  total_count: number;
}

export interface UserDataImportResult {
  status: "ok" | "error";
  message?: string;
  favorites_restored?: number;
  persons_restored?: number;
  persons_pending?: number;
  hidden_groups_restored?: number;
  hidden_groups_pending?: number;
}
