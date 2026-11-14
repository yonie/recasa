/**
 * react-query cache keys. Keys that are invalidated from somewhere other than
 * where they are read must match exactly, so they all live here.
 */
export const queryKeys = {
  stats: ["stats"] as const,
  pipelineStatus: ["pipeline", "status"] as const,
  processingStats: ["pipeline", "processing-stats"] as const,
  pipelineFailures: ["pipeline", "failures"] as const,

  photo: (hash: string | undefined) => ["photo", hash] as const,
  photoList: (filter: Record<string, unknown>) => ["photos", filter] as const,
  search: (q: string) => ["search", q] as const,
  largeFiles: (minSize: number) => ["large-files", minSize] as const,
  duplicates: ["duplicates"] as const,

  timeline: (...parts: unknown[]) => ["timeline", ...parts] as const,
  /** The Photos page: last 24 months, photos only. Persisted across loads. */
  homeTimeline: ["timeline", "month", 24, "photos-only"] as const,
  years: ["years"] as const,
  directoryTree: ["directory-tree"] as const,
  directoryPhotos: (path: string | null) => ["directory-photos", path] as const,

  persons: ["persons"] as const,
  ignoredPersons: ["persons", "ignored"] as const,
  person: (id: number) => ["person", id] as const,
  personPhotos: (id: number) => ["person-photos", id] as const,
  personGroups: ["person-groups"] as const,
  hiddenGroups: ["hidden-groups"] as const,
  togetherPersonsAll: ["persons-together"] as const,
  togetherPersons: (ids: string | undefined) => ["persons-together", ids] as const,
  togetherPhotos: (ids: string | undefined) => ["shared-photos", ids] as const,

  events: ["events"] as const,
  event: (id: number) => ["event", id] as const,
  eventPhotos: (id: number) => ["event-photos", id] as const,

  countries: ["countries"] as const,
  cities: (country: string | undefined) => ["cities", country] as const,
  locationPhotos: (country: string | undefined, city: string | undefined) =>
    ["location-photos", country, city] as const,
  mapPoints: ["map-points"] as const,

  tags: (q: string) => ["tags", q] as const,
  tag: (id: number) => ["tag", id] as const,
  tagPhotos: (id: number) => ["tag-photos", id] as const,
};
