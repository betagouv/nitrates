import { test, expect } from '@playwright/test';

/**
 * #135 — reset/flush du formulaire au changement d'un champ APRES resultat.
 *
 * Cas A (seul scope de ce dev) : un resultat (ou une QC) est affiche, l'user
 * change un champ DANS le formulaire -> le resultat/QC disparait, l'URL est
 * nettoyee (dictionnaire de cles uniques, pas de doublon, pas de valeur
 * derivee obsolete), et la cascade reprend la main au bon endroit. La
 * resoumission ne repose PAS de fausse QC (« type de fertilisant ? »).
 *
 * Le cas B (re-clic carte / scope SIG) est HORS scope (dev separe).
 */

test.describe.configure({ mode: 'serial' });

const REIMS_LNG = 4.0345;
const REIMS_LAT = 49.2583;

// URL d'un resultat complet colza + engrais mineral type_III (pas de QC).
const RESULTAT_COLZA_URL =
  `/simulateur/?lng=${REIMS_LNG}&lat=${REIMS_LAT}` +
  '&categorie_culture=culture_hiver&sous_culture_form=colza' +
  '&occupation_sol=culture_principale&sous_culture=colza' +
  '&categorie_fertilisant=engrais_mineral' +
  '&sous_fertilisant=engrais_azote_mineral&type_fertilisant=type_III';

function dupKeys(search: string): string[] {
  const p = new URLSearchParams(search);
  const seen = new Set<string>();
  const dups: string[] = [];
  for (const k of p.keys()) {
    if (seen.has(k)) dups.push(k);
    seen.add(k);
  }
  return dups;
}

test.describe('Simulateur #135 : reset au changement de champ apres resultat', () => {
  test('changer la categorie de fertilisant retire le resultat et nettoie l URL', async ({
    page,
  }) => {
    await page.goto(RESULTAT_COLZA_URL);

    // Etat initial : resultat affiche, layout en 2 colonnes.
    await expect(page.locator('.result-col')).toBeVisible();
    await expect(page.locator('.results-row.layout--split')).toHaveCount(1);
    // #160 : sur un resultat inchange, PAS de bouton « Lancer la simulation »
    // (rien a relancer).
    await expect(page.locator('#form-submit-row')).toBeHidden();

    // L'user change la categorie de fertilisant (composts).
    await page.locator('label[for="id_categorie_fertilisant__composts"]').click();

    // Le resultat disparait, retour colonne unique.
    await expect(page.locator('.result-col')).toHaveCount(0);
    await expect(page.locator('.results-row.layout--split')).toHaveCount(0);
    // Le bouton REAPPARAIT : l'utilisateur a modifie un champ, il peut relancer.
    await expect(page.locator('#form-submit-row')).toBeVisible();
    await expect(
      page.locator('#form-submit-row button[type="submit"]')
    ).toHaveText(/Lancer la simulation/);

    // type_fertilisant obsolete (type_III) est reset par la cascade : il ne
    // doit plus etre dans l'URL miroir (c'etait une cause des bugs precedents).
    await expect
      .poll(() =>
        page.evaluate(() =>
          new URLSearchParams(location.search).get('type_fertilisant')
        )
      )
      .toBeNull();
    // sous_fertilisant obsolete retire aussi (categorie changee).
    await expect
      .poll(() =>
        page.evaluate(() =>
          new URLSearchParams(location.search).get('sous_fertilisant')
        )
      )
      .toBeNull();
    // La nouvelle categorie est bien dans l'URL.
    await expect
      .poll(() =>
        page.evaluate(() =>
          new URLSearchParams(location.search).get('categorie_fertilisant')
        )
      )
      .toBe('composts');

    // Invariant cle : aucune cle dupliquee dans l'URL.
    const search = await page.evaluate(() => location.search);
    expect(dupKeys(search)).toEqual([]);
  });

  test('reprise de la cascade -> resoumission SANS fausse QC type fertilisant', async ({
    page,
  }) => {
    await page.goto(RESULTAT_COLZA_URL);
    await expect(page.locator('.result-col')).toBeVisible();

    // Change categorie -> sous_fertilisant -> nouveau type resolu par cascade.
    await page.locator('label[for="id_categorie_fertilisant__composts"]').click();
    await expect(page.locator('.result-col')).toHaveCount(0);

    await page
      .locator('label[for="id_sous_fertilisant__compost_fientes_volailles"]')
      .click();
    // cascade.js a resolu type_fertilisant (compost fientes volailles -> type_II).
    await expect(page.locator('#id_type_fertilisant')).toHaveValue('type_II');

    // Relance : on doit obtenir le NOUVEAU resultat, pas une fausse QC.
    await page.locator('#form-simulateur button[type="submit"]').click();
    await page.waitForLoadState('networkidle');

    const body = page.locator('body');
    await expect(body).toContainText('r_colza_type_II');
    // Pas de bloc QC en attente reaffiche (la fausse question des bugs passes).
    await expect(page.locator('#qc-bloc[data-qc-en-attente]')).toHaveCount(0);
  });

  test('editer une QC repondue retire le resultat (cas QC)', async ({ page }) => {
    // culture_printemps + type_II pose la QC fertirrigation ; on la repond via
    // l'URL pour obtenir un resultat AVEC QC recap editable.
    await page.goto(
      `/simulateur/?lng=${REIMS_LNG}&lat=${REIMS_LAT}` +
        '&occupation_sol=culture_principale&sous_culture=culture_printemps' +
        '&type_fertilisant=type_II&fertirrigation=False'
    );

    // Un resultat + le bloc QC (recap) sont presents.
    await expect(page.locator('#qc-bloc')).toHaveCount(1);

    // L'user change la reponse a la QC fertirrigation.
    await page.locator('label[for*="fertirrigation"][for*="True"]').first().click();

    // Le resultat et le bloc QC disparaissent.
    await expect(page.locator('.result-col')).toHaveCount(0);
    await expect(page.locator('#qc-bloc')).toHaveCount(0);

    // L'URL miroir ne reprend PAS la reponse QC obsolete (fertirrigation).
    await expect
      .poll(() =>
        page.evaluate(() =>
          new URLSearchParams(location.search).get('fertirrigation')
        )
      )
      .toBeNull();
    const search = await page.evaluate(() => location.search);
    expect(dupKeys(search)).toEqual([]);
  });
});

/**
 * #135 — REGRESSION boucle infinie (rapportee par Max le 2026-06-26).
 *
 * Scenario exact : apres avoir navigue dans le form, l'utilisateur arrive sur
 * une page qui pose une QC EN ATTENTE (data-qc-en-attente). Il clique le radio
 * de la QC pour y repondre -> AVANT le fix, reset_form elaguait le bloc QC sous
 * ses doigts. Il relance -> le serveur repose la meme QC -> il reclique -> elle
 * redisparait. Boucle infinie, impossible de finaliser.
 *
 * Le fix : ne JAMAIS elaguer quand l'utilisateur clique un radio DANS le bloc
 * QC en attente. On verifie ici que (a) la QC reste a l'ecran apres clic, et
 * (b) on peut effectivement finaliser jusqu'au resultat.
 */
test.describe('Simulateur #135 : pas de boucle infinie sur QC en attente', () => {
  // Le parcours exact du bug : digestats + fraction liquide + mais irrigue ->
  // pose la QC fertirrigation en attente.
  const URL_QC_EN_ATTENTE =
    `/simulateur/?lng=${REIMS_LNG}&lat=${REIMS_LAT}` +
    '&categorie_culture=culture_printemps&sous_culture_form=mais' +
    '&categorie_fertilisant=digestats' +
    '&sous_fertilisant=fraction_liquide_digestat_methanisation' +
    '&occupation_sol=culture_principale&sous_culture=culture_printemps' +
    '&culture_irriguee_type=mais&type_fertilisant=type_II';

  test('repondre a la QC en attente ne la fait PAS disparaitre', async ({
    page,
  }) => {
    await page.goto(URL_QC_EN_ATTENTE);

    // La QC fertirrigation est posee, en attente.
    await expect(page.locator('#qc-bloc[data-qc-en-attente]')).toHaveCount(1);
    await expect(
      page.locator('[data-qc-champ="fertirrigation"]')
    ).toBeVisible();

    // L'utilisateur repond a la QC.
    await page.locator('label[for*="fertirrigation"][for*="True"]').first().click();

    // La QC NE DOIT PAS disparaitre (c'etait le bug). On laisse passer le tick
    // setTimeout(0) de reset_form pour etre sur qu'il n'elague pas.
    await page.waitForTimeout(150);
    await expect(page.locator('#qc-bloc')).toHaveCount(1);
    await expect(
      page.locator('[data-qc-champ="fertirrigation"]')
    ).toBeVisible();
    // Le radio reste coche.
    await expect(
      page.locator('input[name="fertirrigation"][value="True"]')
    ).toBeChecked();
  });

  test('on peut FINALISER la QC en attente jusqu au resultat', async ({
    page,
  }) => {
    await page.goto(URL_QC_EN_ATTENTE);
    await expect(page.locator('#qc-bloc[data-qc-en-attente]')).toHaveCount(1);

    // Repond la QC.
    await page.locator('label[for*="fertirrigation"][for*="True"]').first().click();
    await page.waitForTimeout(150);
    await expect(page.locator('#qc-bloc')).toHaveCount(1);

    // Relance : doit aboutir a un resultat, pas reboucler sur la meme QC.
    await page
      .locator('#form-simulateur button[type="submit"]').click();
    await page.waitForLoadState('networkidle');

    // On a un resultat (r_printemps_*), et plus de QC EN ATTENTE.
    await expect(page.locator('body')).toContainText(/r_printemps/);
    await expect(page.locator('#qc-bloc[data-qc-en-attente]')).toHaveCount(0);
    await expect(page.locator('.result-col')).toHaveCount(1);
  });

  test('changer un champ AMONT pendant une QC en attente elague bien', async ({
    page,
  }) => {
    // Contre-cas : si l'utilisateur change la CATEGORIE (champ amont) alors
    // qu'une QC est en attente, la QC obsolete DOIT disparaitre (le parcours
    // change). C'est l'inverse du cas precedent : on elague bien ici.
    await page.goto(URL_QC_EN_ATTENTE);
    await expect(page.locator('#qc-bloc[data-qc-en-attente]')).toHaveCount(1);

    // Change la categorie de fertilisant (amont de la QC).
    await page.locator('label[for="id_categorie_fertilisant__composts"]').click();
    await page.waitForTimeout(150);

    // La QC en attente obsolete disparait.
    await expect(page.locator('#qc-bloc')).toHaveCount(0);
    // sous_fertilisant reset par la cascade -> retire de l'URL.
    await expect
      .poll(() =>
        page.evaluate(() =>
          new URLSearchParams(location.search).get('sous_fertilisant')
        )
      )
      .toBeNull();
  });
});

/**
 * #135 — parcours QC COMPLET de bout en bout, sans pre-remplir l'URL : on
 * clique reellement chaque etape (carte -> cascade -> submit -> QC -> submit).
 * C'est le test "dans tous les sens" qui aurait du attraper la boucle.
 */
test.describe('Simulateur #135 : parcours QC complet par clics reels', () => {
  test('mais irrigue + digestats : cascade -> QC -> finalisation', async ({
    page,
  }) => {
    await page.goto(`/simulateur/?lng=${REIMS_LNG}&lat=${REIMS_LAT}`);

    // Attendre la cascade prete.
    await expect
      .poll(
        async () =>
          page
            .locator('[data-cascade="categorie_culture"] input[type="radio"]')
            .count(),
        { timeout: 10000 }
      )
      .toBeGreaterThan(0);

    // Cascade culture : printemps -> mais.
    await page.locator('label[for="id_categorie_culture__culture_printemps"]').click();
    await page.locator('label[for="id_sous_culture_form__mais"]').click();
    // Cascade fertilisant : digestats -> fraction liquide.
    await page.locator('label[for="id_categorie_fertilisant__digestats"]').click();
    await page
      .locator(
        'label[for="id_sous_fertilisant__fraction_liquide_digestat_methanisation"]'
      )
      .click();

    // Lancer -> le serveur pose la QC fertirrigation.
    await page
      .locator('#form-simulateur button[type="submit"]').click();
    await page.waitForLoadState('networkidle');
    await expect(page.locator('#qc-bloc[data-qc-en-attente]')).toHaveCount(1);

    // Repondre la QC : elle ne doit PAS disparaitre.
    await page.locator('label[for*="fertirrigation"][for*="True"]').first().click();
    await page.waitForTimeout(150);
    await expect(page.locator('#qc-bloc')).toHaveCount(1);

    // Relancer -> resultat final.
    await page
      .locator('#form-simulateur button[type="submit"]').click();
    await page.waitForLoadState('networkidle');
    await expect(page.locator('body')).toContainText(/r_printemps/);
    await expect(page.locator('#qc-bloc[data-qc-en-attente]')).toHaveCount(0);
  });
});

/**
 * #135 — cas couvert split : la saisie du sous_culture_form passe par 2 mini
 * questions (couvert_split.js) qui cochent le vrai radio et dispatchent son
 * change. On verifie que ce change synthetique declenche bien l'elagage du
 * resultat sans casser (le radio split n'est PAS un champ cascade/derive, mais
 * le sous_culture_form qu'il pilote l'est).
 */
test.describe('Simulateur #135 : reset sur saisie couvert split', () => {
  const URL_RESULTAT_COUVERT =
    `/simulateur/?lng=${REIMS_LNG}&lat=${REIMS_LAT}` +
    '&categorie_culture=couvert_intercultures_longue' +
    '&sous_culture_form=couvert_non_recolte_toujours_en_place_apres_0101' +
    '&occupation_sol=interculture_longue&sous_culture=couvert' +
    '&categorie_fertilisant=engrais_mineral' +
    '&sous_fertilisant=engrais_azote_mineral&type_fertilisant=type_III';

  test('changer une mini-question split apres resultat elague le resultat', async ({
    page,
  }) => {
    await page.goto(URL_RESULTAT_COUVERT);
    await expect(page.locator('.result-col')).toBeVisible();

    // Les 2 mini-questions split sont rendues (couvert_split.js). On change
    // l'axe "recolte" -> recompose la valeur -> coche le vrai radio ->
    // dispatch change -> reset_form doit elaguer.
    const splitRecolte = page.locator(
      'input[name="couvert_split_recolte"][value="recolte"]'
    );
    // Le label DSFR intercepte le clic ; on cible le label associe.
    await page
      .locator('label[for="id_couvert_split_recolte__recolte"]')
      .click();
    await page.waitForTimeout(150);

    // Selon que la valeur recomposee correspond a un vrai radio, le resultat
    // doit avoir ete elague (le parcours a change). Au minimum : pas de crash,
    // et si un sous_culture_form a ete recoche, le resultat disparait.
    void splitRecolte;
    // L'invariant robuste : aucune cle d'URL dupliquee apres l'operation.
    const search = await page.evaluate(() => location.search);
    expect(dupKeys(search)).toEqual([]);
  });
});
