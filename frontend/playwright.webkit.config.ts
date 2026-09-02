import { defineConfig, devices } from '@playwright/test';
export default defineConfig({
  testDir: './tests',
  workers: 1,
  reporter: 'line',
  use: { baseURL: 'http://localhost:7000', headless: true },
  projects: [{ name: 'webkit', use: { ...devices['Desktop Safari'] } }],
});
