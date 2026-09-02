import { test, expect, Page } from "@playwright/test";

/**
 * Navigation smoke test: click through every main page like a user would
 * (client-side routing, not fresh page loads) and fail on any JS error,
 * failed data request, or blank render.
 */

const SIDEBAR_PAGES = [
  { label: "Photos", path: "/" },
  { label: "Folders", path: "/folders" },
  { label: "Years", path: "/years" },
  { label: "Favorites", path: "/favorites" },
  { label: "To Print", path: "/to-print" },
  { label: "People", path: "/people" },
  { label: "Events", path: "/events" },
  { label: "Locations", path: "/locations" },
  { label: "Tags", path: "/tags" },
  { label: "Pipeline", path: "/pipeline" },
];

function collectErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("pageerror", (err) => errors.push(`pageerror: ${err.message}`));
  page.on("console", (msg) => {
    // WebSocket reconnect noise is expected in test environments
    if (msg.type() === "error" && !msg.text().includes("WebSocket")) {
      errors.push(`console.error: ${msg.text()}`);
    }
  });
  page.on("response", (res) => {
    if (res.url().includes("/api/") && res.status() >= 500) {
      errors.push(`HTTP ${res.status()}: ${res.url()}`);
    }
  });
  return errors;
}

test("click through all main pages without errors", async ({ page }) => {
  const errors = collectErrors(page);

  await page.goto("/", { waitUntil: "networkidle" });

  for (const { label, path } of SIDEBAR_PAGES) {
    await page.click(`aside >> text="${label}"`);
    await expect(page).toHaveURL(new RegExp(`${path.replace("/", "\\/")}$`), {
      timeout: 5000,
    });
    // Wait for any loading spinner to resolve
    await page
      .waitForSelector("main .animate-spin", { state: "detached", timeout: 15000 })
      .catch(() => {});
    // The page must have rendered something
    const blank = await page.evaluate(
      () => document.querySelector("#root")?.children.length === 0
    );
    expect(blank, `${label} rendered a blank page`).toBe(false);
    expect(errors, `errors after clicking ${label}: ${errors.join("; ")}`).toHaveLength(0);
  }
});

test("tags: search and open a tag detail", async ({ page }) => {
  const errors = collectErrors(page);

  await page.goto("/tags", { waitUntil: "networkidle" });
  // Open the first tag pill
  await page.click(".flex.flex-wrap button >> nth=0");
  await page.waitForSelector("main .animate-spin", { state: "detached", timeout: 15000 }).catch(() => {});
  await expect(page).toHaveURL(/\/tags\/\d+$/);

  // Back to the list, use the search box
  await page.click('aside >> text="Tags"');
  await page.fill('input[placeholder="Search all tags…"]', "a");
  await page.waitForTimeout(600); // debounce + fetch
  expect(errors, errors.join("; ")).toHaveLength(0);
});

test("viewer opens from the photo grid", async ({ page }) => {
  const errors = collectErrors(page);

  await page.goto("/", { waitUntil: "networkidle" });
  await page.click(".photo-grid-item >> nth=0");
  // The full view is /original for formats the browser decodes and /preview
  // for RAW and HEIC, so match the element rather than the URL.
  await page.waitForSelector('img[data-testid="full-view"]', { timeout: 15000 });
  await page.keyboard.press("Escape");
  expect(errors, errors.join("; ")).toHaveLength(0);
});
