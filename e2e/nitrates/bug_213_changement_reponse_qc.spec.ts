import { test, expect, Page } from '@playwright/test';

/**
 * #213 — changement de reponse a une question complementaire (QC).
 *
 * Comportement attendu (prefetch integral, #213) :
 *   - le serveur rend d'avance les QC de TOUTES les branches (cachees,
 *     annotees data-qc-parent-champ/valeur), y compris celles heritees d'une
 *     bascule cross-arbre (PAR -> PAN via noeud_depart) ;
 *   - changer une reponse QC revele/masque la cascade cote client, SANS
 *     resubmit : rien ne part au serveur tant qu'on n'a pas clique
 *     « Suivant » / « Lancer la simulation » ;
 *   - les QC aval devenues incoherentes sont masquees ET decochees ;
 *   - changer un champ amont (ex. sous-fertilisant) ne rase PAS le volet QC
 *     (anti-clignotement : c'est le rendu serveur suivant qui tranche).
 *
 * Parcours de reference : couvert interculture longue, CINE detruit avant le
 * 31/12, fumier de volaille -> QC « plan d'epandage ».
 */

const REIMS_LNG = 4.0345;
const REIMS_LAT = 49.2583;
const QC_BLOC = '#qc-bloc';

async function pick(page: Page, name: string, value: string) {
  const input = page
    .locator(`input[type=radio][name="${name}"][value="${value}"]:visible`)
    .first();
  await expect(input, `radio ${name}=${value} absent/invisible`).toHaveCount(1);
  const id = await input.getAttribute('id');
  await page.locator(`label[for="${id}"]`).first().click();
  await page.waitForTimeout(500);
}

async function pickFlow(page: Page, name: string, index: number) {
  const g = page.locator(`input[type=radio][name="${name}"]`);
  await expect(g.nth(index), `radio ${name}[${index}] absent`).toHaveCount(1);
  const id = await g.nth(index).getAttribute('id');
  await page.locator(`label[for="${id}"]`).first().click();
  await page.waitForTimeout(300);
}

async function saisirDate(page: Page, inputId: string, jjmm: string) {
  const inp = page.locator(`#q_dates_couvert input[data-input-id="${inputId}"]`);
  await inp.fill(jjmm);
  await inp.blur();
  await page.waitForTimeout(200);
}

async function submit(page: Page) {
  const btn = page
    .locator('button[type="submit"]', { hasText: /Lancer|Relancer|Suivant/ })
    .first();
  await btn.click();
  await page.waitForTimeout(1800);
}

/** Pose un marqueur JS : perdu = la page a recharge (resubmit interdit). */
async function marquerPage(page: Page) {
  await page.evaluate(() => {
    (window as any).__pas_de_reload = true;
  });
}
async function pasDeReload(page: Page): Promise<boolean> {
  return page.evaluate(() => (window as any).__pas_de_reload === true);
}

/** Etat d'un groupe QC : { hidden, coche } ou null si absent du DOM. */
async function qcEtat(page: Page, champ: string) {
  return page.evaluate((c) => {
    const g = document.querySelector(
      `.qc-question[data-qc-champ="${c}"]`,
    ) as HTMLElement | null;
    if (!g) return null;
    const r = g.querySelector(
      'input[type=radio]:checked',
    ) as HTMLInputElement | null;
    return { hidden: g.hidden, coche: r ? r.value : null };
  }, champ);
}

async function parcoursJusquAuxQC(page: Page) {
  await page.goto(`/simulateur/?lng=${REIMS_LNG}&lat=${REIMS_LAT}`);
  await page.waitForLoadState('networkidle');
  await pickFlow(page, 'cflow_destination', 0);
  await pickFlow(page, 'cflow_type_couvert', 0);
  await pickFlow(page, 'cflow_couvert_recolte', 1);
  await saisirDate(page, 'date_semis_couvert', '15/08');
  await saisirDate(page, 'date_destruction_couvert', '15/11');
  await pick(page, 'categorie_fertilisant', 'fumiers');
  await pick(page, 'sous_fertilisant', 'fumier_volaille');
  await submit(page);
  await expect(page.locator(QC_BLOC)).toBeVisible();
}

test('#213a : la cascade QC prefetchee se revele sans resubmit, jusqu au resultat en un seul Lancer', async ({
  page,
}) => {
  test.setTimeout(90000);
  await parcoursJusquAuxQC(page);

  // La QC de la branche icpe_ed est deja dans le DOM, cachee, annotee.
  let dig = await qcEtat(page, 'pas_un_digestats');
  expect(dig, 'pas_un_digestats doit etre prefetchee').not.toBeNull();
  expect(dig!.hidden, 'prefetchee = cachee tant que non pertinente').toBe(true);

  // Repondre icpe_ed revele la QC enchainee SANS aller-retour serveur.
  await marquerPage(page);
  await pick(page, 'plan_epandage', 'icpe_ed');
  expect(await pasDeReload(page), 'resubmit interdit au clic QC').toBe(true);
  dig = await qcEtat(page, 'pas_un_digestats');
  expect(dig!.hidden, 'la QC de la branche choisie doit se reveler').toBe(false);
  expect(dig!.coche, 'revelee VIERGE (pas pre-remplie)').toBeNull();

  // On repond a toute la cascade puis UN SEUL « Lancer » -> resultat direct.
  await pick(page, 'pas_un_digestats', 'False');
  await submit(page);
  await expect(
    page.locator('.result-col').first(),
    'toutes les QC etaient repondues -> resultat en un seul aller-retour',
  ).toBeVisible();
});

test('#213b : flip d une reponse QC apres resultat — revele/masque sans resubmit, y compris cross-arbre', async ({
  page,
}) => {
  test.setTimeout(120000);
  await parcoursJusquAuxQC(page);

  // Chemin icpe_a (bascule PAR -> PAN) : iaa posee apres Lancer.
  await pick(page, 'plan_epandage', 'icpe_a');
  await submit(page);
  const iaa = await qcEtat(page, 'fertilisant_iaa');
  expect(iaa, 'fertilisant_iaa attendue apres icpe_a').not.toBeNull();
  await pick(page, 'fertilisant_iaa', 'True');
  await submit(page);
  await expect(page.locator('.result-col').first()).toBeVisible();

  // Modifier -> flip icpe_a -> icpe_ed : iaa (cross-arbre) se masque et se
  // decoche, digestats se revele vierge. AUCUN resubmit.
  await page.locator('[data-recap-modifier]').first().click();
  await page.waitForTimeout(700);
  await marquerPage(page);
  await pick(page, 'plan_epandage', 'icpe_ed');
  expect(await pasDeReload(page), 'resubmit interdit au flip QC').toBe(true);
  const iaaApres = await qcEtat(page, 'fertilisant_iaa');
  expect(iaaApres!.hidden, 'la QC de l ancienne branche doit se masquer').toBe(true);
  expect(iaaApres!.coche, 'et se decocher (ne sera pas soumise)').toBeNull();
  const digApres = await qcEtat(page, 'pas_un_digestats');
  expect(digApres!.hidden, 'la QC de la nouvelle branche doit se reveler').toBe(false);
  expect(digApres!.coche, 'revelee vierge').toBeNull();

  // Volet toujours a l ecran, et « Lancer » disponible pour finaliser.
  await expect(page.locator(QC_BLOC)).toBeVisible();
  await pick(page, 'pas_un_digestats', 'False');
  await submit(page);
  await expect(
    page.locator('.result-col').first(),
    'apres flip + reponse, un seul Lancer donne le resultat',
  ).toBeVisible();
});

test('#213c : changer le sous-fertilisant ne rase pas le volet QC (anti-clignotement)', async ({
  page,
}) => {
  test.setTimeout(90000);
  await parcoursJusquAuxQC(page);
  await pick(page, 'plan_epandage', 'icpe_ed');
  await pick(page, 'pas_un_digestats', 'False');
  await submit(page);
  await expect(page.locator('.result-col').first()).toBeVisible();

  await page.locator('[data-recap-modifier]').first().click();
  await page.waitForTimeout(700);
  await marquerPage(page);
  // Fumier compact : meme QC ICPE dans l arbre -> le volet ne doit pas
  // disparaitre au changement (il sera confirme/ajuste au Lancer suivant).
  await pick(page, 'sous_fertilisant', 'fumier_compact_non_susceptible_ecoulement');
  expect(await pasDeReload(page), 'resubmit interdit au changement amont').toBe(true);
  await expect(
    page.locator(QC_BLOC),
    'le volet QC ne doit pas disparaitre au changement d un champ amont',
  ).toBeVisible();
  const plan = await qcEtat(page, 'plan_epandage');
  expect(plan, 'la QC plan_epandage reste a l ecran').not.toBeNull();
  expect(plan!.hidden).toBe(false);

  // Le resultat, lui, a bien ete invalide (il ne correspond plus aux choix).
  await expect(page.locator('.result-col')).toHaveCount(0);
});
