import { test, expect, type Page } from "@playwright/test";

const BASE = process.env.RECASA_URL || "http://localhost:7000";
const FULL = 'img[data-testid="full-view"]';
const hashOf = (s: string) => s.match(/photos\/([0-9a-f]+)\//)?.[1] ?? "";

/**
 * Open the viewer on a RAW photo. Uses the search page rather than the home
 * timeline: search is a bounded query, so it stays fast while a scan runs, and
 * it guarantees the photo is a format that needs rendering.
 */
async function openFirstRaw(page: Page) {
  await page.goto(`${BASE}/search?q=.orf`);
  const tile = page.locator('img[src*="/thumbnail/"]').first();
  await tile.waitFor({ state: "visible", timeout: 30000 });
  await tile.click({ force: true });
  const img = page.locator(FULL);
  await img.waitFor({ state: "visible", timeout: 30000 });
  return img;
}

async function waitDecoded(page: Page) {
  await expect
    .poll(() => page.locator(FULL).evaluate((el: HTMLImageElement) => el.naturalWidth), {
      timeout: 30000,
    })
    .toBeGreaterThan(0);
}

async function currentHash(page: Page) {
  return hashOf((await page.locator(FULL).getAttribute("src")) ?? "");
}

/** Press a key and wait for the photo to actually change and finish decoding. */
async function step(page: Page, key: "ArrowRight" | "ArrowLeft") {
  const before = await currentHash(page);
  await page.keyboard.press(key);
  await expect.poll(() => currentHash(page), { timeout: 15000 }).not.toBe(before);
  await waitDecoded(page);
  return currentHash(page);
}

/**
 * Per animation frame, when does the CORRECT photo first appear on screen?
 * `steps` presses ArrowRight that many times in one go: stepping more than one
 * photo lands beyond the prefetch window, so the full view genuinely has to be
 * fetched and the stand-in is what carries the swap.
 */
const measure = ([oldHash, steps]: [string, number]) =>
  new Promise<{ correctAt: number; via: string; fullAt: number; newHash: string }>((resolve) => {
    const container = document.querySelector('img[data-testid="full-view"]')!.parentElement!;
    const t0 = performance.now();
    for (let i = 0; i < steps; i++) {
      document.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true }));
    }

    let correctAt = -1;
    let via = "none";
    const tick = () => {
      const el = container.querySelector('img[data-testid="full-view"]') as HTMLImageElement | null;
      const newHash = (el?.src ?? "").match(/photos\/([0-9a-f]+)\//)?.[1] ?? "";
      const fresh = !!newHash && newHash !== oldHash;
      const bg = getComputedStyle(container).backgroundImage;
      const decoded = !!el && el.complete && el.naturalWidth > 0;

      if (correctAt < 0 && fresh && (bg.includes(newHash) || decoded)) {
        correctAt = performance.now() - t0;
        via = decoded ? "full" : "placeholder";
      }
      if (fresh && decoded) {
        resolve({ correctAt, via, fullAt: performance.now() - t0, newHash });
        return;
      }
      requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  });

/**
 * Navigating used to leave the previous photo up for ~1s: the detail fetch was
 * awaited before anything changed, and the reused <img> kept painting the old
 * frame until the new (RAW-rendered, multi-MB) bytes decoded.
 */
test("stepping to the next photo shows it immediately", async ({ page }) => {
  const img = await openFirstRaw(page);
  await waitDecoded(page);
  const first = hashOf((await img.getAttribute("src")) ?? "");
  const shotBefore = await page.screenshot();

  const t = await page.evaluate(measure, [first, 1] as [string, number]);
  console.log("WARM STEP:", JSON.stringify(t));

  expect(t.newHash).not.toBe(first);
  expect(t.correctAt).toBeGreaterThanOrEqual(0);
  expect(t.correctAt).toBeLessThan(100); // inside the window that reads as instant
  expect(Buffer.compare(shotBefore, await page.screenshot())).not.toBe(0);
});

/**
 * The slow path behind the original complaint, tested on a cold open: opening
 * a photo whose full view takes ~1.5s. Nothing is prefetched yet, so the
 * stand-in is the only thing that can be on screen, and it must be the photo
 * the user actually clicked.
 */
test("a slow full view shows the right photo at once on open", async ({ page }) => {
  await page.route("**/preview", async (route) => {
    await new Promise((r) => setTimeout(r, 1500));
    await route.continue();
  });

  await page.goto(`${BASE}/search?q=.orf`);
  const tile = page.locator('img[src*="/thumbnail/"]').first();
  await tile.waitFor({ state: "visible", timeout: 30000 });
  const hash = hashOf((await tile.getAttribute("src")) ?? "");
  expect(hash).toHaveLength(64);

  const t = await page.evaluate(async (h) => {
    const el = document.querySelector(`img[src*="${h}"]`) as HTMLElement;
    const t0 = performance.now();
    el.click();
    return new Promise<{ placeholderAt: number; fullAt: number }>((resolve) => {
      let placeholderAt = -1;
      const tick = () => {
        const img = document.querySelector('img[data-testid="full-view"]') as HTMLImageElement | null;
        if (img) {
          const bg = getComputedStyle(img.parentElement!).backgroundImage;
          if (placeholderAt < 0 && bg.includes(h)) placeholderAt = performance.now() - t0;
          if (img.complete && img.naturalWidth > 0) {
            resolve({ placeholderAt, fullAt: performance.now() - t0 });
            return;
          }
        }
        requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
    });
  }, hash);

  console.log("COLD OPEN:", JSON.stringify(t));
  expect(t.placeholderAt).toBeGreaterThanOrEqual(0); // the clicked photo stood in
  expect(t.placeholderAt).toBeLessThan(150);
  expect(t.fullAt).toBeGreaterThan(1400); // and the full view really was slow
});

/** Rapid stepping must not drop keys, race, or land on the wrong photo. */
test("rapid stepping lands on the right photo", async ({ page, request }) => {
  // Same query the search page runs, so the order matches the viewer's list.
  const res = await request.get(`${BASE}/api/photos?search=.orf&page_size=200`);
  const items = (await res.json()).items as Array<{ file_hash: string }>;
  test.skip(items.length < 10, "not enough ORF files to step through");

  await openFirstRaw(page);
  await waitDecoded(page);
  const start = hashOf((await page.locator(FULL).getAttribute("src")) ?? "");
  const startIdx = items.findIndex((i) => i.file_hash === start);
  expect(startIdx).toBeGreaterThanOrEqual(0);

  const steps = 6;
  for (let i = 0; i < steps; i++) await page.keyboard.press("ArrowRight");

  // Every key must land: no drops from an in-flight guard, no out-of-order
  // detail response winning and pulling us back.
  await expect
    .poll(async () => hashOf((await page.locator(FULL).getAttribute("src")) ?? ""), {
      timeout: 20000,
    })
    .toBe(items[startIdx + steps].file_hash);
  await waitDecoded(page);
});

/** Stepping back must return to exactly the photo we came from. */
test("stepping back returns to the previous photo", async ({ page }) => {
  await openFirstRaw(page);
  await waitDecoded(page);
  const first = await currentHash(page);

  const second = await step(page, "ArrowRight");
  expect(second).not.toBe(first);

  const backAgain = await step(page, "ArrowLeft");
  expect(backAgain).toBe(first);
});

/**
 * If the render fails there is still a correct thumbnail to show, which beats
 * the blank frame the viewer used to leave behind.
 */
test("a failed render leaves the thumbnail showing, not a blank frame", async ({ page }) => {
  await page.route("**/preview", (route) => route.fulfill({ status: 500, body: "boom" }));

  await page.goto(`${BASE}/search?q=.orf`);
  const tile = page.locator('img[src*="/thumbnail/"]').first();
  await tile.waitFor({ state: "visible", timeout: 30000 });
  await tile.click({ force: true });
  await page.locator(FULL).waitFor({ state: "visible", timeout: 30000 });

  const state = await page.evaluate(async () => {
    const container = document.querySelector('img[data-testid="full-view"]')!.parentElement!;
    await new Promise((r) => setTimeout(r, 1500));
    const el = container.querySelector('img[data-testid="full-view"]') as HTMLImageElement;
    const hash = (el?.src ?? "").match(/photos\/([0-9a-f]+)\//)?.[1] ?? "";
    return {
      showsOwnThumb: getComputedStyle(container).backgroundImage.includes(hash),
      fullDecoded: el.complete && el.naturalWidth > 0,
    };
  });
  console.log("FAILED RENDER:", JSON.stringify(state));
  expect(state.showsOwnThumb).toBe(true);
  expect(state.fullDecoded).toBe(false);
});
