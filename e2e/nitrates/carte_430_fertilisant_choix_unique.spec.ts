import { test, expect, Page } from '@playwright/test';

/**
 * #430 bug 1 (requalifié en feature) : quand une catégorie de fertilisant ne
 * propose qu'UN seul sous-fertilisant (cas « engrais minéral » -> « engrais
 * azoté minéral »), la 2ᵉ question n'a pas de sens pour l'utilisateur. On la
 * saute côté FRONT uniquement : le radio est coché d'office et part toujours
 * dans le formulaire / l'URL (aucun changement de contrat backend).
 *
 * Side-effects explicitement demandés sur la carte et couverts ici : retour
 * « modifier » depuis le résultat, URL directes existantes, reload de page.
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

// ─────────────────────────────────────────────────────────────────────────────
// Bug 1 — question sous_fertilisant sautée quand il n'y a qu'un seul choix
// ─────────────────────────────────────────────────────────────────────────────

test("#430 bug 1 : catégorie de fertilisant à choix unique -> la 2ᵉ question est sautée mais la valeur part quand même", async ({
  page,
}) => {
  // Parcours de la carte : culture principale > culture de printemps > autre
  // que maïs, puis fertilisant « engrais minéral » (1 seul sous-fertilisant).
  await page.goto(`/simulateur/?lng=${REIMS_LNG}&lat=${REIMS_LAT}`);
  await page.waitForLoadState('networkidle');

  await pickFlow(page, 'cflow_destination', 2); // Sur une culture principale
  await pickFlow(page, 'cflow_type_couvert', 1); // culture de printemps
  await expect(page.locator('#q_sous_culture-wrapper')).toBeVisible();
  await pickFlow(page, 'cflow_sous_culture', 1); // autre que maïs

  // La 1ʳᵉ question fertilisant (la catégorie) est bien posée.
  await expect(page.locator('#categorie_fertilisant-wrapper')).toBeVisible();

  // Contrôle négatif d'abord : une catégorie à PLUSIEURS sous-fertilisants
  // continue de poser la 2ᵉ question (on ne saute pas tout le monde).
  await pickCascade(page, 'categorie_fertilisant', 'fumiers');
  await expect(page.locator('#sous_fertilisant-wrapper')).toBeVisible();
  const nbFumiers = await page
    .locator('input[type=radio][name="sous_fertilisant"]')
    .count();
  expect(nbFumiers).toBeGreaterThan(1);

  // Cas de la carte : engrais minéral -> 1 seul sous-fertilisant.
  await pickCascade(page, 'categorie_fertilisant', 'engrais_mineral');

  // La question n'est PLUS affichée...
  await expect(page.locator('#sous_fertilisant-wrapper')).toBeHidden();

  // ... mais la réponse est bien cochée en coulisse (elle partira dans le GET),
  // et le hidden type_fertilisant a été résolu à partir d'elle.
  expect(await radioCoche(page, 'sous_fertilisant')).toBe('engrais_azote_mineral');
  expect(await hidden(page, 'id_type_fertilisant')).toBe('type_III');

  // Le parcours est considéré complet : le bouton de soumission est actif
  // (le gating ne réclame que les questions VISIBLES).
  const submit = page.locator('#form-submit-row button[type=submit]');
  await expect(submit).toBeEnabled();

  // Et la valeur sautée arrive réellement au serveur : elle est dans l'URL.
  await submit.click();
  await page.waitForLoadState('networkidle');
  const url = new URL(page.url());
  expect(url.searchParams.get('sous_fertilisant')).toBe('engrais_azote_mineral');
  expect(url.searchParams.get('categorie_fertilisant')).toBe('engrais_mineral');
  expect(url.searchParams.get('type_fertilisant')).toBe('type_III');
});

test("#430 bug 1 : au rechargement d'une URL directe, la question à choix unique reste sautée et la valeur est conservée", async ({
  page,
}) => {
  // Side-effect explicitement demandé sur la carte : « URL directes existantes
  // non cassées » + « reload de page ». On rejoue l'URL complète.
  const url =
    `/simulateur/?lng=${REIMS_LNG}&lat=${REIMS_LAT}` +
    '&categorie_culture=culture_printemps' +
    '&sous_culture_form=culture_principale_printemps_autre_que_mais' +
    '&occupation_sol=culture_principale&sous_culture=culture_printemps' +
    '&categorie_fertilisant=engrais_mineral' +
    '&sous_fertilisant=engrais_azote_mineral&type_fertilisant=type_III';
  await page.goto(url);
  await page.waitForLoadState('networkidle');
  await ouvrirFormulaireSiReplie(page);

  // Question toujours sautée, réponse toujours cochée, hidden toujours résolu.
  await expect(page.locator('#sous_fertilisant-wrapper')).toBeHidden();
  expect(await radioCoche(page, 'sous_fertilisant')).toBe('engrais_azote_mineral');
  expect(await hidden(page, 'id_type_fertilisant')).toBe('type_III');
  // La catégorie, elle, reste une vraie question visible et cochée.
  await expect(page.locator('#categorie_fertilisant-wrapper')).toBeVisible();
  expect(await radioCoche(page, 'categorie_fertilisant')).toBe('engrais_mineral');
});
