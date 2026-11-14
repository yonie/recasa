import { test, expect } from '@playwright/test';

test.describe('Hero Trail', () => {
  test('full flow: launch trail, click photo, view it, close it, return to trail with popup still open', async ({ page }) => {
    // 1. Go to locations page
    await page.goto('/locations');
    await page.waitForSelector('.leaflet-container', { timeout: 30000 });

    // 2. Launch Hero Trail
    const trailButton = page.locator('button[title="Hero Trail"]');
    await expect(trailButton).toBeVisible({ timeout: 10000 });
    await trailButton.click();

    // 3. Wait for play controls and timeline scrubber
    const playButton = page.locator('button[title="Play"]');
    await expect(playButton).toBeVisible({ timeout: 15000 });
    const scrubber = page.locator('text=Date range:');
    await expect(scrubber).toBeVisible({ timeout: 5000 });

    // 4. Wait for popup with photos to appear on the active stop
    const popup = page.locator('.leaflet-popup');
    await expect(popup).toBeVisible({ timeout: 10000 });
    const popupPhoto = page.locator('.leaflet-popup img').first();
    await expect(popupPhoto).toBeVisible({ timeout: 10000 });

    // 5. Click the photo: viewer should open
    await popupPhoto.click();
    const viewer = page.locator('.fixed.inset-0');
    await expect(viewer).toBeVisible({ timeout: 10000 });

    // 6. Trail controls should be HIDDEN while viewer is open
    await expect(playButton).not.toBeVisible();
    await expect(scrubber).not.toBeVisible();

    // 7. Close the viewer with Escape
    await page.keyboard.press('Escape');
    await expect(viewer).not.toBeVisible({ timeout: 5000 });

    // 8. Trail controls should reappear
    await expect(playButton).toBeVisible({ timeout: 5000 });
    await expect(scrubber).toBeVisible({ timeout: 5000 });

    // 9. The popup should STILL be open (Escape should not close it)
    await expect(popup).toBeVisible();
    await expect(popupPhoto).toBeVisible();

    // 10. Map should still be visible and we're still in play mode
    await expect(page.locator('.leaflet-container')).toBeVisible();
    await expect(page.locator('button[title="Exit play mode"]')).toBeVisible();
  });

  test('trail controls hidden while photo viewer is open', async ({ page }) => {
    await page.goto('/locations');
    await page.waitForSelector('.leaflet-container', { timeout: 30000 });

    // Launch trail
    await page.locator('button[title="Hero Trail"]').click();
    await expect(page.locator('button[title="Play"]')).toBeVisible({ timeout: 15000 });

    // Wait for popup with photo
    const popupPhoto = page.locator('.leaflet-popup img').first();
    await expect(popupPhoto).toBeVisible({ timeout: 10000 });

    // Open photo viewer
    await popupPhoto.click();
    const viewer = page.locator('.fixed.inset-0');
    await expect(viewer).toBeVisible({ timeout: 10000 });

    // Timeline and controls must be hidden
    await expect(page.locator('text=Date range:')).not.toBeVisible();
    await expect(page.locator('button[title="Play"]')).not.toBeVisible();

    // Close and verify trail resumes
    await page.keyboard.press('Escape');
    await expect(page.locator('button[title="Play"]')).toBeVisible({ timeout: 5000 });
  });
});
