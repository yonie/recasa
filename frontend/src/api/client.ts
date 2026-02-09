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

export interface PhotoDetail extends PhotoSummary {
  file_modified: string | null;
  location: PhotoLocation | null;
  exif: PhotoExif | null;
  faces: FaceSummary[];
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
}

export interface QueueStats {
  queue_type: string;
  pending: number;
  processing: number;
  completed_total: number;
  skipped_total: number;
  failed_total: number;
  last_processed_at: string | null;
  last_file_hash: string | null;
  current_file_hash: string | null;
  current_file_path: string | null;
  throughput_per_minute: number;
}

export interface PipelineStats {
  is_running: boolean;
  status: "idle" | "processing" | "done";
  total_files_discovered: number;
  total_files_completed: number;
  start_time: string | null;
  uptime_seconds: number;
  bottleneck: { queue_type: string | null; ratio: number };
  queues: Record<string, QueueStats>;
  flow: Record<string, string[]>;
}

export interface LibraryStats {
  total_photos: number;
  total_size_bytes: number;
  total_faces: number;
  total_persons: number;
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

export interface EventSummary {
  event_id: number;
  name: string | null;
  start_date: string | null;
  end_date: string | null;
  location: string | null;
  photo_count: number;
  cover_photo: PhotoSummary | null;
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
  clearIndex: () => request<{ status: string }>("/scan/clear-index", { method: "POST" }),

  // Pipeline
  getPipelineStatus: () => request<PipelineStats>("/pipeline/status"),
  getQueueStatus: () => request<Record<string, QueueStats>>("/pipeline/queues"),
  getPipelineFlow: () => request<{ stages: { id: string; name: string; next: string[] }[] }>("/pipeline/flow"),

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

  getLocationPhotos: (params?: Record<string, string | number>) =>
    request<PhotoPage>(`/locations/photos${buildQuery(params)}`),

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
