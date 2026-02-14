import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './tests',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: 4,
  reporter: 'list',
  use: {
    baseURL: 'http://localhost:7000',
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
    command: 'echo "App should be running on localhost:7000"',
    url: 'http://localhost:7000',
    reuseExistingServer: true,
  },
});