import { test, expect } from "@playwright/test";

const BASE = process.env.RECASA_URL || "http://localhost:7000";

/** Decode a URL in the page and report the resulting bitmap size. */
const decode = (url: string) =>
  new Promise<{ w: number; h: number }>((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve({ w: img.naturalWidth, h: img.naturalHeight });
    img.onerror = () => reject(new Error("browser could not decode " + url));
    img.src = url;
  });

async function firstHash(request: any, ext: string): Promise<string | null> {
  const res = await request.get(`${BASE}/api/photos?search=${ext}&limit=1`);
  const items = (await res.json()).items as Array<{ file_hash: string }>;
  return items.length ? items[0].file_hash : null;
}

/**
 * The viewer used to point its <img> at /original, which streams raw ORF bytes
 * no browser can decode, so clicking an ORF showed nothing at all.
 */
test("ORF full view decodes in the browser", async ({ page, request }) => {
  const hash = await firstHash(request, ".orf");
  test.skip(!hash, "no ORF files in this library");
  await page.goto(`${BASE}/`);
  const got = await page.evaluate(decode, `${BASE}/api/photos/${hash}/preview`);
  expect(got.w).toBeGreaterThan(0);
  expect(got.h).toBeGreaterThan(0);
});

/** HEIC decodes only in Safari, so it needs the same conversion as RAW. */
test("HEIC full view decodes in the browser", async ({ page, request }) => {
  const hash = await firstHash(request, ".heic");
  test.skip(!hash, "no HEIC files in this library");
  await page.goto(`${BASE}/`);
  const got = await page.evaluate(decode, `${BASE}/api/photos/${hash}/preview`);
  expect(got.w).toBeGreaterThan(0);
  expect(got.h).toBeGreaterThan(0);
});

/** A preview must be served at the photo's real resolution, not downscaled. */
test("preview keeps the original resolution", async ({ page, request }) => {
  const res = await request.get(`${BASE}/api/photos?search=.orf&limit=1`);
  const items = (await res.json()).items as Array<{
    file_hash: string;
    width: number;
    height: number;
  }>;
  test.skip(items.length === 0, "no ORF files in this library");
  const photo = items[0];
  await page.goto(`${BASE}/`);
  const got = await page.evaluate(decode, `${BASE}/api/photos/${photo.file_hash}/preview`);
  expect([got.w, got.h].sort()).toEqual([photo.width, photo.height].sort());
});

/** A format the browser handles must be passed through untouched. */
test("a decodable format is served as the original, not re-encoded", async ({ request }) => {
  const res = await request.get(`${BASE}/api/photos?search=.jpg&limit=1`);
  const items = (await res.json()).items as Array<{ file_hash: string; file_size: number }>;
  test.skip(items.length === 0, "no JPEG files in this library");
  const { file_hash, file_size } = items[0];
  const preview = await request.get(`${BASE}/api/photos/${file_hash}/preview`);
  expect(preview.status()).toBe(200);
  expect((await preview.body()).length).toBe(file_size);
});
