import { test, expect, Page } from '@playwright/test';

/**
 * #430 bug 3 : Q1 pose 4 réponses pour 2 valeurs métier (« sur X » / « juste
 * avant X »). Elles partageaient la même `value`, donc au retour « modifier »
 * depuis le résultat (ou au landing sur une URL partagée) on recochait
 * toujours la 1ʳᵉ -> « juste avant une culture principale » se transformait en
 * « Sur une culture principale ».
 */

const REIMS_LNG = 4.0345;
const REIMS_LAT = 49.2583;

/**
 * #271 : sur la page de resultat le formulaire est replie derriere l'encart
 * recap. On rouvre d'abord, comme l'utilisateur. Idempotent.
 */
async function ouvrirFormulaireSiReplie(page: Page) {
  const formApres = page.locator('#form-after-localisation');
  if ((await formApres.count()) === 0) return;
  if (await formApres.isVisible()) return;
  await page.locator('[data-recap-modifier]').first().click({ force: true });
  await expect(formApres).toBeVisible();
}

async function pickFlow(page: Page, name: string, index: number) {
  await ouvrirFormulaireSiReplie(page);
  const group = page.locator(`input[type=radio][name="${name}"]`);
  await expect(group.nth(index), `radio ${name}[${index}] absent`).toHaveCount(1);
  const id = await group.nth(index).getAttribute('id');
  await page.locator(`label[for="${id}"]`).first().click();
  await page.waitForTimeout(300);
}

/** Clique un radio cascade (rendu dynamiquement par cascade.js) par sa valeur. */
async function pickCascade(page: Page, name: string, value: string) {
  await ouvrirFormulaireSiReplie(page);
  const radio = page.locator(`input[type=radio][name="${name}"][value="${value}"]`);
  await expect(radio, `radio ${name}=${value} absent`).toHaveCount(1);
  const id = await radio.getAttribute('id');
  await page.locator(`label[for="${id}"]`).first().click();
  await page.waitForTimeout(300);
}

async function hidden(page: Page, id: string): Promise<string> {
  return page.locator(`#${id}`).inputValue();
}

/** Valeur du radio actuellement coché d'un groupe (chaîne vide si aucun). */
async function radioCoche(page: Page, name: string): Promise<string> {
  const coche = page.locator(`input[type=radio][name="${name}"]:checked`);
  if ((await coche.count()) === 0) return '';
  return (await coche.getAttribute('value')) || '';
}

/** Libellé du radio actuellement coché (ce que l'utilisateur voit à l'écran). */
async function labelCoche(page: Page, name: string): Promise<string> {
  const id = await page
    .locator(`input[type=radio][name="${name}"]:checked`)
    .getAttribute('id');
  return (await page.locator(`label[for="${id}"]`).textContent())?.trim() || '';
}

// ─────────────────────────────────────────────────────────────────────────────
// Bug 3 — « juste avant une culture principale » ne doit pas devenir « sur »
// ─────────────────────────────────────────────────────────────────────────────

test('#430 bug 3 : « juste avant une culture principale » survit au retour « modifier » depuis le résultat', async ({
  page,
}) => {
  await page.goto(`/simulateur/?lng=${REIMS_LNG}&lat=${REIMS_LAT}`);
  await page.waitForLoadState('networkidle');

  // Q1 index 3 = « Juste avant l'implantation d'une culture principale ».
  await pickFlow(page, 'cflow_destination', 3);
  const labelChoisi = await labelCoche(page, 'cflow_destination');
  expect(labelChoisi.toLowerCase()).toContain('juste avant');
  // Même réponse -> même branche métier qu'un « sur une culture principale ».
  expect(await radioCoche(page, 'cflow_destination')).toBe(
    'culture_principale_avant',
  );

  await pickFlow(page, 'cflow_type_couvert', 1); // culture de printemps
  await pickFlow(page, 'cflow_sous_culture', 1); // autre que maïs
  expect(await hidden(page, 'id_occupation_sol')).toBe('culture_principale');

  await pickCascade(page, 'categorie_fertilisant', 'engrais_mineral');

  const submit = page.locator('#form-submit-row button[type=submit]');
  await expect(submit).toBeEnabled();
  await submit.click();
  await page.waitForLoadState('networkidle');

  // Retour en saisie via « modifier » : c'est là que la réponse basculait.
  await ouvrirFormulaireSiReplie(page);
  expect(await radioCoche(page, 'cflow_destination')).toBe(
    'culture_principale_avant',
  );
  const labelApres = await labelCoche(page, 'cflow_destination');
  expect(labelApres.toLowerCase()).toContain('juste avant');
  expect(labelApres).toBe(labelChoisi);
});

test("#430 bug 3 : « juste avant » survit aussi au landing direct sur l'URL partagée", async ({
  page,
}) => {
  // Cas signalé sur la carte : « doit sûrement aussi arriver sur landing direct
  // de l'URL ». On rejoue une URL portant la réponse Q1 exacte.
  const base =
    `/simulateur/?lng=${REIMS_LNG}&lat=${REIMS_LAT}` +
    '&categorie_culture=culture_printemps' +
    '&sous_culture_form=culture_principale_printemps_autre_que_mais' +
    '&occupation_sol=culture_principale&sous_culture=culture_printemps' +
    '&categorie_fertilisant=engrais_mineral' +
    '&sous_fertilisant=engrais_azote_mineral&type_fertilisant=type_III';

  await page.goto(`${base}&cflow_destination=culture_principale_avant`);
  await page.waitForLoadState('networkidle');
  await ouvrirFormulaireSiReplie(page);
  expect(await radioCoche(page, 'cflow_destination')).toBe(
    'culture_principale_avant',
  );
  expect((await labelCoche(page, 'cflow_destination')).toLowerCase()).toContain(
    'juste avant',
  );

  // Et la réponse « sur » reste bien distincte (on n'a pas juste inversé le bug).
  await page.goto(`${base}&cflow_destination=culture_principale_sur`);
  await page.waitForLoadState('networkidle');
  await ouvrirFormulaireSiReplie(page);
  expect(await radioCoche(page, 'cflow_destination')).toBe(
    'culture_principale_sur',
  );
  expect(
    (await labelCoche(page, 'cflow_destination')).toLowerCase(),
  ).not.toContain('juste avant');
});

test('#430 bug 3 : une URL antérieure au fix reste exploitable (rétro-compat)', async ({
  page,
}) => {
  // Les liens déjà partagés portent `cflow_destination=culture_principale`.
  // Ils doivent continuer à ouvrir la bonne branche ; seule la distinction
  // sur/avant est perdue (on retombe sur « Sur une culture principale »).
  const url =
    `/simulateur/?lng=${REIMS_LNG}&lat=${REIMS_LAT}` +
    '&categorie_culture=culture_printemps' +
    '&sous_culture_form=culture_principale_printemps_autre_que_mais' +
    '&occupation_sol=culture_principale&sous_culture=culture_printemps' +
    '&cflow_destination=culture_principale';
  await page.goto(url);
  await page.waitForLoadState('networkidle');
  await ouvrirFormulaireSiReplie(page);

  expect(await radioCoche(page, 'cflow_destination')).toBe(
    'culture_principale_sur',
  );
  // La suite du parcours est bien rejouée (Q2/Q3 cochées).
  expect(await radioCoche(page, 'cflow_type_couvert')).toBe('culture_printemps');
  expect(await hidden(page, 'id_occupation_sol')).toBe('culture_principale');
});
