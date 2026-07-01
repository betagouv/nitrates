/**
 * Capture des screenshots de validation pour les feuilles ZAR Grand Est.
 * Carte #140. Variante de capture_couvert.spec.ts pour l'arbre ZAR.
 *
 * Pour chaque feuille du manifeste (genere par
 * `manage.py export_manifeste_capture_zar`), prend 2 captures :
 *
 *   1. CALENDRIER du resultat simulateur (`.calc-cal` / `.calendrier-epandage`).
 *      Le deeplink ne suffit pas : on pilote les questions complementaires
 *      (QC) avec les valeurs du manifeste jusqu'au calendrier.
 *   2. NŒUD de l'arbre dans le YAML viewer admin, deplie via le deeplink
 *      `?tree_id=<zar_pk>#regle=<id>` (le `tree_id` force l'arbre ZAR, sinon
 *      le viewer ouvre l'arbre national actif).
 *
 * IMPORTANT : capturer contre le container qui sert `main` (8042), seul a
 * gerer le multi-scope (3 arbres actifs). Une branche feature sans le fix
 * leve `DecisionTree.MultipleObjectsReturned` (500) sur tout deeplink.
 *
 * PNG ecrits dans `e2e/nitrates/_captures_zar/` (`<pk>_calendrier.png`,
 * `<pk>_yaml.png`). Persistance via `manage.py ingest_captures_couvert`
 * (ingest par pk, scope-agnostic).
 *
 * Usage :
 *   docker exec <zar> sh /tmp/run_manage.sh export_manifeste_capture_zar
 *   NITRATES_BASE_URL=http://127.0.0.1:8042 npx playwright test \
 *     --config playwright.config.nitrates.ts capture_zar.spec.ts --workers=2
 *   docker exec <zar> sh /tmp/run_manage.sh ingest_captures_couvert \
 *     --dir e2e/nitrates/_captures_zar
 */

import { test, expect, Page } from '@playwright/test';
import * as fs from 'fs';
import * as path from 'path';

const MANIFESTE = path.join(__dirname, '_capture_zar_manifeste.json');
const OUT_DIR = path.join(__dirname, '_captures_zar');

const STAFF_EMAIL = process.env.CAPTURE_USER || 'capture-bot@nitrates.local';
const STAFF_PW = process.env.CAPTURE_PW || 'capture-bot-local-pw';

type Feuille = {
  pk: number;
  regle_id: string;
  url: string;
  tree_id: number;
  qc: Record<string, string>;
};

const feuilles: Feuille[] = JSON.parse(fs.readFileSync(MANIFESTE, 'utf-8'));

fs.mkdirSync(OUT_DIR, { recursive: true });

// Traduction slug YAML (manifeste) -> value(s) du radio form, quand le form
// n'expose pas le meme slug que l'arbre. `plan_epandage=icpe_autre` (YAML)
// regroupe les cas non-ICPE-ED : le form les distingue en `icpe_a`
// (a autorisation) et `non_concerne`, qui routent tous deux vers la meme
// feuille-resultat ZAR. On essaie les deux.
const VALUE_TRAD: Record<string, Record<string, string[]>> = {
  plan_epandage: { icpe_autre: ['icpe_a', 'non_concerne'] },
};

// Champs dont la valeur ne discrimine PAS le calendrier ZAR sur les couverts
// type_Ia/Ib (le form les pose quand meme). Si non mappes, on coche la 1re
// option pour debloquer la cascade sans fausser le resultat.
const FALLBACK_PREMIER = new Set<string>([
  'fertilisant_iaa',
  'effluent_peu_charge',
  'effluent_peu_charge_elevage',
]);

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
        .locator('button[type="submit"]', { hasText: /Lancer|Relancer|Suivant/ })
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
      // Valeurs candidates : la valeur du contexte (manifeste) PLUS des
      // traductions slug YAML -> value du form. Le form n'expose pas les
      // memes slugs que l'arbre pour certains champs (ex `plan_epandage`
      // YAML `icpe_autre` <-> form `icpe_a`/`non_concerne`). On essaie les
      // candidats dans l'ordre et on coche le 1er radio existant.
      const candidats: string[] = [];
      const valeur = qc[champ];
      if (valeur !== undefined) candidats.push(valeur);
      const trad = VALUE_TRAD[champ]?.[valeur ?? ''];
      if (trad) candidats.push(...trad);
      let radio = null;
      for (const v of candidats) {
        const r = page
          .locator(`input[type="radio"][name="${champ}"][value="${v}"]`)
          .first();
        if (await r.count()) {
          radio = r;
          break;
        }
      }
      // Fallback ultime : QC non mappee dans le contexte de la feuille
      // (intermediaires ZAR poses par le form : fertilisant_iaa, effluent,
      // q_typeIa_ICPE_ED_q6, ...). On coche la 1re option pour debloquer la
      // cascade et atteindre UN calendrier. Best-effort : sur les branches
      // ou ce choix discrimine le resultat, le validateur revoit le crop.
      // (`FALLBACK_PREMIER` garde une trace des champs surement non
      // discriminants ; le fallback general s'applique a tous les autres.)
      void FALLBACK_PREMIER;
      if (!radio) {
        const r = page.locator(`input[type="radio"][name="${champ}"]`).first();
        if (await r.count()) radio = r;
      }
      if (radio) {
        await radio.check({ force: true });
        repondu++;
      }
    }
    const submit = page
      .locator('button[type="submit"]', { hasText: /Suivant|Relancer|Lancer/ })
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

test.describe('Capture ZAR Grand Est', () => {
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

      // ── 2. Nœud YAML viewer deplie (tree_id ZAR force) ──────────────
      if (f.regle_id) {
        await page.goto(
          `/admin/nitrates/arbre-decision/?tree_id=${f.tree_id}#regle=${f.regle_id}`
        );
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
