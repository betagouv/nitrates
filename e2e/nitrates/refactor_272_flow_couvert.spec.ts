import { test, expect, Page } from '@playwright/test';

/**
 * #272 — refactor du parcours culture/couvert en questions successives.
 *
 * Vérifie :
 *  - Q1 « Vous avez prévu d'épandre ? » (4 réponses -> couvert | culture_principale)
 *  - Q2 couvert (interculture longue/courte) et Q2 culture (5 catégories)
 *  - Q3 couvert récolté/non, Q3 culture (précision sous_culture)
 *  - Q4 dates semis/destruction (picker JJ/MM), destruction -> inférence
 *    présence après le 01/01 pour l'interculture longue
 *  - apparition STRICTE une question à la fois
 *  - les vrais champs cascade (categorie_culture, sous_culture_form) + hidden
 *    inputs (occupation_sol, sous_culture, date_*) sont bien renseignés en coulisse.
 */

const REIMS_LNG = 4.0345;
const REIMS_LAT = 49.2583;

async function pickFlow(page: Page, name: string, index: number) {
  // Les radios du flow sont visibles : on clique le label par ordre d'apparition.
  const group = page.locator(`input[type=radio][name="${name}"]`);
  await expect(group.nth(index), `radio ${name}[${index}] absent`).toHaveCount(1);
  const id = await group.nth(index).getAttribute('id');
  await page.locator(`label[for="${id}"]`).first().click();
  await page.waitForTimeout(300);
}

async function hidden(page: Page, id: string): Promise<string> {
  return page.locator(`#${id}`).inputValue();
}

async function estVisible(page: Page, sel: string): Promise<boolean> {
  const loc = page.locator(sel);
  if ((await loc.count()) === 0) return false;
  return loc.isVisible();
}

test('#272 couvert interculture longue CINE, destruction avant 31/12', async ({ page }) => {
  await page.goto(`/simulateur/?lng=${REIMS_LNG}&lat=${REIMS_LAT}`);
  await page.waitForLoadState('networkidle');

  // Au départ : seule Q1 est visible ; Q2/Q3/Q4 masquées (apparition stricte).
  await expect(page.locator('#q_destination_epandage-wrapper')).toBeVisible();
  expect(await estVisible(page, '#q_type_couvert-wrapper')).toBeFalsy();
  expect(await estVisible(page, '#q_couvert_recolte-wrapper')).toBeFalsy();
  expect(await estVisible(page, '#q_dates_couvert-wrapper')).toBeFalsy();

  // Q1 : « Sur un couvert » (index 0 => valeur couvert).
  await pickFlow(page, 'cflow_destination', 0);
  await expect(page.locator('#q_type_couvert-wrapper')).toBeVisible();
  // Q3/Q4 toujours masquées.
  expect(await estVisible(page, '#q_couvert_recolte-wrapper')).toBeFalsy();

  // Q2 : interculture longue (index 0).
  await pickFlow(page, 'cflow_type_couvert', 0);
  await expect(page.locator('#q_couvert_recolte-wrapper')).toBeVisible();
  expect(await estVisible(page, '#q_dates_couvert-wrapper')).toBeFalsy();

  // Q3 : non récolté (index 1 => CINE).
  await pickFlow(page, 'cflow_couvert_recolte', 1);
  await expect(page.locator('#q_dates_couvert-wrapper')).toBeVisible();

  // Gating #272 : tant que les 2 dates ne sont pas saisies, le bouton reste
  // désactivé (Q4 marquée obligatoire).
  await expect(page.locator('#form-simulateur')).toHaveAttribute(
    'data-couvert-dates-incompletes',
    '1',
  );

  // Q4 : destruction avant 31/12 (ex 15/11) -> branche cine_avant_3112.
  await page.locator('#q_dates_couvert input[data-input-id="date_semis_couvert"]').fill('15/08');
  await page.locator('#q_dates_couvert input[data-input-id="date_semis_couvert"]').blur();
  await page.locator('#q_dates_couvert input[data-input-id="date_destruction_couvert"]').fill('15/11');
  await page.locator('#q_dates_couvert input[data-input-id="date_destruction_couvert"]').blur();
  await page.waitForTimeout(300);

  // Vérif du routage en coulisse.
  expect(await hidden(page, 'id_date_semis_couvert')).toBe('15/08');
  expect(await hidden(page, 'id_date_destruction_couvert')).toBe('15/11');
  expect(await hidden(page, 'id_occupation_sol')).toBe('couvert_intercultures');
  expect(await hidden(page, 'id_sous_culture')).toBe('cine_avant_3112');

  // Les 2 dates saisies -> gating levé.
  await expect(page.locator('#form-simulateur')).not.toHaveAttribute(
    'data-couvert-dates-incompletes',
    '1',
  );
});

test('#272 couvert longue CINE, destruction après 01/01 -> cine_apres_0101', async ({ page }) => {
  await page.goto(`/simulateur/?lng=${REIMS_LNG}&lat=${REIMS_LAT}`);
  await page.waitForLoadState('networkidle');

  await pickFlow(page, 'cflow_destination', 0); // couvert
  await pickFlow(page, 'cflow_type_couvert', 0); // longue
  await pickFlow(page, 'cflow_couvert_recolte', 1); // non récolté (CINE)
  await page.locator('#q_dates_couvert input[data-input-id="date_semis_couvert"]').fill('15/08');
  await page.locator('#q_dates_couvert input[data-input-id="date_destruction_couvert"]').fill('15/02');
  await page.locator('#q_dates_couvert input[data-input-id="date_destruction_couvert"]').blur();
  await page.waitForTimeout(300);

  // Destruction 15/02 (année agricole 2ᵉ moitié) => après le 01/01.
  expect(await hidden(page, 'id_sous_culture')).toBe('cine_apres_0101');
});

test('#272 culture principale : Q2 5 catégories, sol_non_cultivé en bas, Q3 précision', async ({ page }) => {
  await page.goto(`/simulateur/?lng=${REIMS_LNG}&lat=${REIMS_LAT}`);
  await page.waitForLoadState('networkidle');

  // Q1 : culture principale (index 2).
  await pickFlow(page, 'cflow_destination', 2);
  await expect(page.locator('#q_type_couvert-wrapper')).toBeVisible();

  // Q2 culture : 5 options, dernière = sol_non_cultivé.
  const labels = await page.locator('#q_type_couvert label').allTextContents();
  expect(labels.length).toBe(5);
  expect(labels[labels.length - 1].toLowerCase()).toContain('sol non cultiv');

  // On choisit culture d'hiver (index 0) -> Q3 précision (colza / autre).
  await pickFlow(page, 'cflow_type_couvert', 0);
  await expect(page.locator('#q_sous_culture-wrapper')).toBeVisible();
  await pickFlow(page, 'cflow_sous_culture', 0); // colza
  expect(await hidden(page, 'id_occupation_sol')).toBe('culture_principale');
  expect(await hidden(page, 'id_sous_culture')).toBe('colza');
});

test('#272 sol non cultivé : pas de Q3 précision, occupation_sol résolu direct', async ({ page }) => {
  await page.goto(`/simulateur/?lng=${REIMS_LNG}&lat=${REIMS_LAT}`);
  await page.waitForLoadState('networkidle');

  await pickFlow(page, 'cflow_destination', 2); // culture principale
  await pickFlow(page, 'cflow_type_couvert', 4); // sol_non_cultivé (dernier)
  // Pas de question précision.
  expect(await estVisible(page, '#q_sous_culture-wrapper')).toBeFalsy();
  expect(await hidden(page, 'id_occupation_sol')).toBe('sol_non_cultive');
});
