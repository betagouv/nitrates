/**
 * Capture automatique des screenshots de validation pour les feuilles
 * « couvert d'interculture ». Carte #140.
 *
 * Pour chaque feuille du manifeste (genere par
 * `manage.py export_manifeste_capture_couvert`), prend 2 captures scopees :
 *
 *   1. CALENDRIER du resultat simulateur (`.calendrier-epandage`). Le
 *      deeplink ne suffit pas a atteindre le resultat : on pilote les
 *      questions complementaires (QC) en repondant avec les valeurs du
 *      manifeste (`qc`), on relance, jusqu'a voir le calendrier.
 *   2. NŒUD de l'arbre dans le YAML viewer admin, deplie + scrolle via le
 *      deeplink `#regle=<id>` (le viewer ouvre les <details> ancestors et
 *      surligne la feuille tout seul).
 *
 * Les PNG sont ecrits dans `e2e/nitrates/_captures_couvert/` nommes
 * `<pk>_calendrier.png` et `<pk>_yaml.png`. La persistance dans le modele
 * se fait ensuite via `manage.py ingest_captures_couvert` (separation
 * capture / ingestion : pas de POST CSRF fragile depuis le spec).
 *
 * Auth : login form admin Django (user staff `capture-bot@nitrates.local`),
 * une fois, en debut de run (local sans ProConnect).
 *
 * Usage :
 *   python manage.py export_manifeste_capture_couvert
 *   npm run e2e-nitrates -- capture_couvert.spec.ts
 *   python manage.py ingest_captures_couvert
 */

import { test, expect, Page } from '@playwright/test';
import * as fs from 'fs';
import * as path from 'path';

const MANIFESTE = path.join(__dirname, '_capture_couvert_manifeste.json');
const OUT_DIR = path.join(__dirname, '_captures_couvert');

const STAFF_EMAIL =
  process.env.CAPTURE_USER || 'capture-bot@nitrates.local';
const STAFF_PW =
  process.env.CAPTURE_PW || 'capture-bot-local-pw';

type Feuille = {
  pk: number;
  regle_id: string;
  url: string;
  qc: Record<string, string>;
};

const feuilles: Feuille[] = JSON.parse(fs.readFileSync(MANIFESTE, 'utf-8'));

fs.mkdirSync(OUT_DIR, { recursive: true });

// Login admin une seule fois (beforeAll), session persistee dans _auth.json
// et reutilisee par chaque test via storageState. PAS de mode serial : les
// 113 feuilles sont independantes ; un test flaky ne doit pas annuler les
// suivants (le serial coupe tout le groupe au 1er echec).
test.beforeAll(async ({ browser }) => {
  const page = await browser.newPage();
  await page.goto('/admin/login/');
  await page.fill('#id_username', STAFF_EMAIL);
  await page.fill('#id_password', STAFF_PW);
  await Promise.all([
    page.waitForLoadState('networkidle'),
    page.locator('input[type="submit"], button[type="submit"]').first().click(),
  ]);
  // Persiste la session pour les pages du run.
  const state = await page.context().storageState();
  fs.writeFileSync(path.join(OUT_DIR, '_auth.json'), JSON.stringify(state));
  await page.close();
});

/**
 * Repond aux QC visibles avec les valeurs de `qc`, relance, jusqu'a ce que
 * le calendrier apparaisse. Retourne true si le resultat est atteint.
 */
async function atteindreResultat(
  page: Page,
  qc: Record<string, string>,
  maxIter = 8
): Promise<boolean> {
  for (let i = 0; i < maxIter; i++) {
    // Resultat deja la ?
    if (
      await page
        .locator('.calendrier-epandage')
        .first()
        .isVisible()
        .catch(() => false)
    ) {
      return true;
    }
    // QC visibles (non cachees par cascade) ?
    const questions = await page
      .locator('#qc-bloc .form-question-group:not([hidden]), .qc-question:not([hidden])')
      .all();
    if (questions.length === 0) {
      // Pas de QC et pas de calendrier : laisser une derniere chance au
      // bouton « Lancer la simulation » initial.
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
      if (valeur === undefined) continue; // pas de reponse connue -> skip
      const radio = page
        .locator(`input[type="radio"][name="${champ}"][value="${valeur}"]`)
        .first();
      if (await radio.count()) {
        await radio.check({ force: true });
        repondu++;
      }
    }
    // Relancer la simulation (bouton du bloc QC, sinon bouton principal).
    const submit = page
      .locator('button[type="submit"]', { hasText: /Relancer|Lancer/ })
      .first();
    if (!(await submit.isVisible().catch(() => false))) return false;
    await submit.click();
    await page.waitForLoadState('networkidle');
    if (repondu === 0) {
      // On n'a rien pu repondre a cette iteration : eviter la boucle infinie.
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

test.describe('Capture couvert', () => {
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
        // Capture LARGE : conteneur .calc-cal = titre « Calendrier des
        // périodes d'épandage » + texte explicatif + champs date + frise +
        // légende + listes à puces. EXCLUT les prescriptions conditionnées
        // (qui sont dans .resultat-panel au-dessus). Fallback sur la frise
        // seule si .calc-cal absent (cas non-calculatrice).
        const large = page.locator('.calc-cal').first();
        const cal = (await large.count())
          ? large
          : page.locator('.calendrier-epandage').first();
        await cal.scrollIntoViewIfNeeded();
        await cal.screenshot({
          path: path.join(OUT_DIR, `${f.pk}_calendrier.png`),
        });
      } else {
        // Trace pour diagnostic : pleine page si resultat non atteint.
        await page.screenshot({
          path: path.join(OUT_DIR, `${f.pk}_calendrier_ECHEC.png`),
          fullPage: true,
        });
      }

      // ── 2. Nœud YAML viewer deplie ──────────────────────────────────
      if (f.regle_id) {
        await page.goto(
          `/admin/nitrates/arbre-decision/#regle=${f.regle_id}`
        );
        await page.waitForLoadState('networkidle');
        // Laisser le JS deeplink deplier + scroller + surligner.
        await page.waitForTimeout(400);
        const noeud = page
          .locator(`.yaml-tree__deeplink-highlight`)
          .first();
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
      // Au moins le calendrier doit etre capture (sinon on veut le savoir).
      expect(ok, `resultat non atteint pour ${f.regle_id}`).toBeTruthy();
    });
  }
});
