import { defineConfig, devices } from '@playwright/test';

// The instance under test. Defaults to the app on this host; point it
// elsewhere with e.g. RECASA_URL=http://localhost:3000 (a Vite dev server).
const baseURL = process.env.RECASA_URL || 'http://localhost:7000';

export default defineConfig({
  testDir: './tests',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: 4,
  reporter: 'list',
  use: {
    baseURL,
    trace: 'on-first-retry',
    headless: true,
    launchOptions: {
      headless: true,
    },
  },
  projects: [
    {
      name: 'chromium',
      use: { 
        ...devices['Desktop Chrome'],
        headless: true,
        launchOptions: {
          headless: true,
        },
      },
    },
  ],
  webServer: {
    command: `echo "App should be running on ${baseURL}"`,
    url: baseURL,
    reuseExistingServer: true,
  },
});