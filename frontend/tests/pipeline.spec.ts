import { test, expect } from '@playwright/test';

const BASE_URL = process.env.RECASA_URL || 'http://localhost:7000';

// The status hero's headline once nothing is running.
const IDLE_TEXT = /Watching for new photos|Automatic detection is off/;

/**
 * Wait until the pipeline is idle. Read-only: it never starts a scan, so
 * the browsing tests below can run against an instance that must not be
 * touched (the old version clicked Rescan and waited for a "Completed in"
 * line the page no longer shows).
 */
async function waitForPipelineComplete(page, timeout = 120000) {
  await page.goto('/pipeline');
  await expect(page.getByText(IDLE_TEXT)).toBeVisible({ timeout });
  return true;
}

test.describe('Pipeline Page', () => {
  test('shows idle or done state on initial load', async ({ page }) => {
    await page.goto('/pipeline');

    const rescanButton = page.locator('button').filter({ hasText: /Rescan/i });
    await expect(rescanButton).toBeVisible({ timeout: 10000 });
  });

  test('displays all pipeline stages in the queue table', async ({ page }) => {
    await page.goto('/pipeline');
    await page.waitForSelector('table', { timeout: 30000 });
    
    // Scoped to the table: some names also appear on the rebuild buttons.
    const table = page.locator('table').first();
    const stages = [
      'File Discovery',
      'EXIF Extraction',
      'Geocoding',
      'Thumbnails',
      'Motion Photos',
      'Perceptual Hashing',
      'Face Detection',
      'AI Captioning',
      'Event Detection'
    ];
    
    for (const stage of stages) {
      await expect(table.getByText(stage, { exact: true })).toBeVisible({ timeout: 5000 });
    }
  });

  test('shows queue statistics columns', async ({ page }) => {
    await page.goto('/pipeline');
    await page.waitForSelector('table', { timeout: 30000 });
    
    for (const column of ['Stage', 'Status', 'Done', 'Issues', 'Progress']) {
      await expect(page.getByRole('columnheader', { name: column })).toBeVisible();
    }
    await expect(page.getByText('Pending', { exact: true })).toBeVisible();
  });
});

test.describe('Full Indexing Flow', () => {
  test('completes full pipeline from idle state', async ({ page }) => {
    await page.goto('/pipeline');
    await page.waitForSelector('button', { timeout: 30000 });
    
    const rescanButton = page.locator('button').filter({ hasText: /Rescan/i });
    await rescanButton.click();
    
    // Starts a real scan: only run this against a disposable instance.
    const scanningOrProcessing = page.getByText(/Checking for new photos|Processing photos/);
    await expect(scanningOrProcessing.first()).toBeVisible({ timeout: 10000 });

    await expect(page.getByText(IDLE_TEXT)).toBeVisible({ timeout: 180000 });
  });
});

test.describe('Years/Timeline View', () => {
  test.beforeEach(async ({ page }) => {
    await waitForPipelineComplete(page);
  });

  test('shows years on timeline page', async ({ page }) => {
    await page.goto('/');
    // Month headings ("October 2026"). The old `text=20\d{2}` selector was
    // a literal string, not a regex, so it never matched anything.
    await page.waitForSelector('main h2', { timeout: 30000 });
    const count = await page.locator('main h2').getByText(/20\d{2}/).count();
    expect(count).toBeGreaterThan(0);
  });
});

test.describe('Photos Grid', () => {
  test.beforeEach(async ({ page }) => {
    await waitForPipelineComplete(page);
  });

  test('displays photos on home page', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('img', { timeout: 30000 });
    
    const photos = page.locator('img');
    const count = await photos.count();
    expect(count).toBeGreaterThan(0);
  });
});

test.describe('People View', () => {
  test.beforeEach(async ({ page }) => {
    await waitForPipelineComplete(page);
  });

  test('shows people page after indexing', async ({ page }) => {
    await page.goto('/people');
    await page.waitForSelector('main, h1, body', { timeout: 30000 });
    await expect(page.locator('body')).toBeVisible();
  });
});

test.describe('Events View', () => {
  test.beforeEach(async ({ page }) => {
    await waitForPipelineComplete(page);
  });

  test('shows events page after indexing', async ({ page }) => {
    await page.goto('/events');
    await page.waitForSelector('main, h1, body', { timeout: 30000 });
    await expect(page.locator('body')).toBeVisible();
  });
});

test.describe('Tags View', () => {
  test.beforeEach(async ({ page }) => {
    await waitForPipelineComplete(page);
  });

  test('shows tags page after indexing', async ({ page }) => {
    await page.goto('/tags');
    await page.waitForSelector('main, h1, body', { timeout: 30000 });
    await expect(page.locator('body')).toBeVisible();
  });
});

test.describe('Locations/Map View', () => {
  test.beforeEach(async ({ page }) => {
    await waitForPipelineComplete(page);
  });

  test('shows locations page after indexing', async ({ page }) => {
    await page.goto('/locations');
    await page.waitForSelector('main, h1, body', { timeout: 30000 });
    await expect(page.locator('body')).toBeVisible();
  });
});

test.describe('Search Functionality', () => {
  test.beforeEach(async ({ page }) => {
    await waitForPipelineComplete(page);
  });

  test('search bar is visible on home page', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('input', { timeout: 30000 });
    
    const searchInput = page.locator('input[type="text"], input[placeholder*="search" i]');
    await expect(searchInput.first()).toBeVisible();
  });
});

test.describe('Navigation', () => {
  test('shows sidebar with navigation links', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('a', { timeout: 30000 });
    
    const navLinks = page.locator('a');
    const count = await navLinks.count();
    expect(count).toBeGreaterThan(0);
  });

  test('navigation works for each section', async ({ page }) => {
    const routes = ['/pipeline', '/people', '/events', '/tags', '/locations'];
    
    for (const route of routes) {
      await page.goto(route);
      await page.waitForSelector('body', { timeout: 30000 });
      await expect(page).toHaveURL(new RegExp(route.replace('/', '')));
    }
  });
});

test.describe('API Health', () => {
  test('pipeline status API returns valid response', async ({ page }) => {
    const response = await page.request.get(`${BASE_URL}/api/pipeline/status`);
    expect(response.ok()).toBeTruthy();
    
    const data = await response.json();
    expect(data).toHaveProperty('state');
    expect(['idle', 'scanning', 'processing', 'done']).toContain(data.state);
  });

  test('photos API returns list', async ({ page }) => {
    const response = await page.request.get(`${BASE_URL}/api/photos?page_size=10`);
    expect(response.ok()).toBeTruthy();
    
    const data = await response.json();
    expect(data).toHaveProperty('items');
    expect(Array.isArray(data.items)).toBeTruthy();
  });

  test('timeline API returns data', async ({ page }) => {
    const response = await page.request.get(`${BASE_URL}/api/timeline`);
    expect(response.ok()).toBeTruthy();
    
    const data = await response.json();
    expect(Array.isArray(data)).toBeTruthy();
  });
});

test.describe('Performance', () => {
  test('home page loads within 5 seconds', async ({ page }) => {
    const startTime = Date.now();
    await page.goto('/');
    await page.waitForSelector('body', { timeout: 30000 });
    const loadTime = Date.now() - startTime;
    
    expect(loadTime).toBeLessThan(5000);
  });

  test('pipeline page loads within 5 seconds', async ({ page }) => {
    const startTime = Date.now();
    await page.goto('/pipeline');
    await page.waitForSelector('body', { timeout: 30000 });
    const loadTime = Date.now() - startTime;
    
    expect(loadTime).toBeLessThan(5000);
  });
});