/**
 * API client for the Recasa backend.
 */

const BASE_URL = "/api";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE_URL}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...options?.headers,
    },
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(error.detail || `HTTP ${response.status}`);
  }

  return response.json();
}

// Types

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

export interface TagCount {
  tag_id: number;
  name: string;
  category: string | null;
  count: number;
}

export interface PhotoDetail extends PhotoSummary {
  file_modified: string | null;
  location: PhotoLocation | null;
  exif: PhotoExif | null;
  faces: FaceSummary[];
  tags: { tag_id: number; name: string; category: string | null }[];
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
}

export interface ScanStatus {
  is_scanning: boolean;
  total_files: number;
  processed_files: number;
  current_file: string | null;
  phase: string | null;
  phase_progress: number;
  phase_total: number;
  discovery_phase: string | null;
  discovery_files_collected: number;
}

export interface QueueStats {
  queue_type: string;
  pending: number;
  processing: number;
  current_file_hash: string | null;
  current_file_path: string | null;
}

export interface ProcessingStats {
  total_photos: number;
  stages: {
    discovery: { status: string; queued: number; completed: number; total: number; enabled: boolean };
    exif: { status: string; queued: number; completed: number; total: number; enabled: boolean };
    geocoding: { status: string; queued: number; completed: number; total: number; enabled: boolean };
    thumbnails: { status: string; queued: number; completed: number; total: number; enabled: boolean };
    motion_photos: { status: string; queued: number; completed: number; total: number; enabled: boolean };
    hashing: { status: string; queued: number; completed: number; total: number; enabled: boolean };
    faces: { status: string; queued: number; completed: number; total: number; enabled: boolean; faces_found?: number };
    captioning: { status: string; queued: number; completed: number; total: number; enabled: boolean };
    events: { status: string; queued: number; completed: number; total: number; enabled: boolean; count?: number };
  };
}

export interface PipelineStats {
  state: "idle" | "scanning" | "processing" | "done";
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
}

export interface DuplicateGroup {
  group_id: number;
  photos: PhotoSummary[];
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

// API functions

function buildQuery(params?: Record<string, string | number | boolean>): string {
  if (!params) return "";
  const searchParams = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null) {
      searchParams.set(key, String(value));
    }
  }
  const query = searchParams.toString();
  return query ? `?${query}` : "";
}

export const api = {
  // Photos
  getPhotos: (params?: Record<string, string | number | boolean>) =>
    request<PhotoPage>(`/photos${buildQuery(params)}`),

  getPhoto: (hash: string) => request<PhotoDetail>(`/photos/${hash}`),

  toggleFavorite: (hash: string) =>
    request<{ file_hash: string; is_favorite: boolean }>(`/photos/${hash}/favorite`, {
      method: "POST",
    }),

  getStats: () => request<LibraryStats>("/photos/stats"),

  // Directories
  getDirectoryTree: () => request<DirectoryNode[]>("/directories"),

  getDirectoryPhotos: (path: string, params?: Record<string, string | number>) =>
    request<PhotoPage>(`/directories/${path}${buildQuery(params)}`),

  // Timeline
  getYears: () => request<YearCount[]>("/timeline/years"),

  getTimeline: (params?: Record<string, string | number>) =>
    request<TimelineGroup[]>(`/timeline${buildQuery(params)}`),

  // Scan
  getScanStatus: () => request<ScanStatus>("/scan/status"),
  triggerScan: () => request<{ status: string }>("/scan/trigger", { method: "POST" }),
  stopPipeline: () => request<{ status: string }>("/scan/stop", { method: "POST" }),
  clearIndex: () => request<{ status: string }>("/scan/clear-index", { method: "POST" }),
  clearStage: (stage: string) => request<{ status: string }>(`/scan/clear-stage/${stage}`, { method: "POST" }),

  // Pipeline
  getPipelineStatus: () => request<PipelineStats>("/pipeline/status"),
  getProcessingStats: () => request<ProcessingStats>("/pipeline/processing-stats"),
  getQueueStatus: () => request<Record<string, QueueStats>>("/pipeline/queues"),
  getPipelineFlow: () => request<{ stages: { id: string; name: string; next: string[] }[] }>("/pipeline/flow"),
  getPipelineLogs: () => request<Array<{ timestamp: string; level: string; message: string }>>("/pipeline/logs"),

  // Duplicates
  getDuplicates: (params?: Record<string, string | number>) =>
    request<DuplicateGroup[]>(`/duplicates${buildQuery(params)}`),

  // Large files
  getLargeFiles: (params?: Record<string, string | number>) =>
    request<PhotoPage>(`/large-files${buildQuery(params)}`),

  // Persons
  getPersons: (params?: Record<string, string | number>) =>
    request<PersonSummary[]>(`/persons${buildQuery(params)}`),

  getPerson: (id: number) => request<PersonSummary>(`/persons/${id}`),

  getPersonPhotos: (id: number, params?: Record<string, string | number>) =>
    request<PhotoPage>(`/persons/${id}/photos${buildQuery(params)}`),

  updatePerson: (id: number, name: string) =>
    request<PersonSummary>(`/persons/${id}`, {
      method: "PUT",
      body: JSON.stringify({ name }),
    }),

  mergePersons: (sourceId: number, targetId: number) =>
    request<{ status: string; target_id: number; faces_moved: number }>("/persons/merge", {
      method: "POST",
      body: JSON.stringify({ source_id: sourceId, target_id: targetId }),
    }),

  ignorePerson: (id: number) =>
    request<{ status: string }>(`/persons/${id}/ignore`, { method: "POST" }),

  unignorePerson: (id: number) =>
    request<{ status: string }>(`/persons/${id}/unignore`, { method: "POST" }),

  getIgnoredPersons: () =>
    request<PersonSummary[]>("/persons/ignored"),

  getPersonGroups: (params?: Record<string, string | number>) =>
    request<PersonGroup[]>(`/persons/groups/together${buildQuery(params)}`),

  getSharedPhotos: (personAId: number, personBId: number, params?: Record<string, string | number>) =>
    request<PhotoPage>(`/persons/groups/together/${personAId}/${personBId}/photos${buildQuery(params)}`),

  // Events
  getEvents: (params?: Record<string, string | number>) =>
    request<EventSummary[]>(`/events${buildQuery(params)}`),

  getEvent: (id: number) => request<EventSummary>(`/events/${id}`),

  getEventPhotos: (id: number, params?: Record<string, string | number>) =>
    request<PhotoPage>(`/events/${id}/photos${buildQuery(params)}`),

  // Locations
  getCountries: () => request<CountryCount[]>("/locations/countries"),

  getCities: (country?: string) =>
    request<CityCount[]>(`/locations/cities${country ? `?country=${encodeURIComponent(country)}` : ""}`),

  getMapPoints: () => request<MapPoint[]>("/locations/map-points"),

  getTrail: (params?: { date_from?: string; date_to?: string }) =>
    request<TrailStop[]>(`/locations/trail${buildQuery(params)}`),

  getLocationPhotos: (params?: Record<string, string | number>) =>
    request<PhotoPage>(`/locations/photos${buildQuery(params)}`),

  // Tags
  getTags: () => request<TagCount[]>("/tags"),

  getTagPhotos: (tagId: number, params?: Record<string, string | number>) =>
    request<PhotoPage>(`/tags/${tagId}/photos${buildQuery(params)}`),

  // Health
  health: () => request<{ status: string; app: string; version: string }>("/health"),
};

// URL helpers
export function thumbnailUrl(hash: string, size: number = 600): string {
  return `${BASE_URL}/photos/${hash}/thumbnail/${size}`;
}

export function originalUrl(hash: string): string {
  return `${BASE_URL}/photos/${hash}/original`;
}

export function livePhotoUrl(hash: string): string {
  return `${BASE_URL}/photos/${hash}/live`;
}

export function personThumbnailUrl(personId: number): string {
  return `${BASE_URL}/persons/${personId}/thumbnail`;
}
