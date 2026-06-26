/**
 * Capture des screenshots de validation pour les feuilles de l'arbre
 * PAR Grand Est (culture principale + couvert). Carte #140.
 *
 * Variante régionale de `capture_couvert.spec.ts`. Deux différences :
 *   1. Le manifeste (`_capture_par_ge_manifeste.json`) couvre CP + couvert
 *      PAR, scope=par_grand_est.
 *   2. Le YAML viewer doit être scopé à l'arbre PAR : 3 arbres sont actifs
 *      en DB (national + PAR + ZAR), donc le viewer sans `tree_id` retombe
 *      sur le 1er actif. Le manifeste fournit `yaml_url` avec
 *      `?tree_id=<pk PAR>#regle=<id>`.
 *
 * IMPORTANT (piège #1 multi-arbres) : le simulateur d'une branche feature
 * sans le fix multi-scope renvoie 500 (`MultipleObjectsReturned`). Lancer ce
 * spec contre le container `main` (8042) :
 *   NITRATES_BASE_URL=http://127.0.0.1:8042 npx playwright test \
 *     --config playwright.config.nitrates.ts capture_par_ge.spec.ts \
 *     --workers=2 --reporter=line
 *
 * PNG -> `e2e/nitrates/_captures_par_ge/<pk>_calendrier.png` et
 * `<pk>_yaml.png`. Ingestion ensuite via `manage.py ingest_captures_par_ge`.
 */

import { test, expect, Page } from '@playwright/test';
import * as fs from 'fs';
import * as path from 'path';

const MANIFESTE = path.join(__dirname, '_capture_par_ge_manifeste.json');
const OUT_DIR = path.join(__dirname, '_captures_par_ge');

const STAFF_EMAIL = process.env.CAPTURE_USER || 'capture-bot@nitrates.local';
const STAFF_PW = process.env.CAPTURE_PW || 'capture-bot-local-pw';

type Feuille = {
  pk: number;
  regle_id: string;
  url: string;
  yaml_url: string;
  qc: Record<string, string>;
};

const feuilles: Feuille[] = JSON.parse(fs.readFileSync(MANIFESTE, 'utf-8'));

fs.mkdirSync(OUT_DIR, { recursive: true });

test.beforeAll(async ({ browser }) => {
  const page = await browser.newPage();
  await page.goto('/admin/login/');
  await page.fill('#id_username', STAFF_EMAIL);
  await page.fill('#id_password', STAFF_PW);
  await Promise.all([
    page.waitForLoadState('networkidle'),
    page.locator('input[type="submit"], button[type="submit"]').first().click(),
  ]);
  const state = await page.context().storageState();
  fs.writeFileSync(path.join(OUT_DIR, '_auth.json'), JSON.stringify(state));
  await page.close();
});

async function atteindreResultat(
  page: Page,
  qc: Record<string, string>,
  maxIter = 8
): Promise<boolean> {
  for (let i = 0; i < maxIter; i++) {
    if (
      await page
        .locator('.calendrier-epandage')
        .first()
        .isVisible()
        .catch(() => false)
    ) {
      return true;
    }
    const questions = await page
      .locator('#qc-bloc .form-question-group:not([hidden]), .qc-question:not([hidden])')
      .all();
    if (questions.length === 0) {
      const lancer = page
        .locator('button[type="submit"]', { hasText: /Lancer|Relancer/ })
        .first();
      if (await lancer.isVisible().catch(() => false)) {
        await lancer.click();
        await page.waitForLoadState('networkidle');
        continue;
      }
      return false;
    }
    let repondu = 0;
    for (const q of questions) {
      const champ = await q.getAttribute('data-qc-champ');
      if (!champ) continue;
      const valeur = qc[champ];
      if (valeur === undefined) continue;
      const radio = page
        .locator(`input[type="radio"][name="${champ}"][value="${valeur}"]`)
        .first();
      if (await radio.count()) {
        await radio.check({ force: true });
        repondu++;
      }
    }
    const submit = page
      .locator('button[type="submit"]', { hasText: /Relancer|Lancer/ })
      .first();
    if (!(await submit.isVisible().catch(() => false))) return false;
    await submit.click();
    await page.waitForLoadState('networkidle');
    if (repondu === 0) {
      const calendrier = await page
        .locator('.calendrier-epandage')
        .first()
        .isVisible()
        .catch(() => false);
      if (!calendrier) return false;
    }
  }
  return page
    .locator('.calendrier-epandage')
    .first()
    .isVisible()
    .catch(() => false);
}

test.describe('Capture PAR Grand Est', () => {
  for (const f of feuilles) {
    test(`${f.pk} ${f.regle_id}`, async ({ browser }) => {
      const context = await browser.newContext({
        storageState: path.join(OUT_DIR, '_auth.json'),
      });
      const page = await context.newPage();

      // ── 1. Calendrier simulateur ────────────────────────────────────
      await page.goto(f.url);
      await page.waitForLoadState('networkidle');
      const ok = await atteindreResultat(page, f.qc);
      if (ok) {
        const large = page.locator('.calc-cal').first();
        const cal = (await large.count())
          ? large
          : page.locator('.calendrier-epandage').first();
        await cal.scrollIntoViewIfNeeded();
        await cal.screenshot({
          path: path.join(OUT_DIR, `${f.pk}_calendrier.png`),
        });
      } else {
        await page.screenshot({
          path: path.join(OUT_DIR, `${f.pk}_calendrier_ECHEC.png`),
          fullPage: true,
        });
      }

      // ── 2. Nœud YAML viewer déplié (scopé arbre PAR via tree_id) ─────
      if (f.regle_id && f.yaml_url) {
        await page.goto(f.yaml_url);
        await page.waitForLoadState('networkidle');
        await page.waitForTimeout(400);
        const noeud = page.locator(`.yaml-tree__deeplink-highlight`).first();
        const cible = (await noeud.count())
          ? noeud
          : page.locator('div[id^="regle-block-"]').first();
        if (await cible.count()) {
          await cible.scrollIntoViewIfNeeded();
          await cible.screenshot({
            path: path.join(OUT_DIR, `${f.pk}_yaml.png`),
          });
        }
      }

      await context.close();
      expect(ok, `resultat non atteint pour ${f.regle_id}`).toBeTruthy();
    });
  }
});
