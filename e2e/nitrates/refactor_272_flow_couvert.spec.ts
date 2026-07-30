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
  // Titre Q2 en mode couvert.
  await expect(page.locator('#q_type_couvert-label')).toContainText(
    'Quel type de couvert',
  );
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

test('#272 date-picker : le calendrier s ouvre et un jour est cliquable (fix clipping)', async ({ page }) => {
  await page.goto(`/simulateur/?lng=${REIMS_LNG}&lat=${REIMS_LAT}`);
  await page.waitForLoadState('networkidle');

  await pickFlow(page, 'cflow_destination', 0); // couvert
  await pickFlow(page, 'cflow_type_couvert', 0); // longue
  await pickFlow(page, 'cflow_couvert_recolte', 0); // récolté

  // Ouvre le picker du semis en cliquant l'input.
  await page.locator('#q_dates_couvert input[data-input-id="date_semis_couvert"]').click();
  // Le popup est ancré sur <body> en position:fixed -> visible et non clippé.
  const popup = page.locator('.calc-cal__picker--fixed');
  await expect(popup).toBeVisible();
  // Le picker s'ouvre sur le MOIS DU PLACEHOLDER (semis 15/08 -> Août), pas janvier.
  await expect(popup.locator('[data-mois-label]')).toHaveText('Août');
  // Un jour de la grille est cliquable (le bug : la grille etait masquee).
  const jour10 = popup.locator('.calc-cal__picker-day[data-jour="10"]');
  await expect(jour10).toBeVisible();
  await jour10.click();

  // La valeur saisie reflete le jour clique dans le mois du placeholder (août = 08).
  const v = await page.locator('#q_dates_couvert input[data-input-id="date_semis_couvert"]').inputValue();
  expect(v).toBe('10/08');
  expect(await hidden(page, 'id_date_semis_couvert')).toBe(v);
});

test('#272 label sol_non_cultivé porte la parenthèse explicative', async ({ page }) => {
  await page.goto(`/simulateur/?lng=${REIMS_LNG}&lat=${REIMS_LAT}`);
  await page.waitForLoadState('networkidle');
  await pickFlow(page, 'cflow_destination', 2); // culture principale
  const dernier = page.locator('#q_type_couvert label').last();
  await expect(dernier).toContainText('Sol non cultivé');
  await expect(dernier).toContainText('surface non utilisée en vue d');
});

test('#272 culture principale : Q2 5 catégories, sol_non_cultivé en bas, Q3 précision', async ({ page }) => {
  await page.goto(`/simulateur/?lng=${REIMS_LNG}&lat=${REIMS_LAT}`);
  await page.waitForLoadState('networkidle');

  // Q1 : culture principale (index 2).
  await pickFlow(page, 'cflow_destination', 2);
  await expect(page.locator('#q_type_couvert-wrapper')).toBeVisible();
  // Le titre de Q2 s'adapte : « catégorie de culture principale », pas « couvert ».
  await expect(page.locator('#q_type_couvert-label')).toContainText(
    'Quelle catégorie de culture principale',
  );

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

test('#272 page résultat : dates dégagées du form gauche, bandeau + titre + labels courts à droite', async ({ page }) => {
  // Résultat couvert longue CINE avant 31/12, type Ia + plan épandage autorisation
  // -> feuille calculatrice avec calendrier dynamique (composant + inputs dates).
  const url =
    `/simulateur/?lng=${REIMS_LNG}&lat=${REIMS_LAT}` +
    '&categorie_culture=couvert_intercultures_longue' +
    '&sous_culture_form=couvert_non_recolte_plus_en_place_apres_3112' +
    '&occupation_sol=couvert_intercultures&sous_culture=cine_avant_3112' +
    '&date_semis_couvert=15/08&date_destruction_couvert=15/11' +
    '&categorie_fertilisant=fumiers&sous_fertilisant=fumier_volaille&type_fertilisant=type_Ia' +
    '&plan_epandage=icpe_a';
  await page.goto(url);
  await page.waitForLoadState('networkidle');

  // Page résultat (colonne split).
  await expect(page.locator('.results-row.layout--split')).toBeVisible();

  // Doublon supprimé : les dates Q4 du formulaire GAUCHE sont masquées.
  await expect(page.locator('#q_dates_couvert-wrapper')).toBeHidden();

  // À DROITE : le calendrier dynamique porte le bandeau violet + le titre
  // d'intro, avec les libellés COURTS d'origine (1 ligne).
  const highlight = page.locator('[data-calc-cal-root] .calc-cal__form--highlight');
  await expect(highlight).toBeVisible();
  await expect(highlight.locator('.calc-cal__form-titre')).toContainText(
    'Jouer avec les dates du couvert',
  );
  const labels = await highlight.locator('.calc-cal__field-label').allTextContents();
  expect(labels).toContain('Date de semis du couvert');
  expect(labels).toContain('Date de destruction du couvert');
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

test('#272 dates Q4 vides : encadré rouge (aria-invalid), pas de placeholder gris, « Suivant » désactivé', async ({ page }) => {
  await page.goto(`/simulateur/?lng=${REIMS_LNG}&lat=${REIMS_LAT}`);
  await page.waitForLoadState('networkidle');
  await pickFlow(page, 'cflow_destination', 0); // couvert
  await pickFlow(page, 'cflow_type_couvert', 0); // longue
  await pickFlow(page, 'cflow_couvert_recolte', 0); // récolté -> Q4 apparaît

  const semis = page.locator('#q_dates_couvert input[data-input-id="date_semis_couvert"]');
  const destr = page.locator('#q_dates_couvert input[data-input-id="date_destruction_couvert"]');
  // Champs VIDES (pas de valeur pré-remplie « 15/08 » grise) + aria-invalid.
  expect(await semis.inputValue()).toBe('');
  await expect(semis).toHaveAttribute('aria-invalid', 'true');
  await expect(destr).toHaveAttribute('aria-invalid', 'true');
  // Le gating bloque tant que les 2 dates ne sont pas saisies.
  await expect(page.locator('#form-simulateur')).toHaveAttribute(
    'data-couvert-dates-incompletes',
    '1',
  );

  // Une fois le semis saisi, son encadré rouge disparaît (mais destruction reste).
  await semis.fill('15/08');
  await semis.blur();
  await expect(semis).not.toHaveAttribute('aria-invalid', 'true');
  await expect(destr).toHaveAttribute('aria-invalid', 'true');
});

test('#272 auto-scroll : après saisie des dates, on scrolle vers la section Fertilisant', async ({ page }) => {
  // Page chargée AVEC lat/lng (cas où l'ancien code désactivait l'auto-scroll
  // en dur -> régression corrigée #272).
  await page.goto(`/simulateur/?lat=49.05&lng=3.97`);
  await page.waitForLoadState('networkidle');

  // On trace les cibles de scrollIntoView.
  await page.evaluate(() => {
    (window as any).__scrollTargets = [];
    const orig = Element.prototype.scrollIntoView;
    (Element.prototype as any).scrollIntoView = function (...a: any[]) {
      (window as any).__scrollTargets.push(this.id || this.className);
      return orig.apply(this, a);
    };
  });

  await pickFlow(page, 'cflow_destination', 0);
  await pickFlow(page, 'cflow_type_couvert', 0);
  await pickFlow(page, 'cflow_couvert_recolte', 0);
  // Saisie des 2 dates -> révèle la section fertilisant.
  const semis = page.locator('#q_dates_couvert input[data-input-id="date_semis_couvert"]');
  await semis.fill('15/08');
  await semis.blur();
  await page.waitForTimeout(300);
  const destr = page.locator('#q_dates_couvert input[data-input-id="date_destruction_couvert"]');
  await destr.fill('15/11');
  await destr.blur();
  await page.waitForTimeout(500);

  // On a bien scrollé vers la section Fertilisant après les dates.
  const targets = await page.evaluate(() => (window as any).__scrollTargets as string[]);
  expect(targets).toContain('section-fertilisant');

  // Puis choix de la catégorie de fertilisant -> scroll vers la sous-question.
  await page.evaluate(() => ((window as any).__scrollTargets = []));
  await pickFlow(page, 'categorie_fertilisant', 1); // lisiers (a des sous-fertilisants)
  await page.waitForTimeout(400);
  const targets2 = await page.evaluate(() => (window as any).__scrollTargets as string[]);
  expect(targets2).toContain('sous_fertilisant-wrapper');
});

test('#272 note picker destruction : affichée seulement sur un mois avec jours indispo', async ({ page }) => {
  // Résultat couvert avant 31/12 (destruction bornée max 31/12).
  const url =
    `/simulateur/?lng=${REIMS_LNG}&lat=${REIMS_LAT}` +
    '&categorie_culture=couvert_intercultures_longue' +
    '&sous_culture_form=couvert_non_recolte_plus_en_place_apres_3112' +
    '&occupation_sol=couvert_intercultures&sous_culture=cine_avant_3112' +
    '&date_semis_couvert=15/08&date_destruction_couvert=15/11' +
    '&categorie_fertilisant=fumiers&sous_fertilisant=fumier_volaille&type_fertilisant=type_Ia' +
    '&plan_epandage=icpe_a';
  await page.goto(url);
  await page.waitForLoadState('networkidle');
  await page.locator('[data-calc-cal-root] input[data-input-id="date_destruction_couvert"]').click();
  await page.waitForTimeout(300);

  // Novembre (tout dispo) : la note est masquée.
  await expect(page.locator('[data-calc-cal-root] [data-mois-label]')).toHaveText('Novembre');
  await expect(page.locator('.calc-cal__picker-note')).toBeHidden();

  // On avance jusqu'à janvier (jours indispo -> après le 31/12) : note visible.
  await page.locator('.calc-cal__picker-nav[data-nav="next"]').click(); // décembre
  await page.waitForTimeout(120);
  await page.locator('.calc-cal__picker-nav[data-nav="next"]').click(); // janvier
  await page.waitForTimeout(150);
  await expect(page.locator('[data-calc-cal-root] [data-mois-label]')).toHaveText('Janvier');
  await expect(page.locator('.calc-cal__picker-note')).toBeVisible();
  await expect(page.locator('.calc-cal__picker-note')).toContainText('recommencez une simulation');
});

test('#272 result page : changer une question du flow invalide le résultat et repasse en saisie', async ({ page }) => {
  // Résultat couvert longue CINE avant 31/12 (URL directe -> résultat affiché).
  const url =
    `/simulateur/?lng=${REIMS_LNG}&lat=${REIMS_LAT}` +
    '&categorie_culture=couvert_intercultures_longue' +
    '&sous_culture_form=couvert_non_recolte_plus_en_place_apres_3112' +
    '&occupation_sol=couvert_intercultures&sous_culture=cine_avant_3112' +
    '&date_semis_couvert=15/08&date_destruction_couvert=15/11' +
    '&categorie_fertilisant=fumiers&sous_fertilisant=fumier_volaille&type_fertilisant=type_Ia' +
    '&plan_epandage=icpe_a';
  await page.goto(url);
  await page.waitForLoadState('networkidle');
  await expect(page.locator('.results-row.layout--split')).toBeVisible();
  await expect(page.locator('#form-simulateur')).toHaveAttribute('data-resultat-affiche', '1');

  // L'utilisateur change la question récolté (non récolté -> récolté).
  await pickFlow(page, 'cflow_couvert_recolte', 0); // récolté

  // Le résultat est invalidé : plus de colonne résultat, retour en mode saisie.
  await expect(page.locator('.result-col')).toHaveCount(0);
  await expect(page.locator('#form-simulateur')).not.toHaveAttribute('data-resultat-affiche', '1');
  // Le bouton « Lancer la simulation » est de nouveau visible.
  await expect(page.locator('#form-submit-row')).toBeVisible();
  // Les dates Q4 réapparaissent à gauche pour re-compléter un parcours cohérent.
  await expect(page.locator('#q_dates_couvert-wrapper')).toBeVisible();
});
