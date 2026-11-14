/** URLs the browser loads directly (img/video src, downloads), not via fetch. */

const BASE_URL = "/api";

export function thumbnailUrl(hash: string, size: number = 600): string {
  return `${BASE_URL}/photos/${hash}/thumbnail/${size}`;
}

export function originalUrl(hash: string): string {
  return `${BASE_URL}/photos/${hash}/original`;
}

/**
 * Full view for the photo viewer. Same bytes as the original for formats the
 * browser can decode; a rendered JPEG for RAW (ORF) and HEIC, which it can't.
 */
export function previewUrl(hash: string): string {
  return `${BASE_URL}/photos/${hash}/preview`;
}

/** Formats no browser decodes: ORF has no LibRaw, HEIC only works in Safari. */
const NEEDS_RENDER = /\.(orf|heic|heif)$/i;

/**
 * Best full-view URL for a photo. Sending decodable formats straight to
 * /original keeps them from queueing behind a RAW decode on the render
 * endpoint. The backend stays the authority (/preview serves the original
 * for anything it doesn't need to convert), so an unrecognised name is safe.
 */
export function fullViewUrl(photo: { file_hash: string; file_name: string }): string {
  return NEEDS_RENDER.test(photo.file_name)
    ? previewUrl(photo.file_hash)
    : originalUrl(photo.file_hash);
}

export function livePhotoUrl(hash: string): string {
  return `${BASE_URL}/photos/${hash}/live`;
}

/** Standalone videos are served through the same original endpoint (range-enabled). */
export const videoUrl = originalUrl;

export function printExportUrl(): string {
  return `${BASE_URL}/photos/print/export`;
}

/** Collage endpoints, keyed by what the collage is made of. */
export const collageUrl = {
  favorites: () => `${BASE_URL}/photos/collage?favorite=true`,
  year: (year: number) => `${BASE_URL}/photos/collage?year=${year}`,
  tag: (name: string) => `${BASE_URL}/photos/collage?tag=${encodeURIComponent(name)}`,
  event: (id: number) => `${BASE_URL}/events/${id}/collage`,
  person: (id: number) => `${BASE_URL}/persons/${id}/collage`,
  together: (ids: number[]) =>
    `${BASE_URL}/persons/groups/together-n/collage?person_ids=${ids.join(",")}`,
};
