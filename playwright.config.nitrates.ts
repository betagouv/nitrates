import { defineConfig, devices } from '@playwright/test';

/**
 * Configuration Playwright dédiée aux tests E2E nitrates.
 *
 * Cible le hostname `nitrates.local` pour atteindre l'urlconf nitrates via le
 * middleware (cf. envergo/contrib/middleware.py:SetUrlConfBasedOnSite).
 *
 * Lancée depuis le container `node` (cf. `npm run e2e-nitrates`), elle utilise
 * `--host-resolver-rules` pour résoudre `nitrates.local` vers le service Docker
 * `django:8000`. Lancée depuis l'hôte, le baseURL `http://nitrates.local:8042`
 * fonctionne tel quel (cf. /etc/hosts).
 */
const inDocker = process.env.IN_DOCKER === '1';
const baseURL = inDocker
  ? 'http://nitrates.local:8000'
  : process.env.NITRATES_BASE_URL || 'http://nitrates.local:8042';

export default defineConfig({
  testDir: './e2e/nitrates',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: 'html',
  use: {
    baseURL,
    trace: 'on-first-retry',
    video: 'on-first-retry',
    locale: 'fr-FR',
    launchOptions: inDocker
      ? {
          args: ['--host-resolver-rules=MAP nitrates.local django'],
        }
      : undefined,
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
});
