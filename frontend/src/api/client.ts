/**
 * API client for the Recasa backend. Every request the app makes goes
 * through here, so endpoints and parameters live in one place.
 */

import type {
  CityCount,
  CountryCount,
  DirectoryNode,
  DuplicateGroup,
  EventSummary,
  HiddenGroup,
  LibraryStats,
  MapPoint,
  PersonGroup,
  PersonSummary,
  PhotoDetail,
  PhotoPage,
  PhotoSummary,
  PipelineStats,
  ProcessingStats,
  StageFailureItem,
  TagCount,
  TagList,
  TimelineGroup,
  TrailStop,
  UserDataImportResult,
  YearCount,
} from "./types";

export * from "./types";
export * from "./urls";

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

const post = <T>(path: string, body?: unknown) =>
  request<T>(path, {
    method: "POST",
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });

/** Fetch a binary response (collages, exports) from an absolute /api URL. */
export async function fetchBlob(url: string): Promise<Blob> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.blob();
}

/** Query string from the defined entries, in the order given. */
function buildQuery(params?: object): string {
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

// Query parameters, as the backend declares them

export interface PageParams {
  page?: number;
  page_size?: number;
}

export interface PhotoListParams extends PageParams {
  sort?: "date_taken" | "file_name" | "file_size" | "indexed_at";
  order?: "asc" | "desc";
  favorite?: boolean;
  marked_for_print?: boolean;
  flagged?: boolean;
  video?: boolean;
  search?: string;
}

export interface TimelineParams {
  year?: number;
  month?: number;
  video?: boolean;
  group_by?: "year" | "month" | "day";
  limit?: number;
  offset?: number;
}

export interface LocationPhotoParams extends PageParams {
  country?: string;
  city?: string;
}

export interface TrailParams {
  date_from?: string;
  date_to?: string;
}

type Toggle<K extends string> = { file_hash: string } & Record<K, boolean>;

export const api = {
  // Photos
  getPhotos: (params?: PhotoListParams) => request<PhotoPage>(`/photos${buildQuery(params)}`),
  getPhoto: (hash: string) => request<PhotoDetail>(`/photos/${hash}`),
  toggleFavorite: (hash: string) => post<Toggle<"is_favorite">>(`/photos/${hash}/favorite`),
  togglePrint: (hash: string) => post<Toggle<"marked_for_print">>(`/photos/${hash}/print`),
  toggleFlag: (hash: string) => post<Toggle<"flagged_for_removal">>(`/photos/${hash}/flag`),
  clearPrintList: () => post<{ removed: number }>("/photos/print/clear"),
  getStats: () => request<LibraryStats>("/photos/stats"),

  // Directories. The path goes in raw: the backend route is /{path:path}.
  getDirectoryTree: () => request<DirectoryNode[]>("/directories"),
  getDirectoryPhotos: (path: string, params?: PageParams) =>
    request<PhotoPage>(`/directories/${path}${buildQuery(params)}`),

  // Timeline
  getYears: () => request<YearCount[]>("/timeline/years"),
  getTimeline: (params?: TimelineParams) =>
    request<TimelineGroup[]>(`/timeline${buildQuery(params)}`),

  // Scan and pipeline
  triggerScan: () => post<{ status: string }>("/scan/trigger"),
  stopPipeline: () => post<{ status: string }>("/scan/stop"),
  clearIndex: () => post<{ status: string }>("/scan/clear-index"),
  clearStage: (stage: string) => post<{ status: string }>(`/scan/clear-stage/${stage}`),
  resumeProcessing: () => post<{ status: string; queued: number }>("/scan/resume"),
  getPipelineStatus: () => request<PipelineStats>("/pipeline/status"),
  getProcessingStats: () => request<ProcessingStats>("/pipeline/processing-stats"),
  getPipelineFailures: () => request<StageFailureItem[]>("/pipeline/failures"),

  // Duplicates and large files
  getDuplicates: (params?: PageParams) =>
    request<DuplicateGroup[]>(`/duplicates${buildQuery(params)}`),
  getLargeFiles: (params: PageParams & { min_size?: number }) =>
    request<PhotoPage>(`/large-files${buildQuery(params)}`),

  // Persons
  getPersons: (params?: PageParams) => request<PersonSummary[]>(`/persons${buildQuery(params)}`),
  getPerson: (id: number) => request<PersonSummary>(`/persons/${id}`),
  getPersonPhotos: (id: number, params?: PageParams) =>
    request<PhotoPage>(`/persons/${id}/photos${buildQuery(params)}`),
  updatePerson: (id: number, name: string) =>
    request<PersonSummary>(`/persons/${id}`, { method: "PUT", body: JSON.stringify({ name }) }),
  ignorePerson: (id: number) => post<{ status: string }>(`/persons/${id}/ignore`),
  unignorePerson: (id: number) => post<{ status: string }>(`/persons/${id}/unignore`),
  getIgnoredPersons: () => request<PersonSummary[]>("/persons/ignored"),
  getPersonGroups: (params?: { min_photos?: number }) =>
    request<PersonGroup[]>(`/persons/groups/together${buildQuery(params)}`),
  getHiddenGroups: () => request<HiddenGroup[]>("/persons/groups/hidden"),
  hideGroup: (personIds: number[]) =>
    post<{ status: string; group_key: string }>("/persons/groups/hide", { person_ids: personIds }),
  unhideGroup: (personIds: number[]) =>
    post<{ status: string; group_key: string }>("/persons/groups/unhide", { person_ids: personIds }),
  getSharedPhotosN: (personIds: number[], params?: PageParams) =>
    request<PhotoPage>(
      `/persons/groups/together-n/photos${buildQuery({ ...params, person_ids: personIds.join(",") })}`
    ),

  // Events
  getEvents: (params?: PageParams) => request<EventSummary[]>(`/events${buildQuery(params)}`),
  getEvent: (id: number) => request<EventSummary>(`/events/${id}`),
  getEventPhotos: (id: number, params?: PageParams) =>
    request<PhotoPage>(`/events/${id}/photos${buildQuery(params)}`),

  // Locations
  getCountries: () => request<CountryCount[]>("/locations/countries"),
  getCities: (country?: string) =>
    request<CityCount[]>(`/locations/cities${country ? `?country=${encodeURIComponent(country)}` : ""}`),
  getMapPoints: () => request<MapPoint[]>("/locations/map-points"),
  getTrail: (params?: TrailParams) => request<TrailStop[]>(`/locations/trail${buildQuery(params)}`),
  getLocationPhotos: (params?: LocationPhotoParams) =>
    request<PhotoPage>(`/locations/photos${buildQuery(params)}`),

  // Tags
  getTags: (params?: { limit?: number; q?: string }) => request<TagList>(`/tags${buildQuery(params)}`),
  getTag: (tagId: number) => request<TagCount>(`/tags/${tagId}`),
  getTagPhotos: (tagId: number, params?: PageParams) =>
    request<PhotoPage>(`/tags/${tagId}/photos${buildQuery(params)}`),

  // User data. Export is a file download, import a multipart upload; neither is JSON-in.
  exportUserData: () => fetchBlob(`${BASE_URL}/user-data/export`),
  importUserData: async (file: File): Promise<UserDataImportResult> => {
    const formData = new FormData();
    formData.append("file", file);
    const res = await fetch(`${BASE_URL}/user-data/import`, { method: "POST", body: formData });
    return res.json();
  },
};

/**
 * A PhotoDetail renderable right now from a grid list entry. The summary
 * already carries everything the image and toolbar need; only the info-panel
 * fields (EXIF, faces, tags, location) require a fetch, and those can arrive a
 * moment later without holding up the photo itself.
 */
export function provisionalDetail(p: PhotoSummary): PhotoDetail {
  return {
    ...p,
    file_modified: null,
    location: null,
    exif: null,
    faces: [],
    tags: [],
    live_photo_video: null,
    motion_photo: false,
    indexed_at: null,
  };
}
