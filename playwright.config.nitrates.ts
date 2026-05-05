import { defineConfig, devices } from '@playwright/test';

/**
 * Configuration Playwright dédiée aux tests E2E nitrates.
 *
 * Cible 127.0.0.1 pour atteindre l'urlconf nitrates via le middleware
 * (cf. envergo/contrib/middleware.py:SetUrlConfBasedOnSite et la
 * Site Django id=3 domain=127.0.0.1). Pas de DNS local lent, pas de
 * --host-resolver-rules.
 *
 * Lancée depuis le container `node` (cf. `npm run e2e-nitrates`), Chrome
 * doit toucher le service Docker `django:8000` mais envoyer Host=127.0.0.1
 * pour matcher la Site Django. On obtient ça via --host-resolver-rules
 * MAP 127.0.0.1 -> django (le Host header reste 127.0.0.1, l'IP devient
 * celle du service django).
 *
 * Lancée depuis l'hôte, le baseURL `http://127.0.0.1:8042` fonctionne
 * directement.
 */
const inDocker = process.env.IN_DOCKER === '1';
const baseURL = inDocker
  ? 'http://127.0.0.1:8000'
  : process.env.NITRATES_BASE_URL || 'http://127.0.0.1:8042';

export default defineConfig({
  testDir: './e2e/nitrates',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  // 1 retry meme en local : le 1er test d'un fichier echoue parfois
  // sur ERR_ABORTED a cause du cold-start chromium dans le container
  // node. Le test repasse au 2eme essai. En CI on garde 2 retries.
  retries: process.env.CI ? 2 : 1,
  workers: process.env.CI ? 1 : undefined,
  reporter: 'html',
  use: {
    baseURL,
    trace: 'on-first-retry',
    video: 'on-first-retry',
    locale: 'fr-FR',
    launchOptions: inDocker
      ? {
          args: ['--host-resolver-rules=MAP 127.0.0.1 django'],
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
