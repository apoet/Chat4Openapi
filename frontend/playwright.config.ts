import { defineConfig } from '@playwright/test'

const localChromium = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE

export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  use: {
    baseURL: 'http://127.0.0.1:4174',
    channel: localChromium ? undefined : 'chrome',
    launchOptions: localChromium ? { executablePath: localChromium } : undefined,
    trace: 'retain-on-failure',
  },
  webServer: [
    {
      command: 'npm run dev -- --host 127.0.0.1 --port 4173',
      url: 'http://127.0.0.1:4173/embed/health-check',
      reuseExistingServer: true,
    },
    {
      command: 'node e2e/host-server.mjs',
      url: 'http://127.0.0.1:4174/embed-host-basic.html',
      reuseExistingServer: true,
    },
  ],
})
