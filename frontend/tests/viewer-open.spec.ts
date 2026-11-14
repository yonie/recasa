import { test, expect, type Page } from "@playwright/test";

const BASE = process.env.RECASA_URL || "http://localhost:7000";
const FULL = 'img[data-testid="full-view"]';

/**
 * Every grid page used to `await api.getPhoto()` before opening the viewer, so
 * a click did nothing at all for the length of a round-trip. They now all go
 * through useOpenPhoto, which opens on the list entry it already has.
 */
async function clickToOpen(page: Page, route: string) {
  await page.goto(`${BASE}${route}`);
  const tile = page.locator('img[src*="/thumbnail/"]').first();
  await tile.waitFor({ state: "visible", timeout: 30000 });

  const t0 = Date.now();
  await tile.click({ force: true });
  // The viewer's own element appearing is the moment the user sees a response.
  await page.locator(FULL).or(page.locator("video")).first().waitFor({
    state: "visible",
    timeout: 30000,
  });
  return Date.now() - t0;
}

// Routes backed by bounded queries, so they stay usable while a scan runs.
for (const route of ["/search?q=.orf", "/to-print"]) {
  test(`viewer opens promptly from ${route}`, async ({ page }) => {
    const ms = await clickToOpen(page, route);
    console.log(`OPEN ${route}: ${ms}ms`);
    expect(ms).toBeLessThan(1000);
    await expect
      .poll(() => page.locator(FULL).evaluate((el: HTMLImageElement) => el.naturalWidth), {
        timeout: 30000,
      })
      .toBeGreaterThan(0);
  });
}

/** Videos take a different branch in the viewer and must be untouched by this. */
test("a video still opens in a player, not the image path", async ({ page }) => {
  await page.goto(`${BASE}/search?q=.mp4`);
  const tile = page.locator('img[src*="/thumbnail/"]').first();
  await tile.waitFor({ state: "visible", timeout: 30000 });
  await tile.click({ force: true });

  const video = page.locator("video");
  await video.waitFor({ state: "visible", timeout: 30000 });
  expect(await video.getAttribute("src")).toContain("/original");
  await expect(page.locator(FULL)).toHaveCount(0);
});

/**
 * Once the full view has decoded, the stand-in must be gone — otherwise a
 * static thumbnail sits behind the image and shows through when zooming.
 */
test("the placeholder is cleared once the full view has decoded", async ({ page }) => {
  await page.goto(`${BASE}/search?q=.orf`);
  const tile = page.locator('img[src*="/thumbnail/"]').first();
  await tile.waitFor({ state: "visible", timeout: 30000 });
  await tile.click({ force: true });
  await page.locator(FULL).waitFor({ state: "visible", timeout: 30000 });
  await expect
    .poll(() => page.locator(FULL).evaluate((el: HTMLImageElement) => el.naturalWidth), {
      timeout: 30000,
    })
    .toBeGreaterThan(0);

  await expect
    .poll(
      () =>
        page
          .locator(FULL)
          .evaluate((el) => getComputedStyle(el.parentElement!).backgroundImage),
      { timeout: 5000 }
    )
    .toBe("none");
});
