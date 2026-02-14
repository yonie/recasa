import { test, expect } from '@playwright/test';

const BASE_URL = 'http://localhost:7000';

async function waitForPipelineComplete(page, timeout = 120000) {
  await page.goto('/pipeline');
  
  await page.waitForSelector('h1', { timeout: 30000 });
  
  const doneText = page.locator('text=Completed in');
  const isDone = await doneText.isVisible().catch(() => false);
  if (isDone) return true;
  
  const rescanButton = page.locator('button').filter({ hasText: /Rescan/i });
  const isIdle = await rescanButton.isVisible().catch(() => false);
  
  if (isIdle) {
    await rescanButton.click();
    await expect(page.locator('text=Completed in')).toBeVisible({ timeout });
  }
  
  return true;
}

test.describe('Pipeline Page', () => {
  test('shows idle or done state on initial load', async ({ page }) => {
    await page.goto('/pipeline');
    await page.waitForSelector('h1', { timeout: 30000 });
    
    const rescanButton = page.locator('button').filter({ hasText: /Rescan/i });
    await expect(rescanButton).toBeVisible({ timeout: 10000 });
  });

  test('displays all pipeline stages in the queue table', async ({ page }) => {
    await page.goto('/pipeline');
    await page.waitForSelector('table', { timeout: 30000 });
    
    const stages = [
      'Discovery',
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
      await expect(page.getByText(stage, { exact: false })).toBeVisible({ timeout: 5000 });
    }
  });

  test('shows queue statistics columns', async ({ page }) => {
    await page.goto('/pipeline');
    await page.waitForSelector('table', { timeout: 30000 });
    
    await expect(page.getByText('Stage')).toBeVisible();
    await expect(page.getByText('Status')).toBeVisible();
    await expect(page.getByText('Done')).toBeVisible();
    await expect(page.getByText('Pending')).toBeVisible();
  });
});

test.describe('Full Indexing Flow', () => {
  test('completes full pipeline from idle state', async ({ page }) => {
    await page.goto('/pipeline');
    await page.waitForSelector('button', { timeout: 30000 });
    
    const rescanButton = page.locator('button').filter({ hasText: /Rescan/i });
    await rescanButton.click();
    
    const scanningOrProcessing = page.locator('text=/Scanning|Processing/');
    await expect(scanningOrProcessing.first()).toBeVisible({ timeout: 10000 });
    
    await expect(page.locator('text=Completed in')).toBeVisible({ timeout: 180000 });
    await expect(page.locator('text=files processed')).toBeVisible();
  });
});

test.describe('Years/Timeline View', () => {
  test.beforeEach(async ({ page }) => {
    await waitForPipelineComplete(page);
  });

  test('shows years on timeline page', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('a, [class*="year"]', { timeout: 30000 });
    
    const yearPattern = /20\d{2}/;
    const yearElements = page.locator(`text=${yearPattern.source}`);
    const count = await yearElements.count();
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